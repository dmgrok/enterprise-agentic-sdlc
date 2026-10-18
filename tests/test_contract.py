import copy
import json
from pathlib import Path
import unittest

from kit.gates import FIELDS, PREVIOUS, digest, evaluate, allowed_path
from kit.profile import inspect, read_frontmatter, Loader
import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "resources/policy.json").read_text())


def fixture(gate="pull_request", risk="standard"):
    sha = "a" * 40
    prior = "b" * 40
    subject = {
        "work_item_id": "DEMO-1", "gate": gate, "version": 1, "owner": "engineer",
        "decision": "proposed", "evidence": ["https://github.com/example/fixture/issues/1"],
        "risk_tier": risk, "predecessor_revision": prior,
        **{key: ["Synthetic example"] for key in FIELDS[gate]},
    }
    if gate == "pull_request":
        subject.update(plan_revision=prior, changed_paths=["src/example.py"])
    if gate == "release":
        subject.update(approved_revision=sha, environment="demo-release")
    reviewers = {
        "intent": ["product-owner"], "specification": ["product-owner", "tech-owner"],
        "plan": ["engineer"], "pull_request": ["tech-owner"],
        "release": ["release-owner"], "incident": ["incident-owner"],
    }[gate]
    if risk == "high":
        reviewers = [*reviewers, "security-owner"]
    artifact = {"allowed_paths": ["src/**"], "summary": "Synthetic merged predecessor"}
    evidence = {
        "source": "synthetic-fixture", "api_status": "ok", "classified_risk": risk,
        "subject_revision": sha, "policy_revision": "c" * 40, "policy_digest": digest(POLICY),
        "author": "author", "invoking_actor": "author",
        "predecessor": {"gate": PREVIOUS[gate], "work_item_id": "DEMO-1", "revision": prior,
                        "decision": "pass", "merged_to_default": True, "artifact": artifact,
                        "content_digest": digest(artifact)},
        "reviews": [{"actor": actor, "actor_type": "User", "state": "APPROVED",
                     "revision": sha, "id": i + 1,
                     "url": f"https://github.com/example/fixture/pull/1#pullrequestreview-{i+1}"}
                    for i, actor in enumerate(reviewers)],
        "tests": {"revision": sha, "command": "python -m unittest", "exit_status": 0,
                  "artifact_digest": "d" * 64},
        "threat_detection": "pass",
        "environment_approvals": {key: {"approved": True, "actor": reviewers[0], "revision": sha}
                                  for key in ("before_agent", "before_write")},
        "release_environment": {"name": "demo-release", "approved": True,
                                "actor": reviewers[0], "revision": sha},
    }
    return {"subject": subject, "evidence": evidence}


