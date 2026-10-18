"""Local process stop adapter and opt-in GitHub cancellation adapter."""

import json
import os
import re
import signal
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kit.control import Denied
from kit.gates import revision


def terminate_group(process, grace_seconds=1):
    # Reap the direct child even when a platform denies signaling its process group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        if process.poll() is None:
            process.terminate()
    time.sleep(grace_seconds)
    process.poll()
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        if process.poll() is None:
            process.kill()
        # A process-group denial cannot prove that descendants have stopped.
        process.wait(timeout=5)
        raise Denied("Process-group termination could not be confirmed")
    return process.wait(timeout=5)


def supervise(controller, run_id, command, cwd, poll_seconds=0.1, grace_seconds=1):
    if not command or controller.status(run_id)["state"] != "running":
        raise Denied("Resume a healthy run before starting an attempt")
    # Do not inherit controller credentials. Same-UID filesystem isolation is not provided here.
    child_env = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TMPDIR") if name in os.environ}
    process = subprocess.Popen(command, cwd=cwd, env=child_env, start_new_session=True)
    stopped = False
    try:
        while process.poll() is None:
            state = controller.status(run_id)
            if state["state"] != "running":
                stopped = True
                terminate_group(process, grace_seconds)
                break
            time.sleep(poll_seconds)
        # Kill any surviving descendants even if their parent exited first.
        terminate_group(process, grace_seconds)
        if process.returncode != 0:
            def failed(data):
                if data["state"] != "stopped":
                    data.update(state="paused", reasons=["local-process-failed"], outputs_allowed=False)
                return {"exit_code": process.returncode}
            controller._change(run_id, "process-exit", failed)
        status = controller.status(run_id)
        return {"run_id": run_id, "exit_code": process.returncode,
                "interrupted": stopped, "state": status["state"],
                "outputs_allowed": status["outputs_allowed"] and process.returncode == 0}
    except BaseException:
        def failed(data):
            if data["state"] != "stopped":
                data.update(state="paused", reasons=["supervisor-error"], outputs_allowed=False)
            return {"error": "termination-or-supervision-failed"}
        controller._change(run_id, "supervisor-error", failed)
        try:
            terminate_group(process, grace_seconds)
        finally:
            process.poll()
        raise


class GitHubCancellation:
    """The token belongs to the external controller, never to the agent job."""

    def __init__(self, repository, run_id, expected_revision, expected_attempt, token=None, transport=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise Denied("Invalid repository")
        if type(run_id) is not int or run_id < 1 or not revision(expected_revision):
            raise Denied("Invalid run ID or revision")
        if type(expected_attempt) is not int or expected_attempt < 1:
            raise Denied("Invalid run attempt")
        self.repository, self.run_id = repository, run_id
        self.revision, self.attempt, self.token = expected_revision, expected_attempt, token
        self.transport = transport or self._request
        self.base = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"

    def _request(self, method, url):
        if not self.token:
            raise Denied("A controller-only GitHub token is required")
        req = Request(url, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": "Bearer " + self.token,
            "X-GitHub-Api-Version": "2026-03-10"})
        try:
            with urlopen(req, timeout=10) as response:
                body = response.read()
                return response.status, json.loads(body) if body else {}
        except HTTPError as exc:
            # Never propagate bodies or request headers into audit output.
            return exc.code, {}
        except (URLError, TimeoutError, ValueError):
            return 0, {}

    def cancel(self, execute=False, grace_seconds=5):
        if not execute:
            return {"mode": "dry-run", "cancel": self.base + "/cancel",
                    "fallback": self.base + "/force-cancel", "termination_confirmed": False}
        run = self.status()
        if run.get("status") == "completed":
            return {"termination_confirmed": run.get("conclusion") == "cancelled",
                    "completed": True, "conclusion": run.get("conclusion")}
        code, _ = self.transport("POST", self.base + "/cancel")
        if code not in (202, 409):
            return {"termination_confirmed": False, "error": "cancel-request-failed", "status": code}
        time.sleep(min(max(grace_seconds, 0), 30))
        run = self.status()
        forced = False
        if run.get("status") != "completed":
            forced = True
            code, _ = self.transport("POST", self.base + "/force-cancel")
            if code not in (202, 409):
                return {"termination_confirmed": False, "error": "force-cancel-failed", "status": code}
            run = self.status()
        return {"termination_confirmed": run.get("status") == "completed" and run.get("conclusion") == "cancelled",
                "force_requested": forced, "status": run.get("status"), "conclusion": run.get("conclusion")}

    def status(self):
        code, run = self.transport("GET", self.base)
        if (code != 200 or not isinstance(run, dict) or run.get("id") != self.run_id
                or run.get("head_sha") != self.revision or run.get("run_attempt") != self.attempt
                or not isinstance(run.get("repository"), dict)
                or run["repository"].get("full_name", "").lower() != self.repository.lower()):
            raise Denied("GitHub run binding could not be verified")
        return run


def watch_github(controller, run_id, adapter, poll_seconds=2, execute=False):
    """Independent watchdog; receives telemetry through other controller connections."""
    if not execute:
        return {"mode": "dry-run", "trigger": "any-axis-unhealthy-or-operator-pause-stop",
                **adapter.cancel()}
    if not 0 < poll_seconds <= 30:
        raise Denied("Polling interval must be between zero and 30 seconds")
    while True:
        state = controller.status(run_id)
        if state["state"] == "running":
            try:
                run = adapter.status()
            except Denied:
                def unavailable(data):
                    if data["state"] != "stopped":
                        data.update(state="paused", reasons=["github-status-unavailable"], outputs_allowed=False,
                                    resume_after_sequence=data["sequence"])
                    return {"error": "github-status-unavailable"}
                controller._change(run_id, "github-status", unavailable)
                state = controller.status(run_id)
            else:
                if run.get("status") == "completed":
                    def complete(data):
                        if data["state"] != "stopped":
                            data.update(state="paused", reasons=["awaiting-final-gate"], outputs_allowed=False,
                                        resume_after_sequence=data["sequence"])
                        return {"conclusion": run.get("conclusion")}
                    controller._change(run_id, "github-completed", complete)
                    return {"completed": True, "conclusion": run.get("conclusion"), "outputs_allowed": False}
        if state["state"] != "running":
            try:
                result = adapter.cancel(execute=True)
            except Denied:
                result = {"termination_confirmed": False, "error": "cancellation-binding-or-api-error"}
            controller._change(run_id, "github-cancellation", lambda d: result)
            return {"control_state": state["state"], **result}
        time.sleep(poll_seconds)
