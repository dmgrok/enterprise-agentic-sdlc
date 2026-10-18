"""Operator CLI. Keep DB, policy and HMAC key inaccessible to agent runtimes."""

import argparse
import json
import os
from pathlib import Path
import sqlite3

from kit.control import Controller, Denied, signed
from kit.supervisor import GitHubCancellation, supervise, watch_github


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--run", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--policy", required=True, type=Path)
    observe = commands.add_parser("observe")
    observe.add_argument("--envelope", required=True, type=Path)
    sign = commands.add_parser("sign")
    sign.add_argument("--event", required=True, type=Path)
    for action in ("pause", "stop", "resume"):
        command = commands.add_parser(action)
        command.add_argument("--actor", required=True)
        command.add_argument("--reason", required=True)
    for action in ("status", "audit", "permit-output"):
        commands.add_parser(action)
    reserve = commands.add_parser("reserve")
    reserve.add_argument("--call", required=True)
    reserve.add_argument("--maximum-microusd", required=True, type=int)
    reserve.add_argument("--tool", required=True)
    reserve.add_argument("--path")
    settle = commands.add_parser("settle")
    settle.add_argument("--call", required=True)
    settle.add_argument("--actual-microusd", required=True, type=int)
    local = commands.add_parser("supervise")
    local.add_argument("--cwd", required=True, type=Path)
    local.add_argument("process", nargs=argparse.REMAINDER)
    for action in ("cancel-github", "watch-github"):
        cancel = commands.add_parser(action)
        cancel.add_argument("--repository", required=True)
        cancel.add_argument("--github-run-id", required=True, type=int)
        cancel.add_argument("--attempt", required=True, type=int)
        cancel.add_argument("--actor", required=True)
        cancel.add_argument("--reason", required=True)
        cancel.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    controller = None
    try:
        key = args.key_file.read_bytes()
        controller = Controller(args.database, key)
        command = args.command
        if command == "create":
            result = controller.create(args.run, json.loads(args.policy.read_text()))
        elif command == "sign":
            result = signed(json.loads(args.event.read_text()), key)
        elif command == "observe":
            data, acceptance = controller.observe(args.run, json.loads(args.envelope.read_text()))
            result = {"state": data["state"], **acceptance}
        elif command in ("pause", "stop", "resume"):
            result = controller.command(args.run, command, args.actor, args.reason)
        elif command == "status":
            result = controller.status(args.run)
        elif command == "audit":
            result = controller.audit(args.run)
        elif command == "permit-output":
            result = controller.permit_output(args.run)
        elif command == "reserve":
            _, result = controller.reserve(args.run, args.call, args.maximum_microusd, args.tool, args.path)
        elif command == "settle":
            result = controller.settle(args.run, args.call, args.actual_microusd)
        elif command == "supervise":
            process = args.process[1:] if args.process[:1] == ["--"] else args.process
            result = supervise(controller, args.run, process, args.cwd)
        elif command in ("cancel-github", "watch-github"):
            data = controller.status(args.run)
            if args.actor not in data["policy"]["operators"]:
                raise Denied("Operator is not authorised")
            target = {"repository": args.repository, "run_id": args.github_run_id, "attempt": args.attempt}
            if args.execute and data["policy"].get("github_target") != target:
                raise Denied("Enroll the exact GitHub target in trusted policy before execution")
            adapter = GitHubCancellation(args.repository, args.github_run_id,
                                         data["policy"]["revision"], args.attempt, os.getenv("KIT_CONTROLLER_GITHUB_TOKEN"))
            if command == "cancel-github":
                if args.execute:
                    controller.command(args.run, "stop", args.actor, args.reason)
                result = adapter.cancel(execute=args.execute)
                if args.execute:
                    controller._change(args.run, "github-cancellation", lambda d: result)
            else:
                result = watch_github(controller, args.run, adapter, execute=args.execute)
        print(json.dumps(result, indent=2))
        if ((command in ("reserve", "permit-output") and result.get("allowed") is False)
                or (command == "observe" and result.get("accepted") is False)
                or (command == "supervise" and result.get("outputs_allowed") is False)):
            return 1
        if (command in ("cancel-github", "watch-github") and args.execute
                and not result.get("termination_confirmed")
                and not (command == "watch-github" and result.get("completed"))):
            return 1
        return 0
    except (Denied, OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
        print(json.dumps({"decision": "error", "reason": str(exc)}))
        return 2
    finally:
        if controller:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
