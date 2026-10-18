"""Provision private local service configuration without printing credentials."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.settings import load


def provision(directory, run_id, policy_path=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("Invalid run ID")
    settings = load(policy_path or ROOT / ".kit/agent-policy.yml")
    directory.mkdir(mode=0o700)
    credentials = {role: secrets.token_urlsafe(32) for role in ("operator", "collector", "agent", "writer")}
    records = [{"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "role": role,
                "run_id": run_id, "actor": "operator" if role == "operator" else role}
               for role, token in credentials.items()]
    files = {"collector.key": os.urandom(32), "auth.json": json.dumps(records, indent=2).encode(),
             "credentials.json": json.dumps(credentials, indent=2).encode(),
             "policy.json": json.dumps(settings["runtime"], indent=2).encode(),
             "gateway.json": json.dumps({"model": "fixture-model",
                 "upstream": "https://provider.example.invalid/v1/chat/completions",
                 "context_tokens": 1000, "max_output_tokens": 100,
                 "input_microusd_per_million": 1000000, "output_microusd_per_million": 2000000}, indent=2).encode()}
    for name, data in files.items():
        with os.fdopen(os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
            stream.write(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--policy", type=Path, default=ROOT / ".kit/agent-policy.yml")
    args = parser.parse_args()
    provision(args.directory, args.run, args.policy)
    print("Created private configuration in", args.directory)
    print("Replace fixture gateway settings and enroll the exact GitHub target before use.")


if __name__ == "__main__":
    main()
