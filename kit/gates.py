"""Offline decision evaluator. Inputs must come from a trusted adapter in production."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


FIELDS = {
    "intent": ("problem", "users", "outcome", "constraints", "exclusions"),
    "specification": ("acceptance_criteria", "data_boundaries", "risks", "design", "alternatives"),
    "plan": ("allowed_paths", "dependencies", "checks", "rollout", "recovery"),
    "pull_request": ("plan_revision", "changed_paths", "tests", "residual_risks"),
    "release": ("approved_revision", "deployment_checks", "environment", "rollback"),
    "incident": ("signal", "impact", "triage", "response", "regression_requirement"),
}
PREVIOUS = dict(zip(FIELDS, (None, "intent", "specification", "plan", "pull_request", "release")))
ROLES = {
    "intent": ("product",), "specification": ("product", "technical"),
    "plan": ("engineer",), "pull_request": ("codeowner",),
    "release": ("release",), "incident": ("incident",),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def revision(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def safe_path(value):
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not value.startswith("/") and "\x00" not in value
            and all(part not in ("", ".", "..") for part in value.split("/")))


def allowed_path(path, scopes):
    # Literal files or directory/** only; avoid platform-dependent glob semantics.
    return safe_path(path) and any(
        (scope.endswith("/**") and safe_path(scope[:-3]) and path.startswith(scope[:-2]))
        or (safe_path(scope) and path == scope)
        for scope in scopes if isinstance(scope, str)
    )


def evaluate(policy, subject, evidence):
    checks = []
    report = {
        "schema_version": "0.1", "mode": "offline-simulation",
        "work_item_id": subject.get("work_item_id"), "gate": subject.get("gate"),
        "subject_revision": evidence.get("subject_revision"),
        "policy_revision": evidence.get("policy_revision"),
        "policy_digest": digest(policy), "risk_tier": subject.get("risk_tier"),
        "checks": checks, "approval_refs": [], "agent_run_refs": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    def check(name, passed, correction, status="fail"):
        checks.append({"id": name, "status": "pass" if passed else status,
                       "evidence_ref": "synthetic-fixture:" + name,
                       "corrective_action": None if passed else correction})

    gate, risk = subject.get("gate"), subject.get("risk_tier")
    try:
        if policy.get("schema_version") != "0.1":
            raise ValueError("Unsupported policy schema")
        for tier in ("low", "standard", "high"):
            minimum = policy["risk_tiers"][tier]["minimum_reviewers"]
            if type(minimum) is not int or minimum < (2 if tier == "high" else 1):
                raise ValueError("Reviewer minimum is invalid")
        for role in set(r for roles in ROLES.values() for r in roles):
            users = policy["roles"][role]
            if not isinstance(users, list) or not users or not all(isinstance(x, str) and x for x in users):
                raise ValueError("Role membership is invalid")
        if not isinstance(policy["automation_identities"], list):
            raise ValueError("Automation identity list is required")
        check("policy", True, "")
    except (KeyError, TypeError, ValueError) as exc:
        check("policy", False, "Repair trusted base policy: " + str(exc), "error")
        report["decision"] = "error"
        return report

    check("gate", gate in FIELDS, "Choose a supported gate")
    check("risk", risk in ("low", "standard", "high"), "Classify risk using trusted policy")
    check("source", evidence.get("source") == "synthetic-fixture",
          "This spike accepts synthetic fixtures only; implement an authenticated GitHub adapter", "error")
    check("revisions", revision(evidence.get("subject_revision")) and revision(evidence.get("policy_revision")),
          "Supply full subject and trusted base policy commit SHAs", "error")
    check("api", evidence.get("api_status") == "ok", "Retrieve complete GitHub metadata", "error")
    check("policy_binding", evidence.get("policy_digest") == digest(policy),
          "Load policy from the trusted base revision and verify its digest", "error")
    check("risk_binding", evidence.get("classified_risk") == risk,
          "Use the risk classification from trusted policy evaluation")
    if gate not in FIELDS or risk not in ("low", "standard", "high"):
        report["decision"] = "blocked"
        return report

    check("artifact", all(subject.get(field) for field in
          ("work_item_id", "version", "owner", "decision", "evidence", *FIELDS[gate])),
          "Fill required artifact fields for " + gate)
    previous = PREVIOUS[gate]
    if previous:
        predecessor = evidence.get("predecessor", {})
        check("predecessor", predecessor.get("gate") == previous
              and predecessor.get("work_item_id") == subject.get("work_item_id")
              and predecessor.get("decision") == "pass"
              and predecessor.get("merged_to_default") is True
              and revision(predecessor.get("revision"))
              and subject.get("predecessor_revision") == predecessor.get("revision")
              and predecessor.get("content_digest") == digest(predecessor.get("artifact", {})),
              "Provide the passed, merged predecessor and its exact content digest")

    approvals = evidence.get("reviews", [])
    check("reviews_available", isinstance(approvals, list), "Retrieve review records", "error")
    latest = {}
    for review in approvals if isinstance(approvals, list) else []:
        if not isinstance(review, dict):
            continue
        actor = review.get("actor")
        # Comments do not replace a previous decisive review. Numeric IDs are ordered.
        if (isinstance(actor, str) and type(review.get("id")) is int
                and review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
                and review["id"] > latest.get(actor, {}).get("id", -1)):
            latest[actor] = review
    humans = {
        actor: review for actor, review in latest.items()
        if review.get("state") == "APPROVED" and review.get("actor_type") == "User"
        and not actor.lower().endswith("[bot]")
        and actor.lower() not in {x.lower() for x in policy["automation_identities"]}
        and actor != evidence.get("author") and review.get("revision") == evidence.get("subject_revision")
        and isinstance(review.get("url"), str) and review["url"].startswith("https://github.com/")
    }
    report["approval_refs"] = [r["url"] for r in humans.values()]
    for role in ROLES[gate]:
        check("role_" + role, bool(set(humans) & set(policy["roles"][role])),
              "Obtain current-revision approval from role " + role)
    check("review_count", len(humans) >= policy["risk_tiers"][risk]["minimum_reviewers"],
          "Obtain enough distinct human approvals of this revision")
    if gate == "specification":
        product = set(humans) & set(policy["roles"]["product"])
        technical = set(humans) & set(policy["roles"]["technical"])
        check("two_roles", any(a != b for a in product for b in technical),
              "Obtain approvals from two distinct product and technical owners")
    if risk == "high":
        check("separation", bool(set(humans) - {evidence.get("invoking_actor")}),
              "An independent reviewer must approve high-risk work")
        for phase in ("before_agent", "before_write"):
            approval = evidence.get("environment_approvals", {}).get(phase, {})
            check(phase, approval.get("approved") is True
                  and approval.get("revision") == evidence.get("subject_revision")
                  and approval.get("actor") in humans,
                  "Record trusted Environment approval for " + phase)

    if gate == "pull_request":
        plan = evidence.get("predecessor", {})
        scopes = plan.get("artifact", {}).get("allowed_paths", [])
        paths = subject.get("changed_paths", [])
        check("plan_revision", subject.get("plan_revision") == plan.get("revision"),
              "Reference the exact merged plan revision")
        check("scope", isinstance(paths, list) and bool(paths) and isinstance(scopes, list)
              and bool(scopes) and all(allowed_path(path, scopes) for path in paths),
              "Keep changes within the merged plan; scope changes need a newly approved plan")
        tests = evidence.get("tests", {})
        check("tests", tests.get("revision") == evidence.get("subject_revision")
              and type(tests.get("exit_status")) is int and tests["exit_status"] == 0
              and isinstance(tests.get("command"), str) and bool(tests["command"])
              and isinstance(tests.get("artifact_digest"), str)
              and re.fullmatch(r"[0-9a-f]{64}", tests["artifact_digest"]) is not None,
              "Run trusted checks on the current head and record command, exit status and SHA-256")
        check("threat_detection", evidence.get("threat_detection") == "pass",
              "Obtain a successful threat-detection result")
    if gate == "release":
        environment = evidence.get("release_environment", {})
        check("release_environment", environment.get("approved") is True
              and environment.get("actor") in humans
              and environment.get("revision") == evidence.get("subject_revision")
              and subject.get("approved_revision") == evidence.get("subject_revision")
              and environment.get("name") == subject.get("environment"),
              "Obtain release Environment approval of the release revision")
    report["decision"] = ("error" if any(c["status"] == "error" for c in checks)
                          else "blocked" if any(c["status"] == "fail" for c in checks) else "pass")
    return report


def main():
    parser = argparse.ArgumentParser(description="Offline gate simulation; never a production approval source")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args()
    try:
        fixture = json.loads(args.fixture.read_text())
        result = evaluate(json.loads(args.policy.read_text()), fixture["subject"], fixture["evidence"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result = {"schema_version": "0.1", "mode": "offline-simulation", "decision": "error",
                  "checks": [{"id": "input", "status": "error", "corrective_action": str(exc)}]}
    print(json.dumps(result, indent=2))
    return {"pass": 0, "blocked": 1, "error": 2}[result["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
