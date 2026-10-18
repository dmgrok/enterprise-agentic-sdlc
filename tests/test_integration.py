import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jsonschema import ValidationError
from kit.contracts import check_schemas, validate
from kit.control import Controller, policy_digest, signed
from kit.collector import collect
from kit.ghaw import HOOK, governed_config, inspect_governed
from kit.service import APIError, Application, server
from tests.test_contract import fixture, POLICY as GATE_POLICY
from kit.gates import evaluate
from scripts.provision_control import provision

ROOT = Path(__file__).resolve().parents[1]
KEY = b"synthetic-integration-collector-key-only"


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.policy = json.loads((ROOT / "resources/control-policy.json").read_text())
        self.policy["github_target"] = {"repository": "example/fixture", "run_id": 123, "attempt": 1}
        self.policy["work_item_id"] = "DEMO-1"
        self.binding = {"repository": "example/fixture", "github_run_id": 123, "attempt": 1,
                        "revision": self.policy["revision"]}
        self.tokens = {role: ("synthetic-" + role + "-credential-" + "x" * 40)
                       for role in ("agent", "collector", "operator", "writer")}
        credentials = [{"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "role": role,
                        "run_id": "run-1", "actor": "operator" if role == "operator" else role}
                       for role, token in self.tokens.items()]
        self.calls = []
        self.response = {"id": "fixture-completion", "object": "chat.completion", "created": 1,
                         "model": "fixture-model", "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Synthetic intent"}}],
                         "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        def provider(payload):
            self.calls.append(payload)
            return copy.deepcopy(self.response)
        self.app = Application(root / "control.db", KEY, credentials, {
            "model": "fixture-model", "upstream": "https://provider.example.invalid/v1/chat/completions",
            "context_tokens": 1000, "max_output_tokens": 100,
            "input_microusd_per_million": 1000000, "output_microusd_per_million": 2000000},
            root / "staged", provider=provider)
        self.sequence = 0
        self.call("operator", "/runs/run-1", {"policy": self.policy})

    def tearDown(self):
        self.temp.cleanup()

    def call(self, role, path, payload=None, method="POST"):
        return self.app.handle(method, path, "Bearer " + self.tokens[role], payload or {})[1]

    def telemetry(self, changes=None):
        event = {"run_id": "run-1", "revision": self.policy["revision"], "policy_digest": policy_digest(self.policy),
                 "sequence": self.sequence, "observed_at": time.time(),
                 "mission": {"objective_id": self.policy["objective_id"], "scope_violation": False, "progress": "advancing"},
                 "quality": {"checks": {name: "pass" for name in self.policy["mandatory_checks"]}, "repair_attempts": 0},
                 "spend": {"accounting": "reservation-ledger", "coverage": "complete"}}
        self.sequence += 1
        if changes:
            changes(event)
        self.call("collector", "/runs/run-1/telemetry", signed(event, KEY))

    def start(self):
        self.telemetry()
        self.call("operator", "/runs/run-1/commands", {"action": "resume", "reason": "Fixture authorised"})

    def request(self, **changes):
        return {"model": "fixture-model", "messages": [{"role": "user", "content": "Draft intent"}],
                "max_tokens": 20, **changes}

    def test_role_separation_and_run_scope(self):
        for path, payload in (("commands", {"action": "resume", "reason": "Agent override"}),
                              ("telemetry", {"event": {}}), ("stage", {})):
            with self.assertRaises(APIError):
                self.call("agent", "/runs/run-1/" + path, payload)
        with self.assertRaises(APIError):
            self.call("operator", "/runs/other", {"policy": self.policy})
        self.assertEqual([], self.calls)

    def test_admission_requires_operator_and_exact_run_binding(self):
        with self.assertRaises(APIError):
            self.call("agent", "/runs/run-1/admission", self.binding)
        self.start()
        self.assertTrue(self.call("agent", "/runs/run-1/admission", self.binding)["allowed"])
        with self.assertRaises(APIError):
            self.call("agent", "/runs/run-1/admission", dict(self.binding, attempt=2))

    def test_gateway_reserves_and_settles_before_returning(self):
        self.start()
        result = self.call("agent", "/v1/chat/completions", self.request())
        self.assertEqual("fixture-completion", result["id"])
        state = self.call("operator", "/runs/run-1", method="GET")
        self.assertEqual(9, state["spent_microusd"])
        self.assertTrue(all(r["state"] == "settled" for r in state["reservations"].values()))
        self.assertFalse(self.calls[0]["stream"])

    def test_streaming_client_receives_buffered_settled_sse(self):
        self.start()
        status, body, mime = self.app.handle("POST", "/v1/chat/completions", "Bearer " + self.tokens["agent"],
                                           self.request(stream=True))
        self.assertEqual("text/event-stream", mime)
        self.assertIn(b"data: [DONE]", body)
        self.assertIn(b"chat.completion.chunk", body)
        self.assertEqual(200, status)

    def test_quality_pause_denies_next_provider_call_and_output(self):
        self.start()
        self.telemetry(lambda e: e["quality"]["checks"].update(scope="fail"))
        with self.assertRaises(APIError):
            self.call("agent", "/v1/chat/completions", self.request())
        with self.assertRaises(APIError):
            self.call("agent", "/runs/run-1/output-check", self.binding)
        self.assertEqual([], self.calls)

    def test_mission_stop_denies_provider_call(self):
        self.start()
        self.telemetry(lambda e: e["mission"].update(scope_violation=True))
        with self.assertRaises(APIError):
            self.call("agent", "/v1/chat/completions", self.request())
        self.assertEqual([], self.calls)

    def test_budget_denial_occurs_before_provider(self):
        self.start()
        self.app.gateway["context_tokens"] = 3000000
        with self.assertRaises(APIError):
            self.call("agent", "/v1/chat/completions", self.request())
        self.assertEqual([], self.calls)

    def test_unknown_usage_retains_reservation_and_pauses(self):
        self.start()
        self.response.pop("usage")
        with self.assertRaises(APIError):
            self.call("agent", "/v1/chat/completions", self.request())
        state = self.call("operator", "/runs/run-1", method="GET")
        self.assertEqual("paused", state["state"])
        self.assertTrue(any(r["state"] == "reserved" for r in state["reservations"].values()))

    def test_provider_exception_retains_reservation_and_pauses(self):
        self.start()
        def unavailable(payload):
            raise RuntimeError("Simulated upstream failure")
        self.app.provider = unavailable
        with self.assertRaises(APIError):
            self.call("agent", "/v1/chat/completions", self.request())
        state = self.call("operator", "/runs/run-1", method="GET")
        self.assertEqual("paused", state["state"])
        self.assertTrue(any(r["state"] == "reserved" for r in state["reservations"].values()))

    def test_wrong_model_oversized_output_and_multimodal_are_denied(self):
        self.start()
        for changes in ({"model": "unpriced-model"}, {"max_tokens": 101},
                        {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]}):
            with self.assertRaises(APIError):
                self.call("agent", "/v1/chat/completions", self.request(**changes))
        self.assertEqual([], self.calls)

    def test_stage_broker_checks_schema_binding_and_state(self):
        self.start()
        artifact = json.loads((ROOT / "resources/intent-template.json").read_text())
        artifact["work_item_id"] = "DEMO-1"
        self.telemetry(lambda e: e["quality"].update(artifact_digest=hashlib.sha256(
            json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()))
        payload = {"binding": self.binding, "artifact": artifact, "path": "work/DEMO-1/intent.json"}
        result = self.call("writer", "/runs/run-1/stage", payload)
        self.assertTrue(result["staged"])
        self.call("operator", "/runs/run-1/commands", {"action": "stop", "reason": "Stop before next write"})
        with self.assertRaises(APIError):
            self.call("writer", "/runs/run-1/stage", payload)
        self.assertEqual(1, len(list(self.app.stage_root.iterdir())))

    def test_malformed_collector_data_pauses_immediately(self):
        self.start()
        with self.assertRaises(APIError):
            self.call("collector", "/runs/run-1/telemetry", {"event": {}, "signature": "forged"})
        self.assertEqual("paused", self.call("operator", "/runs/run-1", method="GET")["state"])

    def test_http_round_trip_and_authentication(self):
        instance = server(self.app, port=0)
        worker = threading.Thread(target=instance.serve_forever)
        worker.start()
        base = "http://127.0.0.1:" + str(instance.server_port)
        try:
            self.start()
            request = Request(base + "/v1/chat/completions", data=json.dumps(self.request()).encode(),
                              headers={"Authorization": "Bearer " + self.tokens["agent"], "Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                self.assertEqual("fixture-completion", json.load(response)["id"])
            environment = {**os.environ, "KIT_URL": base, "KIT_RUN": "run-1", "KIT_PHASE": "admission",
                           "KIT_REPOSITORY": "example/fixture", "KIT_GITHUB_RUN_ID": "123",
                           "KIT_GITHUB_ATTEMPT": "1", "KIT_REVISION": self.policy["revision"],
                           "KIT_TOKEN": self.tokens["agent"]}
            admitted = subprocess.run([sys.executable, "-c", HOOK], env=environment, capture_output=True, text=True, timeout=5)
            self.assertEqual(0, admitted.returncode, admitted.stderr)
            environment["KIT_GITHUB_ATTEMPT"] = "2"
            denied_hook = subprocess.run([sys.executable, "-c", HOOK], env=environment,
                                         capture_output=True, text=True, timeout=5)
            self.assertNotEqual(0, denied_hook.returncode)
            self.assertNotIn(self.tokens["agent"], denied_hook.stderr)
            with self.assertRaises(HTTPError) as denied:
                urlopen(base + "/runs/run-1", timeout=5)
            self.assertEqual(401, denied.exception.code)
            denied.exception.close()
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(timeout=5)


class ContractTests(unittest.TestCase):
    def test_schema_definitions_and_existing_reports(self):
        check_schemas()
        validate("control-policy", json.loads((ROOT / "resources/control-policy.json").read_text()))
        validate("intent", json.loads((ROOT / "resources/intent-template.json").read_text()))
        f = fixture()
        validate("evidence", evaluate(GATE_POLICY, f["subject"], f["evidence"]))

    def test_artifact_cannot_claim_approval(self):
        artifact = json.loads((ROOT / "resources/intent-template.json").read_text())
        artifact["approved"] = True
        with self.assertRaises(ValidationError):
            validate("intent", artifact)

    def test_governed_profile_rejects_hook_and_write_drift(self):
        config = governed_config()
        self.assertEqual([], inspect_governed(config))
        for mutation in (lambda c: c["safe-outputs"].update(staged=False),
                         lambda c: c.update(jobs={}),
                         lambda c: c["engine"]["harness"].update({"max-retries": 3}),
                         lambda c: c["pre-agent-steps"][0].update(run="echo allowed")):
            changed = copy.deepcopy(config)
            mutation(changed)
            self.assertTrue(inspect_governed(changed))

    def test_independent_collector_checks_actual_files(self):
        policy = json.loads((ROOT / "resources/control-policy.json").read_text())
        artifact = json.loads((ROOT / "resources/intent-template.json").read_text())
        artifact["work_item_id"] = "DEMO-1"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "DEMO-1/intent.json"
            target.parent.mkdir()
            target.write_text(json.dumps(artifact))
            good = collect(root, policy, "run-1", 1)
            validate("telemetry", good)
            self.assertEqual("pass", good["quality"]["checks"]["artifact-schema"])
            self.assertIn("artifact_digest", good["quality"])
            artifact["approved"] = True
            target.write_text(json.dumps(artifact))
            bad = collect(root, policy, "run-1", 2)
            self.assertEqual("fail", bad["quality"]["checks"]["artifact-schema"])
            self.assertNotIn("artifact_digest", bad["quality"])
            (root / "escape.py").write_text("unexpected")
            self.assertTrue(collect(root, policy, "run-1", 3)["mission"]["scope_violation"])

    def test_private_provisioning_uses_distinct_scoped_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "private"
            provision(root, "WORK-1")
            credentials = json.loads((root / "credentials.json").read_text())
            auth = json.loads((root / "auth.json").read_text())
            self.assertEqual(4, len(set(credentials.values())))
            self.assertEqual(32, len((root / "collector.key").read_bytes()))
            for entry in auth:
                self.assertEqual("WORK-1", entry["run_id"])
                self.assertEqual(hashlib.sha256(credentials[entry["role"]].encode()).hexdigest(), entry["token_sha256"])
                self.assertNotIn(credentials[entry["role"]], (root / "auth.json").read_text())
            self.assertEqual(0o700, root.stat().st_mode & 0o777)
            self.assertEqual(0o600, (root / "credentials.json").stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
