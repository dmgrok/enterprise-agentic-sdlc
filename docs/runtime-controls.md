# Keep mission, quality and spend within control

Continue only while all three axes are healthy. Collect evidence independently
of the agent, admit each action before execution, and keep the output broker
closed when evidence is missing or a control trips.

## What is implemented

`kit/control.py` persists run state, an immutable policy snapshot, cost
reservations, settlements, and a transactional audit history in SQLite. SQLite
transactions serialize concurrent admissions so two calls cannot reserve the
same money. `kit/control_cli.py` exposes the operator interface.

`kit/supervisor.py` monitors a real local subprocess and terminates its process
group on pause, stop, telemetry expiry or a runtime ceiling. It uses TERM followed
by KILL after a grace period, also cleaning up surviving descendants when the
leader exits. A failed subprocess closes outputs. It does not automatically
restart a process. Processes that deliberately detach into another session
require container/cgroup isolation; this adapter is not an adversarial sandbox.

The GitHub adapter verifies repository, numeric run ID, attempt and head SHA
before cancelling. The external watchdog watches controller state, tries normal
cancellation, then requests force cancellation if the run remains active. A
request accepted by the API is not recorded as confirmed termination. Failure
or unavailable metadata leaves outputs denied and reports an unconfirmed stop.
Cancellation can be retried against the same enrolled target.

## Policy and state

`resources/control-policy.json` is a **synthetic example**, with a $2 total
inference budget, a $1.50 warning, a $1 rolling 60-second rate limit, a 10-minute
runtime ceiling, 15-second telemetry freshness and a 2-attempt repair ceiling.
Amounts use integer micro-USD: 1,000,000 = $1. These numbers are illustrative,
not measured usage or recommended enterprise defaults.

| State | New paid calls | Apply outputs | Next transition |
|---|---|---|---|
| paused | Denied | Denied | Fresh healthy observation plus explicit authorised resume |
| running | Reserved before admission | Allowed only while healthy and all calls settled | Pause or terminal stop on policy trip |
| stopped | Denied | Denied | No resume or automatic retry |

Runs begin paused. Valid telemetry alone never starts or resumes them. Operator
commands require an allowed operator and a reason. Resume needs a newer accepted
observation than the one at pause, all axes healthy, and every in-flight call
reconciled. Runtime, spent money and repair counts are not reset by resuming.
Creating new work is an external approval decision; this prototype does not
enforce organisation-wide budgets across separately enrolled run IDs.

Scope violations and disallowed tool/path requests stop immediately. Wrong
objectives, stalled progress, missing or failed required checks, incomplete cost
coverage and stale telemetry pause. Hitting a repair, runtime or spending ceiling
stops. The admission check can also pause before a proposed call would exceed the
rolling burn limit. A hard budget rejection stops before the provider is called.

The mission collector must evaluate actual actions against the approved intent.
An objective identifier and path allowlist alone cannot establish semantic fit.
The quality collector must execute actual tests, security and artifact checks,
with human/semantic evaluation where required. This controller consumes those
results; it does not invent an LLM quality score or claim to have implemented
those collectors. During testing, results are synthetic.

## Trusted telemetry protocol

Collectors submit HMAC-SHA256 envelopes. The signature covers canonical JSON
with sorted keys, compact separators and nonfinite numbers disallowed. Events
bind `run_id`, the approved `revision`, immutable `policy_digest`, monotonic
`sequence` and `observed_at` (UTC epoch seconds) to:

```json
{
  "mission": {
    "objective_id": "draft-intent",
    "scope_violation": false,
    "progress": "advancing"
  },
  "quality": {
    "checks": {"scope": "pass", "artifact-schema": "pass"},
    "repair_attempts": 0
  },
  "spend": {"accounting": "reservation-ledger", "coverage": "complete"}
}
```

The first five binding fields are required in the event in addition to the
fragment above. `Controller.observe` verifies signature, freshness, sequence,
revision and policy binding; bad or replayed telemetry pauses the run. Repair
counts cannot regress. The exact required check names come from policy.

HMAC authenticates a collector, not the truth of its claims. Deploy the collector
and controller in a separate trust boundary. Do not sign the agent's own report
and treat that as independent evidence.

## Enforce money before the call

The gateway calls `reserve(run_id, call_id, maximum_microusd, tool, path)` before
each paid request. It proceeds only when `allowed` is true. Admission counts
actual cumulative spend plus **all outstanding maximum reservations**. The
gateway must calculate a real worst-case charge from input size, output limits,
model rates and billable extras. A request with unknown maximum cost is denied.

After a provider response, the gateway calls `settle` with the actual charge.
Double settlement and reused call IDs are rejected. Settlements remain possible
after pause or stop so in-flight billing can be reconciled. Unknown calls retain
their reservations; do not release them just because a client timed out. A
zero-charge settlement requires independent proof of no charge. If a provider
exceeds the reservation, the actual overspend is recorded and the run is stopped.
The controller cannot refund it.

