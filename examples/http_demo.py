"""Real loopback HTTP integration; fake provider, ephemeral credentials, no GitHub writes."""

import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.collector import collect
from kit.control import policy_digest, signed
from kit.service import Application, server


def main():
    with tempfile.TemporaryDirectory(prefix="sdlc-http-fixture-") as folder:
        root = Path(folder)
        key = secrets.token_bytes(32)
        tokens = {r: secrets.token_urlsafe(32) for r in ("operator", "collector", "agent", "writer")}
        auth = [{"role": role, "actor": "operator" if role == "operator" else role,
                 "run_id": "FIXTURE", "token_sha256": hashlib.sha256(token.encode()).hexdigest()}
                for role, token in tokens.items()]
        policy = json.loads((ROOT / "resources/control-policy.json").read_text())
        policy["github_target"] = {"repository": "example/fixture", "run_id": 123, "attempt": 1}
        policy["work_item_id"] = "DEMO-1"
        binding = {"repository": "example/fixture", "github_run_id": 123, "attempt": 1, "revision": policy["revision"]}
        artifact = json.loads((ROOT / "resources/intent-template.json").read_text())
        artifact.update(work_item_id="DEMO-1", owner="fixture-owner", problem="An example needs documentation",
                        users=["fixture-reader"], outcome="A bounded intent is drafted")
        calls = []
        def fake_provider(payload):
            calls.append(payload)
            return {"id": "fixture-completion", "object": "chat.completion", "created": 1,
                    "model": "fixture-model", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(artifact)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 50}}
        app = Application(root / "controller.db", key, auth, {
            "model": "fixture-model", "upstream": "https://provider.example.invalid/v1/chat/completions",
            "context_tokens": 1000, "max_output_tokens": 100,
            "input_microusd_per_million": 1000000, "output_microusd_per_million": 2000000},
            root / "staged", provider=fake_provider)
        instance = server(app, port=0)
        worker = threading.Thread(target=instance.serve_forever)
        worker.start()
        base = "http://127.0.0.1:" + str(instance.server_port)
        def request(role, path, payload=None, method="POST"):
            query = Request(base + path, method=method,
                            data=json.dumps(payload).encode() if payload is not None else None,
                            headers={"Content-Type": "application/json", "Authorization": "Bearer " + tokens[role]})
            with urlopen(query, timeout=5) as response:
                return json.load(response)
        try:
            request("operator", "/runs/FIXTURE", {"policy": policy})
            readiness = {"run_id": "FIXTURE", "revision": policy["revision"], "policy_digest": policy_digest(policy),
                         "sequence": 0, "observed_at": time.time(),
                         "mission": {"objective_id": policy["objective_id"], "scope_violation": False, "progress": "advancing"},
                         "quality": {"checks": {"scope": "pass", "artifact-schema": "pass"}, "repair_attempts": 0},
                         "spend": {"accounting": "reservation-ledger", "coverage": "complete"}}
            request("collector", "/runs/FIXTURE/telemetry", signed(readiness, key))
            request("operator", "/runs/FIXTURE/commands", {"action": "resume", "reason": "Fixture authorised"})
            assert request("agent", "/runs/FIXTURE/admission", binding)["allowed"]
            completion = request("agent", "/v1/chat/completions", {
                "model": "fixture-model", "messages": [{"role": "user", "content": "Draft intent"}], "max_tokens": 100})
            work = root / "downloaded-work"
            target = work / "DEMO-1/intent.json"
            target.parent.mkdir(parents=True)
            target.write_text(completion["choices"][0]["message"]["content"])
            observed = collect(work, policy, "FIXTURE", 1)
            request("collector", "/runs/FIXTURE/telemetry", signed(observed, key))
            assert request("agent", "/runs/FIXTURE/output-check", binding)["allowed"]
            staged = request("writer", "/runs/FIXTURE/stage", {
                "binding": binding, "artifact": json.loads(target.read_text()), "path": "work/DEMO-1/intent.json"})
            state = request("operator", "/runs/FIXTURE", method="GET")
            request("operator", "/runs/FIXTURE/commands", {"action": "stop", "reason": "Fixture emergency stop"})
            try:
                request("agent", "/v1/chat/completions", {
                    "model": "fixture-model", "messages": [{"role": "user", "content": "Try again"}]})
                raise AssertionError("Stopped run was admitted")
            except HTTPError as exc:
                assert exc.code == 409
                exc.close()
            assert len(calls) == 1
            print(json.dumps({"mode": "http-integration-fixture", "admission": "pass",
                              "provider": "fake", "provider_calls": len(calls),
                              "spent_microusd": state["spent_microusd"], "artifact_staged": staged["staged"],
                              "artifact_digest": staged["artifact_digest"], "stop_denied_next_call": True,
                              "github_writes": 0, "paid_calls": 0}, indent=2))
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