class GateTests(unittest.TestCase):
    def result(self, f, policy=None):
        return evaluate(POLICY if policy is None else policy, f["subject"], f["evidence"])

    def test_six_gates_three_risks(self):
        for gate in FIELDS:
            for risk in ("low", "standard", "high"):
                with self.subTest(gate=gate, risk=risk):
                    self.assertEqual("pass", self.result(fixture(gate, risk))["decision"])

    def test_missing_fields(self):
        for gate, fields in FIELDS.items():
            for field in fields:
                with self.subTest(gate=gate, field=field):
                    f = fixture(gate)
                    del f["subject"][field]
                    self.assertEqual("blocked", self.result(f)["decision"])

    def test_unknown_risk_blocks(self):
        f = fixture()
        f["subject"]["risk_tier"] = "unknown"
        self.assertEqual("blocked", self.result(f)["decision"])

    def test_risk_downgrade_blocks(self):
        f = fixture(risk="high")
        f["subject"]["risk_tier"] = "low"
        self.assertEqual("blocked", self.result(f)["decision"])

    def test_agent_approval_field_has_no_authority(self):
        f = fixture()
        f["subject"]["approved"] = True
        f["evidence"]["reviews"] = []
        self.assertEqual("blocked", self.result(f)["decision"])

    def test_stale_bot_machine_and_self_reviews_block(self):
        for replacement in ({"revision": "f" * 40}, {"actor_type": "Bot"},
                            {"actor": "delivery-machine-user"}, {"actor": "author"},
                            {"actor": "fake[bot]"}):
            f = fixture()
            f["evidence"]["reviews"][0].update(replacement)
            self.assertEqual("blocked", self.result(f)["decision"])

    def test_newer_changes_requested_cancels_approval(self):
        f = fixture()
        change = {**f["evidence"]["reviews"][0], "id": 99, "state": "CHANGES_REQUESTED"}
        f["evidence"]["reviews"].append(change)
        self.assertEqual("blocked", self.result(f)["decision"])

    def test_predecessor_must_be_merged_same_item_unchanged(self):
        for replacement in ({"merged_to_default": False}, {"work_item_id": "OTHER"},
                            {"revision": "f" * 40}, {"content_digest": "0" * 64},
                            {"decision": "blocked"}):
            f = fixture()
            f["evidence"]["predecessor"].update(replacement)
            self.assertEqual("blocked", self.result(f)["decision"])

    def test_scope_and_traversal_block(self):
        for path in (".github/workflows/ci.yml", "src/../secrets", "/src/example.py",
                     "src\\example.py", "src//example.py", "tests/test.py"):
            f = fixture()
            f["subject"]["changed_paths"] = [path]
            self.assertEqual("blocked", self.result(f)["decision"])

    def test_path_scope_does_not_match_sibling(self):
        self.assertFalse(allowed_path("src-other/a.py", ["src/**"]))
        self.assertTrue(allowed_path("src/nested/a.py", ["src/**"]))

    def test_bad_or_stale_tests_block(self):
        for replacement in ({"revision": "f" * 40}, {"exit_status": 1},
                            {"exit_status": False}, {"artifact_digest": "made-up"}, {"command": ""}):
            f = fixture()
            f["evidence"]["tests"].update(replacement)
            self.assertEqual("blocked", self.result(f)["decision"])

    def test_failed_threat_detection_blocks(self):
        f = fixture()
        f["evidence"]["threat_detection"] = "fail"
        self.assertEqual("blocked", self.result(f)["decision"])

    def test_api_error_never_passes(self):
        f = fixture()
        f["evidence"]["api_status"] = "unavailable"
        self.assertEqual("error", self.result(f)["decision"])

    def test_policy_binding_and_malformed_policy_error(self):
        f = fixture()
        f["evidence"]["policy_digest"] = "fake"
        self.assertEqual("error", self.result(f)["decision"])
        self.assertEqual("error", self.result(fixture(), {})["decision"])

    def test_real_evidence_not_supported_by_spike(self):
        f = fixture()
        f["evidence"]["source"] = "github"
        self.assertEqual("error", self.result(f)["decision"])

    def test_high_risk_requires_both_environment_approvals(self):
        for phase in ("before_agent", "before_write"):
            f = fixture(risk="high")
            del f["evidence"]["environment_approvals"][phase]
            self.assertEqual("blocked", self.result(f)["decision"])

    def test_release_environment_must_match(self):
        f = fixture("release")
        f["evidence"]["release_environment"]["name"] = "wrong-environment"
        self.assertEqual("blocked", self.result(f)["decision"])


class ProfileTests(unittest.TestCase):
    def config(self):
        return read_frontmatter(ROOT / "fixtures/gh-aw/draft-intent.md")

    def test_shipped_profile(self):
        self.assertEqual([], inspect(self.config()))

    def test_unsafe_capabilities_rejected(self):
        for key, value in (("imports", ["bypass.md"]), ("jobs", {"bypass": {}}),
                           ("steps", []), ("features", {"experimental": True}),
                           ("permissions", {"contents": "write"}), ("strict", False),
                           ("check-for-updates", False), ("max-ai-credits", -1),
                           ("timeout-minutes", True), ("on", {"pull_request_target": {}}),
                           ("network", {"allowed": ["*"]})):
            with self.subTest(key=key):
                config = self.config()
                config[key] = value
                self.assertTrue(inspect(config))

    def test_approve_merge_and_unstaged_outputs_rejected(self):
        for output in ("merge-pull-request", "approve-workflow-run", "submit-pull-request-review"):
            config = self.config()
            config["safe-outputs"][output] = {}
            self.assertTrue(inspect(config))
        config = self.config()
        config["safe-outputs"]["staged"] = False
        self.assertTrue(inspect(config))

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaises(ValueError):
            yaml.load("strict: true\nstrict: false\n", Loader=Loader)


if __name__ == "__main__":
    unittest.main()
