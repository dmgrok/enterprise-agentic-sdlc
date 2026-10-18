# Enterprise Agentic SDLC Kit

Agents propose delivery artifacts. People approve them. Deterministic checks
connect each decision to a revision and its evidence.

This is a **local contract and runtime-control prototype**, built on
[GitHub Agentic Workflows](https://github.com/github/gh-aw), not an enterprise
release. No paid model runs, live GitHub cancellation or repository-protection
configuration have been performed. The package contains synthetic examples only.

The six lifecycle gates are intent, specification, plan, pull request, release,
and incident feedback. `kit/gates.py` evaluates their proposed contract offline.
The first packaged agent workflow drafts intent artifacts in **staged mode**.
Its output cannot grant gate approval. The other five agent workflows and the
trusted GitHub evidence adapter are not implemented.

## Run the local proof

From this directory, with Python 3.10 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python -m kit.profile .
.venv/bin/python -m kit.gates --policy resources/policy.json --fixture fixtures/allowed-implementation.json
.venv/bin/python -m kit.gates --policy resources/policy.json --fixture fixtures/blocked-unapproved-plan.json
```

The allowed fixture exits 0 with `decision: pass`. The deliberately unapproved
plan exits 1 with `decision: blocked` and a corrective action. Input/API errors
exit 2. Every report declares `mode: offline-simulation` and uses synthetic
evidence references. A fixture report must never be a required production check.
`approved: true` in an artifact has no approval authority.

`resources/policy.json` contains illustrative identities, not real repository
owners. The current artifact representation is JSON so the spike can evaluate
it without parsing prose. It is a candidate machine contract; the reviewed
spec's Markdown artifacts will need a mapping before the contract is frozen.

## Reproduce compilation

The compiler is pinned to **v0.92.0**. The gh-aw Actions dependency is pinned to
commit `458b269006dcf88e3b5496b6fbecabe4b9a0f954`, resolved from that release.
See `runtime.json`. Download the binary for your OS from the official
[release](https://github.com/github/gh-aw/releases/tag/v0.92.0), check its
published checksum, and run:

```sh
python3 scripts/compile.py --compiler /absolute/path/to/gh-aw
python3 scripts/compile.py --compiler /absolute/path/to/gh-aw --check
```

Compilation uses a temporary consumer repository and does not install an
extension or add workflows to the host working tree. The committed lock is a
reference build. `aw.yml` lists the source workflow; consumers compile their
installed copy. Compilation does not prove sandbox, billing, model execution,
threat detection or repository-protection behavior on GitHub.

## Package adoption, after installation verification

The `aw.yml` manifest follows the official
[package format](https://github.github.com/gh-aw/reference/aw-yml-package-manifest/).
It declares one workflow and one template resource. This repository is a public
prototype, not a verified enterprise distribution. In an isolated consumer
repository, use a reviewed commit SHA when trying its staged intent recipe:

```sh
gh aw add dmgrok/enterprise-agentic-sdlc@COMMIT_SHA
gh aw compile --strict --action-mode action --action-tag 458b269006dcf88e3b5496b6fbecabe4b9a0f954
```

Replace `COMMIT_SHA` with the full reviewed commit SHA. Installation into a live
consumer has not been verified. Pin the consumer compiler to
v0.92.0. Merge `{"strict": true}` into the consumer's
`.github/workflows/aw.json` without overwriting existing configuration. Confirm
the template is installed at `.github/aw/kit/intent-template.json`. This workflow
expects Copilot authentication through `COPILOT_GITHUB_TOKEN`; token scope,
organisation policy and billing require a live adoption test. Do not supply any
credentials to the offline proof.

The intent workflow uses manual dispatch, a 10-minute timeout, a 20-AI-credit
agent guardrail, a separate 20-credit threat-detection cap, a 100-credit daily
workflow guardrail, a 10-turn limit, explicit network access, merged-content integrity filtering,
read-only agent permissions, draft proposals limited to `work/**`, enabled
threat detection and staged safe outputs. AI credits are not a dollar budget.
These are compiler-checked configuration choices, not observed GitHub runtime results.

## Control the three axes while work runs

The controller checks **mission, quality and spend** and denies new calls and
outputs when any axis is unhealthy. Policy is fixed when a run is created;
the agent has no policy-update interface. Pauses require fresh signed telemetry
and an explicit operator resume. Stops are terminal and survive restarts.

```sh
python3 examples/control_demo.py --output reports/control-demo.json
```

The demo blocks scope drift, pauses on a quality failure, denies an over-budget
call, and actually terminates a running local process. No model or GitHub call
is made. Run the tests for automatic local termination on each axis and
concurrent-budget reservation checks.

| Axis | Controls implemented |
|---|---|
| Mission | Objective/revision binding, allowed tools and paths, scope-violation stop, stalled-progress pause |
| Quality | Required named checks, missing/failed-check pause, repair ceiling, stale-telemetry pause |
| Spend | Integer micro-USD ledger, maximum-cost reservations, cumulative ceiling, warning threshold, rolling burn limit |
| Intervention | Pause/stop/resume, SQLite audit history, real local process-group termination, GitHub cancellation/watchdog adapter |

Read [runtime controls and the operator guide](docs/runtime-controls.md) before
connecting a runtime. The local supervisor works; the GitHub adapter has mocked
API tests and defaults to dry-run. The packaged gh-aw workflow **is not yet wired
to this controller**. It retains staged outputs and its native caps. Dollar
enforcement requires every paid call to pass through a trusted gateway, and
output containment requires every write to pass through the trusted broker.

To remove the spike from a consumer, disable its workflow, remove the installed
workflow source and lock, and remove the template if no other workflow uses it.
Retain evidence records. Revoke any dedicated credential when no longer needed.

## What makes the enterprise layer

The runtime contains the agent. The kit must establish authority separately:

| Layer | Responsibility | Current evidence |
|---|---|---|
| gh-aw | Agent sandbox, scoped tools, safe outputs | One strict compilation; no live run |
| Contract evaluator | Artifact chain, human roles, freshness, scope, test evidence | Offline synthetic fixtures |
| Restricted profile | Reject unsupported tools, triggers, imports and output capabilities | Local negative tests |
| Runtime controller | Three-axis policy, spending reservations, interventions and audit | Local tests, including real child-process termination |
| GitHub cancellation | Bound run/attempt verification, cancel then force-cancel, independent watchdog | Mocked API tests; no live cancellation |
| Trusted adapter | Fetch complete GitHub records and policy from the trusted base | Not implemented |
| GitHub protections | Required checks, CODEOWNERS, review freshness, Environments | Not configured or audited |

The profile intentionally supports only the shipped intent workflow. It rejects
imports and custom jobs instead of claiming to evaluate arbitrary gh-aw
configuration. It is not the full hardened-profile checker in the target spec.

See [the implementation backlog](docs/implementation.md) for remaining work and
release acceptance criteria. No enforcement, compliance or performance claim is
made from these local tests.

## License

MIT. See [LICENSE](LICENSE). GitHub Agentic Workflows is an upstream dependency;
this project is an independent kit and is not endorsed by GitHub.
