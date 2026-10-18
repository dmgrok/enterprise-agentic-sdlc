"""Persistent three-axis controller. Deploy outside the agent's trust boundary."""

import hashlib
import hmac
import json
import sqlite3
import time

from kit.gates import allowed_path, revision


class Denied(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signed(event, key):
    return {"event": event, "signature": hmac.new(key, canonical(event), hashlib.sha256).hexdigest()}


def policy_digest(policy):
    return hashlib.sha256(canonical(policy)).hexdigest()


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def validate_policy(policy):
    if policy.get("schema_version") != "0.1" or not revision(policy.get("revision")):
        raise Denied("Invalid policy version or subject revision")
    for field in ("objective_id",):
        if not isinstance(policy.get(field), str) or not policy[field]:
            raise Denied("Missing " + field)
    for field in ("allowed_paths", "allowed_tools", "mandatory_checks", "operators"):
        if (not isinstance(policy.get(field), list) or not policy[field]
                or not all(isinstance(x, str) and x for x in policy[field])):
            raise Denied("Invalid " + field)
    for field in ("max_runtime_seconds", "telemetry_ttl_seconds", "max_spend_microusd",
                  "warn_spend_microusd", "max_burn_microusd_per_minute"):
        if not integer(policy.get(field), 1):
            raise Denied("Invalid " + field)
    if not integer(policy.get("max_repair_attempts"), 1):
        raise Denied("Invalid repair limit")
    if policy["warn_spend_microusd"] >= policy["max_spend_microusd"]:
        raise Denied("Warning threshold must be below the spending ceiling")


class Controller:
    def __init__(self, database, telemetry_key, clock=time.time):
        if not isinstance(telemetry_key, bytes) or len(telemetry_key) < 32:
            raise Denied("A collector HMAC key of at least 32 bytes is required")
        self.key, self.clock = telemetry_key, clock
        self.db = sqlite3.connect(str(database), timeout=10, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS audit(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            at REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def create(self, run_id, policy):
        validate_policy(policy)
        if not isinstance(run_id, str) or not run_id:
            raise Denied("A run ID is required")
        data = {"run_id": run_id, "policy": policy, "policy_digest": policy_digest(policy),
                "created_at": self.clock(), "state": "paused", "reasons": ["awaiting-telemetry"],
                "sequence": -1, "observed_at": None, "axes": {}, "attempt": 0,
                "resume_after_sequence": -1,
                "spent_microusd": 0, "reservations": {}, "charges": [], "warnings": [],
                "outputs_allowed": False}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("INSERT INTO runs VALUES (?, ?)", (run_id, canonical(data).decode()))
            self._audit(run_id, "created", {"policy_digest": data["policy_digest"]})
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return data

    def _audit(self, run_id, kind, detail):
        self.db.execute("INSERT INTO audit(run_id, at, kind, detail) VALUES (?, ?, ?, ?)",
                        (run_id, self.clock(), kind, canonical(detail).decode()))

    def _change(self, run_id, kind, function):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise Denied("Unknown run")
            data = json.loads(row[0])
            result = function(data)
            self.db.execute("UPDATE runs SET data=? WHERE id=?", (canonical(data).decode(), run_id))
            self._audit(run_id, kind, {"state": data["state"], "reasons": data["reasons"],
                                       "result": result})
            self.db.execute("COMMIT")
            return data, result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _health(self, data):
        p, now = data["policy"], self.clock()
        stops, pauses = [], []
        if now - data["created_at"] >= p["max_runtime_seconds"]:
            stops.append("runtime-ceiling")
        if data["observed_at"] is None or now - data["observed_at"] > p["telemetry_ttl_seconds"]:
            pauses.append("telemetry-stale")
        axes = data["axes"]
        mission, quality = axes.get("mission", {}), axes.get("quality", {})
        if mission.get("scope_violation") is True:
            stops.append("mission-scope")
        if mission.get("objective_id") != p["objective_id"]:
            pauses.append("mission-objective")
        if mission.get("progress") != "advancing":
            pauses.append("mission-progress")
        checks = quality.get("checks", {})
        if not all(checks.get(name) == "pass" for name in p["mandatory_checks"]):
            pauses.append("quality-checks")
        if axes.get("spend") != {"accounting": "reservation-ledger", "coverage": "complete"}:
            pauses.append("spend-coverage")
        repairs = quality.get("repair_attempts")
        if integer(repairs) and repairs >= p["max_repair_attempts"]:
            stops.append("quality-repair-limit")
        if data["spent_microusd"] >= p["max_spend_microusd"]:
            stops.append("spend-ceiling")
        recent = sum(c["amount"] for c in data["charges"] if now - c["at"] < 60)
        if recent >= p["max_burn_microusd_per_minute"]:
            pauses.append("spend-burn-rate")
        data["warnings"] = (["spend-warning"] if data["spent_microusd"] >= p["warn_spend_microusd"] else [])
        if data["state"] != "stopped":
            if stops:
                data["state"], data["reasons"] = "stopped", stops + pauses
            elif pauses and data["state"] == "running":
                data["state"], data["reasons"] = "paused", pauses
                data["resume_after_sequence"] = data["sequence"]
        pending = any(r["state"] == "reserved" for r in data["reservations"].values())
        data["outputs_allowed"] = data["state"] == "running" and not stops and not pauses and not pending
        return stops + pauses

    def status(self, run_id):
        return self._change(run_id, "health", lambda d: self._health(d))[0]

    def observe(self, run_id, envelope):
        def apply(data):
            try:
                event, signature = envelope["event"], envelope["signature"]
                expected = signed(event, self.key)["signature"]
                if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
                    raise Denied("telemetry-signature")
                if (event["run_id"] != run_id or event["revision"] != data["policy"]["revision"]
                        or event["policy_digest"] != data["policy_digest"]):
                    raise Denied("telemetry-binding")
                if not integer(event["sequence"]) or event["sequence"] <= data["sequence"]:
                    raise Denied("telemetry-replay")
                observed = event["observed_at"]
                if (type(observed) not in (int, float) or observed > self.clock()
                        or self.clock() - observed > data["policy"]["telemetry_ttl_seconds"]
                        or (data["observed_at"] is not None and observed < data["observed_at"])):
                    raise Denied("telemetry-time")
                mission, quality = event["mission"], event["quality"]
                if (not isinstance(mission, dict) or type(mission.get("scope_violation")) is not bool
                        or mission.get("progress") not in ("advancing", "stalled")
                        or not isinstance(quality, dict) or not isinstance(quality.get("checks"), dict)
                        or not integer(quality.get("repair_attempts"))):
                    raise Denied("telemetry-schema")
                previous = data["axes"].get("quality", {}).get("repair_attempts", 0)
                if quality["repair_attempts"] < previous:
                    raise Denied("repair-counter-regression")
                data.update(sequence=event["sequence"], observed_at=observed,
                            axes={"mission": mission, "quality": quality, "spend": event.get("spend", {})})
                return {"accepted": True, "health": self._health(data)}
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                if data["state"] != "stopped":
                    data["state"], data["reasons"] = "paused", ["invalid-telemetry"]
                    data["resume_after_sequence"] = data["sequence"]
                data["outputs_allowed"] = False
                return {"accepted": False, "reason": str(exc)}
        return self._change(run_id, "telemetry", apply)

    def command(self, run_id, action, actor, reason):
        if action not in ("pause", "stop", "resume") or not isinstance(reason, str) or not reason.strip():
            raise Denied("An explicit action and reason are required")
        def apply(data):
            if actor not in data["policy"]["operators"]:
                raise Denied("Operator is not authorised")
            health = self._health(data)
            if action == "resume":
                if data["state"] == "stopped":
                    raise Denied("Stopped runs are terminal; create separately authorised work")
                if data["state"] != "paused" or health:
                    raise Denied("Resume requires a paused run with all three axes healthy")
                if data["sequence"] <= data["resume_after_sequence"]:
                    raise Denied("Resume requires a new accepted telemetry observation")
                if any(r["state"] == "reserved" for r in data["reservations"].values()):
                    raise Denied("Reconcile in-flight reservations before resuming")
                data["state"], data["reasons"] = "running", []
                data["attempt"] += 1
            elif data["state"] != "stopped":
                data["state"], data["reasons"] = ("stopped" if action == "stop" else "paused"), [reason]
                data["resume_after_sequence"] = data["sequence"]
            data["outputs_allowed"] = data["state"] == "running"
            return {"actor": actor, "action": action, "reason": reason}
        return self._change(run_id, "operator-command", apply)[0]

    def reserve(self, run_id, call_id, maximum_microusd, tool, path=None):
        if not isinstance(call_id, str) or not call_id or not integer(maximum_microusd, 1):
            raise Denied("A unique call ID and positive integer worst-case charge are required")
        def apply(data):
            self._health(data)
            if call_id in data["reservations"]:
                return {"allowed": False, "reason": "duplicate-call-id"}
            if data["state"] != "running":
                return {"allowed": False, "reason": "run-not-running"}
            if (tool not in data["policy"]["allowed_tools"] or (tool == "draft" and path is None)
                    or (path is not None and not allowed_path(path, data["policy"]["allowed_paths"]))):
                data.update(state="stopped", reasons=["forbidden-action"], outputs_allowed=False)
                return {"allowed": False, "reason": "forbidden-action"}
            held = sum(r["maximum"] for r in data["reservations"].values() if r["state"] == "reserved")
            if data["spent_microusd"] + held + maximum_microusd > data["policy"]["max_spend_microusd"]:
                data.update(state="stopped", reasons=["reservation-exceeds-budget"], outputs_allowed=False)
                return {"allowed": False, "reason": "reservation-exceeds-budget"}
            recent = sum(c["amount"] for c in data["charges"] if self.clock() - c["at"] < 60)
            if recent + held + maximum_microusd > data["policy"]["max_burn_microusd_per_minute"]:
                data.update(state="paused", reasons=["projected-burn-rate"], outputs_allowed=False)
                data["resume_after_sequence"] = data["sequence"]
                return {"allowed": False, "reason": "projected-burn-rate"}
            data["reservations"][call_id] = {"maximum": maximum_microusd, "state": "reserved"}
            data["outputs_allowed"] = False
            return {"allowed": True, "call_id": call_id}
        return self._change(run_id, "reserve", apply)

    def settle(self, run_id, call_id, actual_microusd):
        if not integer(actual_microusd):
            raise Denied("Charge must be a nonnegative integer in micro-USD")
        def apply(data):
            reservation = data["reservations"].get(call_id)
            if not reservation or reservation["state"] != "reserved":
                raise Denied("Missing or already settled reservation")
            reservation.update(state="settled", actual=actual_microusd)
            data["spent_microusd"] += actual_microusd
            data["charges"].append({"at": self.clock(), "amount": actual_microusd})
            if actual_microusd > reservation["maximum"]:
                data.update(state="stopped", reasons=["provider-exceeded-reservation"], outputs_allowed=False)
            self._health(data)
            return {"charged_microusd": actual_microusd}
        return self._change(run_id, "settle", apply)[0]

    def permit_output(self, run_id):
        data = self.status(run_id)
        return {"allowed": data["outputs_allowed"], "run_id": run_id,
                "revision": data["policy"]["revision"], "policy_digest": data["policy_digest"],
                "state": data["state"], "reasons": data["reasons"]}

    def audit(self, run_id):
        return [{"sequence": seq, "at": at, "kind": kind, "detail": json.loads(detail)}
                for seq, at, kind, detail in self.db.execute(
                    "SELECT sequence,at,kind,detail FROM audit WHERE run_id=? ORDER BY sequence", (run_id,))]

    def apply_output(self, run_id, revision_sha, operation):
        """Trusted broker callback, serialized against pause/stop. Never pass agent code."""
        def apply(data):
            self._health(data)
            if not data["outputs_allowed"] or revision_sha != data["policy"]["revision"]:
                return {"applied": False, "reason": "output-denied"}
            # The writer must bound its I/O timeout; cancellation cannot undo completed I/O.
            operation()
            return {"applied": True}
        return self._change(run_id, "apply-output", apply)