The rolling burn limit uses settled charges in the previous 60 seconds plus
outstanding reservations when admitting the next call. Settle-time measurements
are not a continuous provider billing stream. The total ceiling relies on valid
worst-case reservations, not low-latency post-hoc billing data. Actions runner,
storage and other charges need their own reservations/accounting or a separate
budget. The example ledger covers inference only.

gh-aw also supplies native credit, turn and time controls. Its AI-credit figures
are estimated from model pricing and may differ from the invoice. The package
sets agent and threat-detection caps separately because detection has a separate
budget. Its daily guardrail is an additional admission safeguard, not this
controller's transactional ledger. See the official
[cost-management reference](https://github.github.com/gh-aw/reference/cost-management/).

## Keep outputs contained

`permit-output` is a diagnostic decision, not a durable authorisation token.
For enforcement, a trusted writer must call `Controller.apply_output` with an
immutable subject revision and a trusted, bounded I/O callback. This rechecks
health and serializes the write against pause/stop in the controller's transaction.
Never pass agent-authored executable code as that callback. Network timeouts must
be bounded. A request already submitted or a completed write cannot be undone by
a later stop. A retried writer needs provider-side idempotency and reconciliation;
there is no cross-system exactly-once guarantee.

Every actual GitHub write must use that broker or an equivalent independently
enforced gate. Staged safe outputs remain enabled in the shipped gh-aw workflow;
there is no deployed production output broker yet.

## Run the demonstration

From the package root:

```sh
python3 examples/control_demo.py --output reports/control-demo.json
python3 -m unittest discover -v
```

The demo is self-contained and uses a temporary database and synthetic key.
The tests also terminate real child processes for each axis breach, verify
concurrent reservations, reject unauthorised/replayed input, and check that stop
survives a controller restart. No paid model run or GitHub mutation is performed.

## Operator interface

Provision a key file of at least 32 random bytes **outside the agent sandbox**.
Keep it, the policy and database readable/writable only by the control service.
Use the same trusted paths in each command. All CLI commands are intended for
the control-service account; `--actor` is an audit identity asserted by that
trusted interface, not a login mechanism. An external service must authenticate
the operator before invoking it. Direct access to the database bypasses these
controls, and the local same-UID demo provides no such filesystem isolation.

```sh
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 create --policy /CONTROL/policy.json
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 status
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 sign --event /CONTROL/event.json
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 observe --envelope /CONTROL/signed-event.json
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 resume --actor operator --reason 'Fresh evidence reviewed'
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 pause --actor operator --reason 'Investigate drift'
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 stop --actor operator --reason 'Emergency stop'
```

`sign` prints its envelope; save that result in the trusted collector, then
submit it with `observe`. Production collectors use the Python `signed` and
`observe` interfaces directly. The path `/CONTROL` is a deployment placeholder.

The CLI also provides `reserve`, `settle`, `permit-output`, `audit`, and
`supervise --cwd /AGENT/WORKSPACE -- PROGRAM ARG...`. Supervision does not forward
controller tokens or HMAC keys to the child's environment. Do not grant the
child network or filesystem routes that bypass the gateway and output broker.

## GitHub cancellation integration

Run the watchdog in a separate service or separately protected execution context
that outlives the agent job. Enroll the exact GitHub target in the immutable
policy as `github_target`, for example:

```json
{"repository": "OWNER/REPOSITORY", "run_id": 123, "attempt": 1}
```

For a preview, without a token or network call:

```sh
python3 -m kit.control_cli --database /CONTROL/run.sqlite --key-file /CONTROL/collector.key --run WORK-1 cancel-github --repository OWNER/REPOSITORY --github-run-id 123 --attempt 1 --actor operator --reason 'Emergency stop'
```

For an explicitly intended cancellation, supply a dedicated controller GitHub
App token through `KIT_CONTROLLER_GITHUB_TOKEN` and add `--execute`.
`cancel-github --execute` first commits terminal stop and output denial, then
contacts GitHub. `watch-github` takes the same target arguments and `--execute`,
polls controller health and cancels when the run pauses or stops. Without
`--execute`, both commands return a preview. These adapters have mocked tests;
no live GitHub cancellation has been performed.

The token needs Actions write permission on the target, independently of the
agent token. Force cancellation is requested only after normal cancellation
does not complete, as specified by the
[GitHub workflow-runs API](https://docs.github.com/en/rest/actions/workflow-runs#force-cancel-a-workflow-run).
Do not interpret cancellation as suspending a model request for later
continuation. A paused GitHub attempt is cancelled; a resumed workload needs a
separately authorised attempt and rebinding, with cumulative budget retained.
Attempt handoff and organisation-wide retry admission are not implemented yet.

## Remaining integration proof

The runnable local controller and cancellation client do not constitute a live
enterprise deployment. Still required: trusted runtime collectors, complete
gateway routing, a protected output broker, operator authentication, protected
storage and keys, alert delivery, an external watchdog deployment, enrolment
across run attempts, and a synthetic live GitHub proof that all three axes can
stop work and withhold writes. Keep staged mode on until those checks pass.
