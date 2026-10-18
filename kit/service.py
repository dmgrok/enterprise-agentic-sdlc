"""Role-scoped HTTP controller and reservation-aware OpenAI chat proxy."""

import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request
import uuid

from jsonschema import ValidationError
from kit.contracts import validate
from kit.control import Controller, Denied, canonical, integer
from kit.gates import allowed_path


MAX_BODY = 2 * 1024 * 1024


class APIError(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def price(tokens, per_million):
    return (tokens * per_million + 999999) // 1000000


class Application:
    def __init__(self, database, telemetry_key, credentials, gateway, stage_root,
                 provider=None, provider_key=None, allow_loopback=False):
        self.database, self.telemetry_key = database, telemetry_key
        self.credentials, self.gateway = credentials, gateway
        self.stage_root = Path(stage_root).resolve()
        self.stage_root.mkdir(parents=True, exist_ok=True)
        self.provider_key = provider_key
        self.provider = provider or self._provider
        self.allow_loopback = allow_loopback
        if not isinstance(telemetry_key, bytes) or len(telemetry_key) < 32:
            raise Denied("A collector key of at least 32 bytes is required")
        for account in credentials:
            if (account.get("role") not in {"agent", "collector", "operator", "writer"}
                    or not re.fullmatch(r"[0-9a-f]{64}", account.get("token_sha256", ""))
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", account.get("run_id", ""))
                    or not account.get("actor")):
                raise Denied("Invalid service credential record")
        hashes = [c["token_sha256"] for c in credentials]
        if len(hashes) != len(set(hashes)):
            raise Denied("Each service role must have a distinct token")
        for name in ("context_tokens", "max_output_tokens", "input_microusd_per_million", "output_microusd_per_million"):
            if not integer(gateway.get(name), 1):
                raise Denied("Invalid gateway pricing or token limit")
        target = urlsplit(gateway["upstream"])
        local = target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost"}
        if ((target.scheme != "https" and not (local and allow_loopback)) or target.username
                or target.password or target.query or target.fragment):
            raise Denied("Provider must use HTTPS; loopback HTTP needs explicit fixture mode")
        if not isinstance(gateway.get("model"), str) or not gateway["model"]:
            raise Denied("A fixed gateway model is required")

    def connection(self):
        return Controller(self.database, self.telemetry_key)

    def authenticate(self, authorization):
        if not authorization.startswith("Bearer ") or len(authorization[7:]) < 32:
            raise APIError(401, "authentication-required")
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        for credential in self.credentials:
            if hmac.compare_digest(digest, credential["token_sha256"]):
                return credential
        raise APIError(401, "authentication-required")

    def _provider(self, payload):
        if not self.provider_key:
            raise APIError(503, "provider-credential-unavailable")
        request = Request(self.gateway["upstream"], data=canonical(payload), method="POST", headers={
            "Authorization": "Bearer " + self.provider_key, "Content-Type": "application/json"})
        # Fixed endpoint only. Redirects must not forward provider credentials.
        from urllib.request import HTTPRedirectHandler, build_opener
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with build_opener(NoRedirect).open(request, timeout=30) as response:
                data = response.read(MAX_BODY + 1)
                if len(data) > MAX_BODY:
                    raise APIError(502, "provider-response-too-large")
                return json.loads(data)
        except (HTTPError, URLError, TimeoutError, ValueError):
            raise APIError(502, "provider-result-unavailable") from None

    @staticmethod
    def pause(control, run_id, reason):
        def apply(data):
            if data["state"] != "stopped":
                data.update(state="paused", reasons=[reason], outputs_allowed=False,
                            resume_after_sequence=data["sequence"])
            return {"reason": reason}
        control._change(run_id, "gateway-error", apply)

    def infer(self, control, account, payload):
        if account["role"] != "agent":
            raise APIError(403, "agent-role-required")
        allowed = {"model", "messages", "max_tokens", "max_completion_tokens", "stream", "stream_options",
                   "temperature", "top_p", "tools", "tool_choice", "parallel_tool_calls", "stop",
                   "response_format", "seed", "presence_penalty", "frequency_penalty"}
        if set(payload) - allowed or payload.get("model") != self.gateway["model"]:
            raise APIError(400, "unsupported-model-or-request-fields")
        if (not isinstance(payload.get("messages"), list) or not payload["messages"]
                or any(not isinstance(m, dict) or not isinstance(m.get("role"), str)
                       or (m.get("content") is not None and not isinstance(m["content"], str))
                       for m in payload["messages"])):
            raise APIError(400, "text-and-tool-messages-required")
        if "max_tokens" in payload and "max_completion_tokens" in payload:
            raise APIError(400, "ambiguous-output-limit")
        output = payload.get("max_tokens", payload.get("max_completion_tokens", self.gateway["max_output_tokens"]))
        if not integer(output, 1) or output > self.gateway["max_output_tokens"]:
            raise APIError(400, "output-limit-exceeded")
        if type(payload.get("stream", False)) is not bool:
            raise APIError(400, "invalid-stream-option")
        maximum = (price(self.gateway["context_tokens"], self.gateway["input_microusd_per_million"])
                   + price(output, self.gateway["output_microusd_per_million"]))
        call_id, run_id = uuid.uuid4().hex, account["run_id"]
        _, reservation = control.reserve(run_id, call_id, maximum, "inference")
        if not reservation["allowed"]:
            raise APIError(409, reservation["reason"])
        request = dict(payload, stream=False)
        request.pop("stream_options", None)
        if "max_tokens" not in request and "max_completion_tokens" not in request:
            request["max_tokens"] = output
        try:
            result = self.provider(request)
            usage = result["usage"]
            incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
            if (not integer(incoming) or not integer(outgoing) or not isinstance(result.get("choices"), list)
                    or not result["choices"] or not isinstance(result.get("id"), str)
                    or not integer(result.get("created")) or result.get("model") != self.gateway["model"]
                    or any(not isinstance(c, dict) or not integer(c.get("index"))
                           or not isinstance(c.get("message"), dict) for c in result["choices"])):
                raise APIError(502, "provider-usage-invalid")
            actual = (price(incoming, self.gateway["input_microusd_per_million"])
                      + price(outgoing, self.gateway["output_microusd_per_million"]))
            state = control.settle(run_id, call_id, actual)
            if incoming > self.gateway["context_tokens"] or outgoing > output:
                self.pause(control, run_id, "provider-token-bound-exceeded")
                raise APIError(502, "provider-token-bound-exceeded")
            if state["state"] != "running":
                raise APIError(409, "run-interrupted-before-response")
            if not payload.get("stream", False):
                return 200, result, "application/json"
            # Buffer upstream completion, settle cost, then emit an OpenAI SSE response.
            choices = []
            for choice in result["choices"]:
                message = dict(choice["message"])
                if "tool_calls" in message:
                    message["tool_calls"] = [dict(tool, index=i) for i, tool in enumerate(message["tool_calls"])]
                choices.append({"index": choice["index"], "delta": message, "finish_reason": choice.get("finish_reason")})
            chunk = {"id": result["id"], "object": "chat.completion.chunk", "created": result["created"],
                     "model": result["model"], "choices": choices, "usage": usage}
            data = b"data: " + canonical(chunk) + b"\n\ndata: [DONE]\n\n"
            return 200, data, "text/event-stream"
        except Exception:
            self.pause(control, run_id, "provider-result-needs-reconciliation")
            raise APIError(502, "provider-result-needs-reconciliation") from None

    def handle(self, method, path, authorization, payload):
        account = self.authenticate(authorization)
        control = self.connection()
        try:
            if method == "POST" and path == "/v1/chat/completions":
                return self.infer(control, account, payload)
            match = re.fullmatch(r"/runs/([A-Za-z0-9_-]{1,100})(?:/(telemetry|commands|admission|output-check|stage|audit))?", path)
            if not match or match[1] != account["run_id"]:
                raise APIError(403, "run-scope-denied")
            run_id, operation = match[1], match[2]
            if method == "POST" and operation is None and account["role"] == "operator":
                validate("control-policy", payload["policy"])
                if not payload["policy"].get("github_target") or not payload["policy"].get("work_item_id"):
                    raise APIError(400, "github-target-and-work-item-required")
                result = control.create(run_id, payload["policy"])
            elif method == "GET" and operation is None:
                result = control.status(run_id)
            elif method == "GET" and operation == "audit" and account["role"] == "operator":
                result = control.audit(run_id)
            elif method == "POST" and operation == "telemetry" and account["role"] == "collector":
                try:
                    validate("telemetry", payload["event"])
                except (ValidationError, KeyError, TypeError):
                    self.pause(control, run_id, "collector-schema-failed")
                    raise APIError(409, "telemetry-schema-rejected") from None
                state, acceptance = control.observe(run_id, payload)
                if not acceptance["accepted"]:
                    raise APIError(409, "telemetry-rejected")
                result = {"state": state["state"], **acceptance}
            elif method == "POST" and operation == "commands" and account["role"] == "operator":
                result = control.command(run_id, payload["action"], account["actor"], payload["reason"])
            elif method == "POST" and operation in {"admission", "output-check"} and account["role"] == "agent":
                self.binding(control, run_id, payload)
                if operation == "output-check":
                    state = control.status(run_id)
                    artifact_digest = state["axes"].get("quality", {}).get("artifact_digest", "")
                    if not re.fullmatch(r"[0-9a-f]{64}", artifact_digest):
                        raise APIError(409, "independent-artifact-evidence-required")
                result = control.permit_output(run_id)
                if not result["allowed"]:
                    raise APIError(409, "controller-denied")
            elif method == "POST" and operation == "stage" and account["role"] == "writer":
                self.binding(control, run_id, payload["binding"])
                validate("intent", payload["artifact"])
                state = control.status(run_id)
                destination = payload["path"]
                expected = "work/" + payload["artifact"]["work_item_id"] + "/intent.json"
                if (payload["artifact"]["work_item_id"] != state["policy"]["work_item_id"]
                        or destination != expected or not allowed_path(destination, state["policy"]["allowed_paths"])):
                    raise APIError(403, "artifact-path-denied")
                actual_digest = hashlib.sha256(canonical(payload["artifact"])).hexdigest()
                if state["axes"].get("quality", {}).get("artifact_digest") != actual_digest:
                    raise APIError(409, "artifact-evidence-digest-mismatch")
                # Store only inside a controller-owned directory, with a flat, derived filename.
                target = self.stage_root / (run_id + "." + actual_digest + ".intent.json")
                if target.is_symlink():
                    raise APIError(409, "stage-target-invalid")
                def write():
                    with tempfile.NamedTemporaryFile(dir=self.stage_root, mode="wb", delete=False) as out:
                        temporary = Path(out.name)
                        out.write(canonical(payload["artifact"]))
                    try:
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                _, result = control.apply_output(run_id, payload["binding"]["revision"], write,
                                                 {"artifact_digest": actual_digest, "path": destination})
                if not result["applied"]:
                    raise APIError(409, "output-denied")
                result = {"staged": True, "artifact_digest": hashlib.sha256(target.read_bytes()).hexdigest(),
                          "run_id": run_id, "path": destination}
            else:
                raise APIError(403, "role-or-method-denied")
            return 200, result, "application/json"
        finally:
            control.close()

    @staticmethod
    def binding(control, run_id, binding):
        validate("binding", binding)
        state = control.status(run_id)
        expected = state["policy"].get("github_target")
        if binding["revision"] != state["policy"]["revision"] or expected != {
            "repository": binding["repository"], "run_id": binding["github_run_id"], "attempt": binding["attempt"]
        }:
            raise APIError(409, "github-binding-mismatch")


def server(application, host="127.0.0.1", port=8080):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.process()
        def do_POST(self):
            self.process()
        def process(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                    raise APIError(413, "request-too-large-or-chunked")
                payload = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(payload, dict):
                    raise APIError(400, "json-object-required")
                code, result, content_type = application.handle(
                    self.command, self.path, self.headers.get("Authorization", ""), payload)
            except APIError as exc:
                code, result, content_type = exc.status, {"error": exc.reason}, "application/json"
            except (Denied, ValidationError, ValueError, TypeError, KeyError, sqlite3.Error):
                code, result, content_type = 409, {"error": "invalid-or-unavailable-control-state"}, "application/json"
            except Exception:
                code, result, content_type = 503, {"error": "controller-unavailable"}, "application/json"
            body = result if isinstance(result, bytes) else canonical(result)
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
    instance = ThreadingHTTPServer((host, port), Handler)
    instance.daemon_threads = True
    return instance


def main():
    parser = argparse.ArgumentParser()
    for field in ("database", "key-file", "auth-file", "gateway-config", "stage-root"):
        parser.add_argument("--" + field, required=True, type=Path)
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--allow-loopback-provider", action="store_true")
    args = parser.parse_args()
    app = Application(args.database, args.key_file.read_bytes(), json.loads(args.auth_file.read_text()),
                      json.loads(args.gateway_config.read_text()), args.stage_root,
                      provider_key=os.getenv("KIT_UPSTREAM_API_KEY"), allow_loopback=args.allow_loopback_provider)
    server(app, port=args.port).serve_forever()


if __name__ == "__main__":
    main()
