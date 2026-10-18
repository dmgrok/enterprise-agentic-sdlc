import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

from kit.control import Controller, Denied, policy_digest, signed
from kit.supervisor import GitHubCancellation, supervise, watch_github

ROOT = Path(__file__).resolve().parents[1]
KEY = b"synthetic-test-key-never-use-in-production"
POLICY = json.loads((ROOT / "resources/control-policy.json").read_text())


def event(policy, now, sequence=0, run_id="run-1"):
    return {"run_id": run_id, "revision": policy["revision"], "policy_digest": policy_digest(policy),
            "sequence": sequence, "observed_at": now,
            "mission": {"objective_id": policy["objective_id"], "scope_violation": False, "progress": "advancing"},
            "quality": {"checks": {name: "pass" for name in policy["mandatory_checks"]}, "repair_attempts": 0},
            "spend": {"accounting": "reservation-ledger", "coverage": "complete"}}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "controller.sqlite"
        self.now = 1000
        self.policy = copy.deepcopy(POLICY)
        self.controller = Controller(self.database, KEY, lambda: self.now)
        self.controller.create("run-1", self.policy)

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def healthy(self, sequence=0):
        return self.controller.observe("run-1", signed(event(self.policy, self.now, sequence), KEY))

    def start(self):
        self.healthy(self.controller.status("run-1")["sequence"] + 1)
        return self.controller.command("run-1", "resume", "operator", "Reviewed initial evidence")

    def reserve(self, name="call-1", amount=100000):
        return self.controller.reserve("run-1", name, amount, "draft", "work/demo/intent.json")

    def test_no_start_without_all_three_axes(self):
        with self.assertRaises(Denied):
            self.controller.command("run-1", "resume", "operator", "Try without telemetry")
        self.assertFalse(self.controller.permit_output("run-1")["allowed"])

    def test_healthy_does_not_resume_automatically(self):
        self.healthy()
        self.assertEqual("paused", self.controller.status("run-1")["state"])
        self.assertEqual("running", self.start()["state"])

    def test_scope_stops_and_quality_pauses(self):
        for axis in ("scope", "quality", "progress", "spend"):
            with self.subTest(axis=axis):
                name = "run-" + axis
                self.controller.create(name, self.policy)
                good = event(self.policy, self.now, run_id=name)
                self.controller.observe(name, signed(good, KEY))
                self.controller.command(name, "resume", "operator", "Start")
                bad = event(self.policy, self.now, sequence=1, run_id=name)
                if axis == "scope":
                    bad["mission"]["scope_violation"] = True
                elif axis == "quality":
                    bad["quality"]["checks"]["scope"] = "fail"
                elif axis == "progress":
                    bad["mission"]["progress"] = "stalled"
                else:
                    bad["spend"]["coverage"] = "unknown"
                self.controller.observe(name, signed(bad, KEY))
                self.assertEqual("stopped" if axis == "scope" else "paused", self.controller.status(name)["state"])
                self.assertFalse(self.controller.permit_output(name)["allowed"])

    def test_signed_replay_and_bad_signature_pause(self):
        self.start()
        envelope = signed(event(self.policy, self.now), KEY)
        _, accepted = self.controller.observe("run-1", envelope)
        self.assertFalse(accepted["accepted"])
        self.assertEqual("paused", self.controller.status("run-1")["state"])
        self.healthy(1)
        self.controller.command("run-1", "resume", "operator", "Revalidated")
        envelope["signature"] = "forged"
        self.assertFalse(self.controller.observe("run-1", envelope)[1]["accepted"])

    def test_wrong_run_revision_policy_and_time_rejected(self):
        for change in ({"run_id": "other"}, {"revision": "b" * 40},
                       {"policy_digest": "fake"}, {"observed_at": 1001}, {"observed_at": 0}):
            snapshot = event(self.policy, self.now)
            snapshot.update(change)
            self.assertFalse(self.controller.observe("run-1", signed(snapshot, KEY))[1]["accepted"])

    def test_missing_telemetry_and_runtime_ceiling(self):
        self.start()
        self.now += self.policy["telemetry_ttl_seconds"] + 1
        self.assertEqual("paused", self.controller.status("run-1")["state"])
        self.now += self.policy["max_runtime_seconds"]
        self.assertEqual("stopped", self.controller.status("run-1")["state"])

    def test_repair_limit_stops_and_cannot_reset(self):
        self.start()
        bad = event(self.policy, self.now, 1)
        bad["quality"]["repair_attempts"] = self.policy["max_repair_attempts"]
        self.controller.observe("run-1", signed(bad, KEY))
        self.assertEqual("stopped", self.controller.status("run-1")["state"])
        self.assertFalse(self.healthy(2)[1]["accepted"])

    def test_budget_reservations_include_concurrent_calls(self):
        self.start()
        # Raise only burn limit in a separately enrolled policy to test total-budget denial.
        other = dict(self.policy, max_burn_microusd_per_minute=10000000)
        self.controller.create("budget", other)
        self.controller.observe("budget", signed(event(other, self.now, run_id="budget"), KEY))
        self.controller.command("budget", "resume", "operator", "Start")
        self.assertTrue(self.controller.reserve("budget", "one", 1500000, "read")[1]["allowed"])
        self.assertFalse(self.controller.reserve("budget", "two", 600000, "read")[1]["allowed"])
        self.assertFalse(self.controller.permit_output("budget")["allowed"])

    def test_burn_rate_reservation_pauses_before_call(self):
        self.start()
        self.assertTrue(self.reserve("one", 600000)[1]["allowed"])
        self.assertFalse(self.reserve("two", 600000)[1]["allowed"])
        self.assertEqual("paused", self.controller.status("run-1")["state"])

    def test_warning_then_exact_budget_ceiling(self):
        policy = dict(self.policy, max_burn_microusd_per_minute=10000000)
        self.controller.create("warning", policy)
        self.controller.observe("warning", signed(event(policy, self.now, run_id="warning"), KEY))
        self.controller.command("warning", "resume", "operator", "Start")
        self.controller.reserve("warning", "one", 1500000, "read")
        result = self.controller.settle("warning", "one", 1500000)
        self.assertEqual(["spend-warning"], result["warnings"])
        self.assertEqual("running", result["state"])
        self.controller.reserve("warning", "two", 500000, "read")
        result = self.controller.settle("warning", "two", 500000)
        self.assertEqual("stopped", result["state"])
        self.assertFalse(self.controller.permit_output("warning")["allowed"])

    def test_settlement_idempotency_and_overshoot(self):
        self.start()
        self.reserve()
        self.controller.settle("run-1", "call-1", 100001)
        self.assertEqual("stopped", self.controller.status("run-1")["state"])
        with self.assertRaises(Denied):
            self.controller.settle("run-1", "call-1", 0)
        self.assertEqual(100001, self.controller.status("run-1")["spent_microusd"])

    def test_pause_preserves_cost_and_inflight_reservations(self):
        self.start()
        self.reserve()
        self.controller.command("run-1", "pause", "operator", "Investigate")
        self.assertFalse(self.reserve("two")[1]["allowed"])
        with self.assertRaises(Denied):
            self.controller.command("run-1", "resume", "operator", "Still in flight")
        self.controller.settle("run-1", "call-1", 90000)
        self.healthy(1)
        self.controller.command("run-1", "resume", "operator", "Reconciled")
        self.assertEqual(90000, self.controller.status("run-1")["spent_microusd"])

    def test_forbidden_tool_or_path_stops(self):
        for name, tool, path in (("badtool", "deploy", None), ("badpath", "draft", ".github/ci.yml"),
                                 ("missingpath", "draft", None)):
            self.controller.create(name, self.policy)
            self.controller.observe(name, signed(event(self.policy, self.now, run_id=name), KEY))
            self.controller.command(name, "resume", "operator", "Start")
            data, result = self.controller.reserve(name, "call", 1, tool, path)
            self.assertFalse(result["allowed"])
            self.assertEqual("stopped", data["state"])

    def test_operator_authority_and_terminal_stop(self):
        self.start()
        with self.assertRaises(Denied):
            self.controller.command("run-1", "stop", "agent", "Override")
        self.controller.command("run-1", "stop", "operator", "Emergency")
        self.healthy(1)
        with self.assertRaises(Denied):
            self.controller.command("run-1", "resume", "operator", "Restart")

    def test_policy_immutable_and_state_survives_restart(self):
        self.start()
        with self.assertRaises(sqlite3.IntegrityError):
            self.controller.create("run-1", dict(self.policy, max_spend_microusd=999999999))
        self.controller.command("run-1", "stop", "operator", "Persist stop")
        with ControllerContext(self.database, lambda: self.now) as other:
            self.assertEqual("stopped", other.status("run-1")["state"])
            self.assertTrue(any(e["kind"] == "operator-command" for e in other.audit("run-1")))

    def test_output_broker_rechecks_state_and_revision(self):
        writes = []
        self.start()
        self.assertTrue(self.controller.apply_output("run-1", self.policy["revision"], lambda: writes.append("ok"))[1]["applied"])
        self.assertFalse(self.controller.apply_output("run-1", "b" * 40, lambda: writes.append("bad"))[1]["applied"])
        self.controller.command("run-1", "pause", "operator", "Hold")
        self.assertFalse(self.controller.apply_output("run-1", self.policy["revision"], lambda: writes.append("bad"))[1]["applied"])
        self.assertEqual(["ok"], writes)

    def test_outputs_wait_for_inflight_cost_settlement(self):
        self.start()
        self.reserve()
        self.assertFalse(self.controller.permit_output("run-1")["allowed"])
        self.controller.settle("run-1", "call-1", 50000)
        self.assertTrue(self.controller.permit_output("run-1")["allowed"])

    def test_resume_requires_new_observation_after_manual_pause(self):
        self.start()
        self.controller.command("run-1", "pause", "operator", "Review intent")
        with self.assertRaises(Denied):
            self.controller.command("run-1", "resume", "operator", "No new evidence")
        self.healthy(1)
        self.assertEqual("running", self.controller.command("run-1", "resume", "operator", "Fresh evidence reviewed")["state"])

    def test_actual_process_is_terminated_on_stop(self):
        # Real process, real cross-connection stop; no model or network.
        live = dict(self.policy, max_runtime_seconds=30, telemetry_ttl_seconds=30)
        self.controller.create("local-process", live)
        self.controller.observe("local-process", signed(event(live, self.now, run_id="local-process"), KEY))
        self.controller.command("local-process", "resume", "operator", "Start local proof")
        marker = Path(self.temp.name) / "started"
        errors = []
        def operator():
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                with ControllerContext(self.database, lambda: self.now) as other:
                    other.command("local-process", "stop", "operator", "Integration stop")
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=operator)
        worker.start()
        command = [sys.executable, "-c", "from pathlib import Path; import time; Path('started').touch(); time.sleep(20)"]
        result = supervise(self.controller, "local-process", command, self.temp.name, 0.02, 0.05)
        worker.join(timeout=5)
        self.assertFalse(errors)
        self.assertTrue(marker.exists())
        self.assertTrue(result["interrupted"])
        self.assertLess(result["exit_code"], 0)
        self.assertFalse(result["outputs_allowed"])

    def test_concurrent_reservations_cannot_oversubscribe_budget(self):
        policy = dict(self.policy, max_spend_microusd=1000000,
                      warn_spend_microusd=900000, max_burn_microusd_per_minute=10000000)
        self.controller.create("concurrent", policy)
        self.controller.observe("concurrent", signed(event(policy, self.now, run_id="concurrent"), KEY))
        self.controller.command("concurrent", "resume", "operator", "Start")
        barrier = threading.Barrier(2)
        allowed, errors = [], []
        def reserve(name):
            try:
                with ControllerContext(self.database, lambda: self.now) as other:
                    barrier.wait(timeout=5)
                    allowed.append(other.reserve("concurrent", name, 600000, "read")[1]["allowed"])
            except BaseException as exc:
                errors.append(exc)
        workers = [threading.Thread(target=reserve, args=(str(i),)) for i in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        self.assertFalse(errors)
        self.assertEqual([False, True], sorted(allowed))

    def test_actual_process_stops_on_each_axis_breach(self):
        for axis in ("mission", "quality", "spend"):
            with self.subTest(axis=axis):
                name = "process-" + axis
                self.controller.create(name, self.policy)
                self.controller.observe(name, signed(event(self.policy, self.now, run_id=name), KEY))
                self.controller.command(name, "resume", "operator", "Start")
                marker = Path(self.temp.name) / name
                errors = []
                def trigger():
                    try:
                        deadline = time.monotonic() + 5
                        while not marker.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        with ControllerContext(self.database, lambda: self.now) as other:
                            if axis == "spend":
                                other.reserve(name, "too-much", self.policy["max_spend_microusd"] + 1, "read")
                            else:
                                bad = event(self.policy, self.now, 1, name)
                                if axis == "mission":
                                    bad["mission"]["scope_violation"] = True
                                else:
                                    bad["quality"]["checks"]["scope"] = "fail"
                                other.observe(name, signed(bad, KEY))
                    except BaseException as exc:
                        errors.append(exc)
                worker = threading.Thread(target=trigger)
                worker.start()
                code = "from pathlib import Path; import time; Path(" + repr(name) + ").touch(); time.sleep(20)"
                result = supervise(self.controller, name, [sys.executable, "-c", code], self.temp.name, 0.02, 0.05)
                worker.join(timeout=5)
                self.assertFalse(errors)
                self.assertTrue(marker.exists())
                self.assertTrue(result["interrupted"])
                self.assertFalse(result["outputs_allowed"])

    def test_failed_process_blocks_outputs(self):
        self.start()
        result = supervise(self.controller, "run-1", [sys.executable, "-c", "raise SystemExit(3)"], self.temp.name, 0.01, 0.01)
        self.assertEqual(3, result["exit_code"])
        self.assertFalse(self.controller.permit_output("run-1")["allowed"])

    def test_supervisor_rejects_controller_secrets_in_child_environment(self):
        self.start()
        with self.assertRaises(Denied):
            supervise(self.controller, 'run-1', [sys.executable, '-c', 'pass'], self.temp.name,
                      environment={'KIT_UPSTREAM_API_KEY': 'synthetic-key'})

    def test_writer_rechecks_output_quality_and_digest_inside_transaction(self):
        policy = copy.deepcopy(self.policy)
        policy['output_mandatory_checks'] = ['security']
        self.controller.create('writer-run', policy)
        observed = event(policy, self.now, run_id='writer-run')
        observed['quality']['artifact_digest'] = 'a' * 64
        self.controller.observe('writer-run', signed(observed, KEY))
        self.controller.command('writer-run', 'resume', 'operator', 'Verify writer policy')
        writes = []
        result = self.controller.apply_output('writer-run', policy['revision'], lambda: writes.append('bad'),
                                               {'artifact_digest': 'a' * 64})[1]
        self.assertEqual('output-quality-checks-required', result['reason'])
        observed['sequence'] = 1
        observed['quality']['checks']['security'] = 'pass'
        observed['quality']['artifact_digest'] = 'b' * 64
        self.controller.observe('writer-run', signed(observed, KEY))
        result = self.controller.apply_output('writer-run', policy['revision'], lambda: writes.append('stale'),
                                               {'artifact_digest': 'a' * 64})[1]
        self.assertEqual('artifact-evidence-digest-mismatch', result['reason'])
        result = self.controller.apply_output('writer-run', policy['revision'], lambda: writes.append('accepted'),
                                               {'artifact_digest': 'b' * 64})[1]
        self.assertTrue(result['applied'])
        self.assertEqual(['accepted'], writes)


class ControllerContext:
    def __init__(self, database, clock):
        self.controller = Controller(database, KEY, clock)
    def __enter__(self):
        return self.controller
    def __exit__(self, *args):
        self.controller.close()


class CancellationTests(unittest.TestCase):
    def adapter(self, transport=None):
        return GitHubCancellation("example/fixture", 123, "a" * 40, 1, transport=transport)

    def run_record(self, **changes):
        return {"id": 123, "head_sha": "a" * 40, "run_attempt": 1,
                "repository": {"full_name": "example/fixture"}, "status": "in_progress", **changes}

    def test_default_dry_run_never_calls_network(self):
        def forbidden(*args):
            raise AssertionError("Network must not be called")
        self.assertEqual("dry-run", self.adapter(forbidden).cancel()["mode"])

    def test_binding_mismatch_never_posts_cancel(self):
        calls = []
        def transport(method, url):
            calls.append(method)
            return 200, self.run_record(head_sha="b" * 40)
        with self.assertRaises(Denied):
            self.adapter(transport).cancel(execute=True, grace_seconds=0)
        self.assertEqual(["GET"], calls)

    def test_force_only_after_normal_cancel_and_not_false_success(self):
        calls = []
        def transport(method, url):
            calls.append((method, url.rsplit("/", 1)[-1]))
            return (200, self.run_record()) if method == "GET" else (202, {})
        result = self.adapter(transport).cancel(execute=True, grace_seconds=0)
        self.assertFalse(result["termination_confirmed"])
        self.assertTrue(result["force_requested"])
        self.assertEqual(["cancel", "force-cancel"], [u for m, u in calls if m == "POST"])

    def test_confirmed_cancel_and_already_completed(self):
        for conclusion in ("cancelled", "success"):
            adapter = self.adapter(lambda method, url: (200, self.run_record(status="completed", conclusion=conclusion)))
            self.assertEqual(conclusion == "cancelled", adapter.cancel(execute=True)["termination_confirmed"])

    def test_watchdog_cancels_when_quality_pauses(self):
        class Control:
            def status(self, run_id):
                return {"state": "paused"}
            def _change(self, run_id, kind, function):
                return function({})
        calls = []
        class Adapter:
            def cancel(self, execute=False):
                calls.append(execute)
                return {"termination_confirmed": True}
        result = watch_github(Control(), "run-1", Adapter(), execute=True)
        self.assertEqual([True], calls)
        self.assertEqual("paused", result["control_state"])

    def test_watchdog_completion_blocks_until_final_gate(self):
        class Control:
            data = {"state": "running", "sequence": 4}
            def status(self, run_id):
                return dict(self.data)
            def _change(self, run_id, kind, function):
                return function(self.data)
        control = Control()
        class Adapter:
            def status(self):
                return {"status": "completed", "conclusion": "success"}
        result = watch_github(control, "run-1", Adapter(), execute=True)
        self.assertTrue(result["completed"])
        self.assertFalse(result["outputs_allowed"])
        self.assertEqual("paused", control.data["state"])


if __name__ == "__main__":
    unittest.main()
