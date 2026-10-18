# Enterprise Agentic SDLC Kit

**Keep an agent on mission, producing acceptable work, and within budget while it runs.**
Built on [GitHub Agentic Workflows](https://github.com/github/gh-aw), with an independent controller
that can deny the next model call, withhold an output, pause a run, or request cancellation.

[![Tests](https://github.com/dmgrok/enterprise-agentic-sdlc/actions/workflows/ci.yml/badge.svg)](https://github.com/dmgrok/enterprise-agentic-sdlc/actions/workflows/ci.yml)

**Integration prototype.** The governed recipe compiles against `gh-aw v0.92.0`. Its admission hooks,
reservation-aware model gateway, independent artifact collector and staging broker have executable fixture tests.
A live local Copilot CLI pilot has verified native inference, billing settlement, independent artifact checks,
staging and denial after stop. See the [recorded result](docs/local-pilot-proof.json) and
[proposed artifact](examples/proposed-intent.json). A complete gh-aw agent run on GitHub remains a validation step.
The installable recipe keeps safe outputs
staged. This is not a production release or a compliance certification.

## Configure your agents and acceptance rules

| What you want to change | Edit here | Enforcement |
| --- | --- | --- |
| Mission scope, required checks, repair/time/spend limits | [.kit/agent-policy.yml](.kit/agent-policy.yml) | Frozen into each enrolled controller run |
| Written agent guidelines and selected model | [.kit/agent-policy.yml](.kit/agent-policy.yml) | Rendered into the gh-aw source, then compiled |
| Dependency vulnerability threshold | [.github/dependency-review-config.yml](.github/dependency-review-config.yml) | Dependency policy PR check |
| Trigger, allowed tools, native limits and staged outputs | [governed-intent.md](.github/workflows/governed-intent.md) | Compiled Actions workflow and restricted profile |

The dependency rule is `fail-on-severity: high`: new high/critical vulnerabilities block the check;
low/moderate findings may proceed. Missing or failed scans do not become a pass. Make **Dependency policy**
a required status check to block merging. The workflow reads its configuration from the PR's base commit,
so a PR cannot lower its own threshold. This check covers dependency changes introduced by the PR;
existing vulnerabilities and other security findings need separate checks.

Change policy through reviewed configuration changes. The agent cannot grant itself an exception or resume itself.
See [configuration and the local pilot](docs/configuration.md) for commands, approval, operation and limitations.

## Run the installed workflow

The compiled **Governed Intent** workflow is installed in [Actions](https://github.com/dmgrok/enterprise-agentic-sdlc/actions/workflows/governed-intent.lock.yml).
It is manual-only and requires approval in `kit-agent-start`. The current pilot runs locally;
the cloud workflow deliberately retains an unusable controller origin and has no agent secret.
GitHub-hosted execution needs a private controller connection or an explicitly approved hosted deployment.
The provider credential stays in the local gateway. Safe outputs remain staged for human acceptance.

## The three operating axes

| Axis | Question | Signals and intervention |
| --- | --- | --- |
| Mission | Is the agent doing the approved job? | Bind objective and revision; restrict tools and paths; stop on scope escape; pause on stalled progress |
| Quality | Is the result acceptable? | Require fresh named checks; bind artifact checks to a digest; pause on failure; stop at the repair ceiling |
| Spend | Are cost and consumption under control? | Reserve maximum cost before a call; settle usage afterward; enforce cumulative and rolling limits |

**Continue = mission healthy AND quality healthy AND spend healthy.** Missing critical evidence pauses the run.
Schema checks establish structure and scope. Human acceptance and task-specific evaluations still establish whether
an artifact solves the original problem.

## Who runs the agent, and who controls it?

The agent does the work. A separate controller decides whether it may continue.
The human operator can pause or stop it at any time.

![The agent reaches the provider through a gateway supervised by an independent controller.](docs/diagrams/overview.svg)

The agent credential can request inference and check admission for **one enrolled run**. It cannot create policy,
sign telemetry, resume itself or stage writes. Collector, operator and writer credentials are separate.
The real provider key lives in the gateway. Deployment must keep the control database, signing key and those
privileged credentials outside the agent's filesystem and network authority.

The overview shows the model-call path. The controller also governs artifact staging and an external watchdog
can request cancellation. Those details are explained in the flows below and the
[integration guide](docs/integration.md). Hosting and operational setup remain deployment work.

Diagrams use rendered SVGs for reliable GitHub display. Their
[editable Mermaid sources](docs/diagrams/) are checked with the renderer in CI.

## Six delivery gates

Each gate answers one question. Agents propose the evidence; a responsible person decides whether to proceed.

![Six delivery gates from defining the problem to learning from incidents.](docs/diagrams/lifecycle.svg)

Agents propose artifacts; people decide. Approval authority comes from trusted platform records, never an
`approved: true` field. The offline evaluator covers all six contracts. The packaged workflows currently draft
**intent only**; the other five agent workflows and the live lifecycle-approval adapter remain on the
[implementation roadmap](docs/implementation.md).

## Follow one model call

The gateway checks mission, quality, spending limits and the cost of this request **before** contacting the provider.
It records the actual cost afterward.
The rejection branch does not spend money on a provider request.

![A model call is rejected before reaching the provider unless all three axes are healthy and its cost can be reserved.](docs/diagrams/model-call.svg)

Budget admission counts **settled spend + every outstanding maximum reservation + the proposed request**.
Retries keep their accumulated spend. Unknown provider usage retains the reservation and pauses the run.
The gateway reserves the configured model context bound and requested output bound, rather than guessing token
counts from character length. Rates and token bounds must come from the operator's actual provider contract.
The example rates used by tests are synthetic.

Supported proxy surface: OpenAI-compatible, text/tool chat completions for one explicitly priced model.
Streaming clients receive buffered SSE after settlement. Responses API, multimodal requests, other currencies,
provider-specific fees and live streaming are not implemented. Runner and storage charges need separate accounting.

## Pause, stop and resume

A new run starts paused. Resuming it needs fresh healthy checks and an explicit human decision.
A human can stop either a running or paused run. A stop ends this enrolled run permanently.

![A run starts paused, needs a human decision to resume, and cannot resume after a terminal stop.](docs/diagrams/run-states.svg)

Pause denies new calls and outputs. The local supervisor terminates the current process; the GitHub watchdog
requests cancellation of the attempt. Resume is a new explicit execution decision, not suspension of an in-flight
provider request. Completed writes and consumed tokens cannot be undone. A cancelled GitHub attempt needs an
explicitly authorised, budget-preserving handoff; that cross-attempt workflow is not implemented yet.

## Quick start without a model credential

Python 3.10 or later on Linux or macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python -m kit.profile .
.venv/bin/python examples/control_demo.py --output reports/control-demo.json
.venv/bin/python examples/http_demo.py
```

The local demo stops real child processes. The HTTP demo exercises role separation, admission, a fake provider,
usage settlement, independent artifact checks, staging and a denied call after stop. Tests include schema and
negative-path coverage, concurrent reservations, stale evidence, all three axis breaches and mocked cancellation.
No paid provider is contacted by these commands.

## Machine-readable contracts

All schemas use JSON Schema Draft 2020-12 and are validated by tests. They describe candidate `0.1` contracts.

| Contract | Purpose | Source |
| --- | --- | --- |
| Control policy | Immutable objective, revision, tools, paths, operators and thresholds | [control-policy.schema.json](schemas/control-policy.schema.json) |
| GitHub binding | Repository, numeric run ID, attempt and exact revision | [binding.schema.json](schemas/binding.schema.json) |
| Telemetry | Signed three-axis observation, monotonic sequence, timestamp and artifact digest | [telemetry.schema.json](schemas/telemetry.schema.json) |
| Intent | Proposed artifact; excludes approval-granting fields | [intent.schema.json](schemas/intent.schema.json) |
| Gate evidence | Offline lifecycle-validator report, including checks and corrective actions | [evidence.schema.json](schemas/evidence.schema.json) |

An observation before signing looks like this. These hashes and timestamp are illustrative; use the actual enrolled
policy digest, subject SHA and current epoch time when sending evidence.

```json
{
  "run_id": "WORK-1",
  "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "policy_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "sequence": 3,
  "observed_at": 1792288800,
  "mission": {
    "objective_id": "draft-intent",
    "scope_violation": false,
    "progress": "advancing"
  },
  "quality": {
    "checks": {"scope": "pass", "artifact-schema": "pass"},
    "repair_attempts": 0,
    "artifact_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "spend": {"accounting": "reservation-ledger", "coverage": "complete"}
}
```

The collector wraps this as `{ "event": EVENT, "signature": HMAC_SHA256 }`. The signature covers canonical JSON.
It authenticates a trusted collector, not the truth of an agent's own statements. The independent collector checks
actual files and the broker recomputes the artifact digest before staging.

### Before an artifact is staged

![Independent checks identify the exact artifact by its digest before the controller permits staging.](docs/diagrams/artifact-check.svg)

A valid signature alone does not establish quality. The collector must check the actual file; the broker then
compares its digest with that evidence. A failed check, changed artifact or unhealthy run blocks staging.
Staging still requires a separate human acceptance decision before production use.

Each run retains its policy snapshot, observations, cost reservations and audit history. See the schema links
above for field-level details.

## Connect the governed gh-aw recipe

The package installs only the governed recipe. The original unconnected recipe is retained as a test fixture:

| Recipe | Execution |
| --- | --- |
| `fixtures/gh-aw/draft-intent.md` | Regression fixture only; not installed by `aw.yml` |
| `governed-intent.md` | Protected start approval, external admission, BYOK gateway, artifact export and final output check |

1. Deploy the controller behind HTTPS and provision separate scoped credentials. Follow the
   [integration deployment guide](docs/integration.md). The built-in HTTP server binds loopback for a TLS reverse proxy.
2. Choose a fixed provider model and verified pricing/token bounds. Set the real provider credential only on the server.
3. Install into a fixture repository using a reviewed commit SHA:

   ```sh
   gh aw add dmgrok/enterprise-agentic-sdlc@COMMIT_SHA
   ```

4. Configure the governed source in this package, then compile it with the pinned compiler before distributing the
   resulting source/lock pair to the consumer:

   ```sh
   .venv/bin/python scripts/configure_governed.py --controller-url https://YOUR_CONTROLLER_HOST --model YOUR_MODEL
   .venv/bin/python scripts/compile.py --compiler /absolute/path/to/gh-aw
   ```

   The checked-in controller address uses the reserved `.invalid` domain and cannot contact a real service.
5. Configure `KIT_AGENT_TOKEN` on the consumer and a protected Environment named `kit-agent-start`. Dispatch with a
   controller run ID. While GitHub waits for that approval, enroll the exact repository/run/attempt/SHA on the controller,
   start independent readiness observations and explicitly resume. Then approve the Environment.
6. Keep collector heartbeats fresh during execution. Download the exported `kit-intent-RUN_ID-ATTEMPT` work artifact
   using a trusted, provenance-verifying collector. Validate the actual files, submit signed digest-bound results and
   retain human acceptance as a separate decision. The final hook denies execution without independent artifact evidence.

The installable recipe retains staged safe outputs. The final HTTP check is a snapshot and cannot make a later GitHub write
atomic with controller state. The supplied writer broker stages artifacts under the controller's authority; a
production GitHub writer must use an equivalent atomic/reconciled authority path before real writes are enabled.
A full consumer installation and paid Copilot BYOK run still require a deployment trial.

## API and operator reference

| Endpoint | Credential role | Effect |
| --- | --- | --- |
| `POST /runs/{id}` | Operator | Enroll immutable policy |
| `POST /runs/{id}/telemetry` | Collector | Accept signed evidence |
| `POST /runs/{id}/commands` | Operator | Pause, stop or explicit resume |
| `POST /runs/{id}/admission` | Agent | Check current health and GitHub binding |
| `POST /v1/chat/completions` | Agent | Reserve, call fixed provider, settle |
| `POST /runs/{id}/output-check` | Agent | Require healthy state and independent artifact digest |
| `POST /runs/{id}/stage` | Writer | Validate and stage the exact digest-bound artifact |
| `GET /runs/{id}` | Any scoped role | Inspect state |
| `GET /runs/{id}/audit` | Operator | Read audit history |

Every credential is scoped to one enrolled run. The service stores token hashes; the collector HMAC key and
upstream key are provisioned separately. HTTP logs do not include request bodies, provider responses or credentials.
The prototype requires a protected reverse proxy for TLS, rate/connection limits and production authentication.

- [Deploy and operate the HTTP integration](docs/integration.md)
- [Runtime policy, reservations and intervention details](docs/runtime-controls.md)
- [Remaining enterprise release criteria](docs/implementation.md)
- [Contributing and verification](CONTRIBUTING.md)

## Reproduce the compiled recipe

Compiler: **gh-aw v0.92.0**. Actions dependency: **`458b269006dcf88e3b5496b6fbecabe4b9a0f954`**.
Download the official [release binary](https://github.com/github/gh-aw/releases/tag/v0.92.0), verify its checksum,
and run:

```sh
.venv/bin/python scripts/compile.py --compiler /absolute/path/to/gh-aw --check
```

Compilation occurs in a temporary consumer repository. CI runs deterministic tests and fixture demonstrations;
it does not invoke an agent. Repository protections and the remaining six-gate enforcement path need separate
configuration and validation.

## License

MIT, see [LICENSE](LICENSE). This is an independent project, not endorsed by GitHub.
