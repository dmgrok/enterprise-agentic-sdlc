"""Run synthetic three-axis interventions and one real local cancellation."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kit.control import Controller, policy_digest, signed
from kit.supervisor import supervise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    policy = json.loads((ROOT / "resources/control-policy.json").read_text())
    key = b"synthetic-local-demo-key-not-a-real-secret"
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="sdlc-control-demo-") as folder:
        db = Path(folder) / "control.sqlite"
        control = Controller(db, key)
        def telemetry(run, sequence=0):
            return {"run_id": run, "revision": policy["revision"], "policy_digest": policy_digest(policy),
                    "sequence": sequence, "observed_at": time.time(),
                    "mission": {"objective_id": policy["objective_id"], "scope_violation": False, "progress": "advancing"},
                    "quality": {"checks": {name: "pass" for name in policy["mandatory_checks"]}, "repair_attempts": 0},
                    "spend": {"accounting": "reservation-ledger", "coverage": "complete"}}
        def start(run):
            control.create(run, policy)
            control.observe(run, signed(telemetry(run), key))
            control.command(run, "resume", "operator", "Synthetic demonstration authorised")
        try:
            start("mission")
            bad = telemetry("mission", 1)
            bad["mission"]["scope_violation"] = True
            control.observe("mission", signed(bad, key))
            outcomes.append({"scenario": "mission-scope-violation", **control.permit_output("mission")})

            start("quality")
            bad = telemetry("quality", 1)
            bad["quality"]["checks"]["artifact-schema"] = "fail"
            control.observe("quality", signed(bad, key))
            outcomes.append({"scenario": "quality-check-failure", **control.permit_output("quality")})
            control.observe("quality", signed(telemetry("quality", 2), key))
            assert control.status("quality")["state"] == "paused"
            control.command("quality", "resume", "operator", "Reviewed corrected evidence")

            start("spend")
            _, reservation = control.reserve("spend", "too-expensive", 2000001, "read")
            outcomes.append({"scenario": "budget-denies-next-call", **reservation, **control.permit_output("spend")})

            start("running-process")
            marker = Path(folder) / "started"
            errors = []
            def stop_when_started():
                operator = Controller(db, key)
                try:
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    operator.command("running-process", "stop", "operator", "Manual emergency stop")
                except BaseException as exc:
                    errors.append(str(exc))
                finally:
                    operator.close()
            worker = threading.Thread(target=stop_when_started)
            worker.start()
            command = [sys.executable, "-c", "from pathlib import Path; import time; Path('started').touch(); time.sleep(20)"]
            result = supervise(control, "running-process", command, folder, 0.02, 0.05)
            worker.join(timeout=5)
            assert not errors, errors
            assert result["interrupted"] and result["exit_code"] < 0
            outcomes.append({"scenario": "stop-real-running-process", **result})
            report = {"mode": "synthetic-local-demo", "provider_calls": 0, "github_mutations": 0,
                      "outcomes": outcomes, "audit_events": len(control.audit("running-process"))}
            rendered = json.dumps(report, indent=2) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered)
            print(rendered, end="")
        finally:
            control.close()


if __name__ == "__main__":
    main()
