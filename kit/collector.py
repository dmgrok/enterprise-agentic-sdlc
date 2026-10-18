"""Independent deterministic collection from a downloaded work/ artifact directory."""

import argparse
import hashlib
import json
from pathlib import Path
import time

from jsonschema import ValidationError
from kit.contracts import validate
from kit.control import canonical, policy_digest, signed
from kit.gates import allowed_path


def collect(root, policy, run_id, sequence, repair_attempts=0):
    """The trusted downloader must verify GitHub run/attempt/revision provenance first."""
    root = Path(root)
    files = sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink())
    scope = (not root.is_symlink() and len(files) == 1 and not files[0].is_symlink()
             and all(not parent.is_symlink() for parent in files[0].parents if parent == root or root in parent.parents)
             and allowed_path("work/" + files[0].relative_to(root).as_posix(), policy["allowed_paths"]))
    valid, digest = False, None
    if scope:
        try:
            if files[0].stat().st_size > 1024 * 1024:
                raise ValueError("Artifact too large")
            artifact = json.loads(files[0].read_text())
            validate("intent", artifact)
            valid = (files[0].relative_to(root).as_posix() == artifact["work_item_id"] + "/intent.json"
                     and artifact["work_item_id"] == policy.get("work_item_id", artifact["work_item_id"]))
            if valid:
                digest = hashlib.sha256(canonical(artifact)).hexdigest()
        except (ValueError, OSError, ValidationError):
            valid = False
    quality = {"checks": {"scope": "pass" if scope else "fail", "artifact-schema": "pass" if valid else "fail"},
               "repair_attempts": repair_attempts}
    if digest:
        quality["artifact_digest"] = digest
    return {"run_id": run_id, "revision": policy["revision"], "policy_digest": policy_digest(policy),
            "sequence": sequence, "observed_at": time.time(),
            "mission": {"objective_id": policy["objective_id"], "scope_violation": not scope,
                        "progress": "advancing" if valid else "stalled"},
            "quality": quality, "spend": {"accounting": "reservation-ledger", "coverage": "complete"}}


def main():
    parser = argparse.ArgumentParser(description="Collect artifact schema/scope evidence, not semantic acceptance")
    parser.add_argument("--work-directory", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--repair-attempts", type=int, default=0)
    parser.add_argument("--key-file", required=True, type=Path)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    result = collect(args.work_directory, policy, args.run, args.sequence, args.repair_attempts)
    validate("telemetry", result)
    print(json.dumps(signed(result, args.key_file.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
