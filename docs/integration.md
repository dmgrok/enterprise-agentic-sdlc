# Deploy the governed execution path

The repository now connects gh-aw's start and output hooks to a scoped controller
API, and Copilot BYOK to a reservation-aware model gateway. Use the loopback
fixture to verify the protocol first. No paid provider or live GitHub cancellation
has been exercised by the integration tests.

The repository also installs its compiled workflow in `.github/workflows/` for a temporary local pilot.
See [configuration](configuration.md) for the operator-owned YAML, native Copilot gateway, bounded tunnel ingress,
independent observer and human start approval. A separate bounded live Copilot gateway probe has verified inference
and settlement; that is distinct from the synthetic integration suite and a complete GitHub workflow run.

## Prove the HTTP flow locally

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python examples/http_demo.py
```

The script starts a real loopback HTTP server, creates ephemeral independent
credentials, enrolls policy, submits signed readiness, explicitly resumes and
checks admission. Its fake provider returns a proposed artifact and usage.
The gateway reserves and settles the call before returning it. A separate
collector validates the resulting files and submits their digest. The writer
then stages that exact artifact. Finally the operator stops the run and a second
model request is denied before the fake provider is called.

All files and credentials are temporary. Output includes the synthetic charge,
artifact digest and denial result, never credential values. Loopback network
access is required. The fixture is not a Copilot CLI compatibility test.

## Provision the external service

Run the service under a dedicated account with storage and credentials outside
the agent's trust boundary. The Python HTTP server listens only on loopback;
terminate HTTPS and enforce connection/request/rate limits in a reverse proxy.
Do not expose the built-in server directly to the internet.

```sh
.venv/bin/python scripts/provision_control.py --directory /CONTROL/WORK-1 --run WORK-1
```

`/CONTROL/WORK-1` must not already exist; its parent must exist. The command
creates a private directory and mode-0600 files without printing credentials:

| File | Access |
| --- | --- |
| `collector.key` | Collector and controller only |
| `auth.json` | Controller; hashes, roles and immutable run scopes |
| `credentials.json` | Provisioning operator only; distribute each role separately |
| `policy.json` | Operator-owned run policy template |
| `gateway.json` | Operator-owned, deliberately nonfunctional fixture provider settings |

Do not distribute the entire credentials file to the agent or collector. Bind
operator tokens to authenticated operator identities in `auth.json`; the identity
must be in policy's `operators`. The prototype uses possession of a role token
as authentication. Production SSO, expiry/rotation and tenant separation belong
at the deployment boundary and still need validation.

Replace the `.invalid` upstream with the exact provider chat-completions endpoint,
set a fixed model and verified input/output prices in micro-USD per million
tokens, and set provider-certified context and output bounds. The generated
fixture values are not real provider pricing. The model gateway only accepts
that model. It rejects unknown fields, alternate models, images and excessive
output limits. Provider and control hooks refuse redirects to avoid forwarding
credentials to another origin.

```sh
.venv/bin/python -m kit.service \
  --database /CONTROL/WORK-1/controller.sqlite \
  --key-file /CONTROL/WORK-1/collector.key \
  --auth-file /CONTROL/WORK-1/auth.json \
  --gateway-config /CONTROL/WORK-1/gateway.json \
  --stage-root /CONTROL/WORK-1/staged \
  --port 8080
```

Provision `KIT_UPSTREAM_API_KEY` in the service environment, not in the agent job.
Configure a process manager to restart the service and retain its database. The
control service is not itself an always-on watchdog: run `watch-github` in a
separate protected process after enrollment, as described in the
[runtime guide](runtime-controls.md).

## Configure the consumer workflow

The package manifest installs `governed-intent.md` and the intent template. The
old unconnected recipe is a regression fixture and is not installed.

```sh
gh aw add dmgrok/enterprise-agentic-sdlc@REVIEWED_COMMIT_SHA
```

Merge `{"strict": true}` into the consumer's `.github/workflows/aw.json` without
discarding existing configuration. Confirm the resource is installed as
`.github/aw/kit/intent-template.json`. A full package installation trial is still
a release prerequisite; the checked-in lock is a compiler-verified reference.

Render the supported source in a checkout of this package:

```sh
.venv/bin/python scripts/configure_governed.py \
  --controller-url https://YOUR_CONTROLLER_HOST \
  --model YOUR_FIXED_MODEL
.venv/bin/python scripts/compile.py --compiler /absolute/path/to/gh-aw
.venv/bin/python -m kit.profile .
```

Use the rendered source in the consumer's `.github/workflows/` and compile it
with v0.92.0 and the action commit in `runtime.json`. The generator requires a
literal HTTPS origin. That same origin is used for admission, output checks and
the model proxy, and its host is explicitly allowlisted by the recipe. The
default `.invalid` origin intentionally cannot run.

The supported profile accepts only the generated hook and provider configuration;
editing their bodies, enabling real safe outputs or re-enabling harness retries
fails it. The check must itself run from a protected base/pinned Action before
claiming enforcement against malicious repository changes. This repository's CI
is a regression check, not an organisation ruleset.

Configure a consumer secret `KIT_AGENT_TOKEN` containing only that run's agent
token. The recipe passes it to the trusted admission hooks and the Copilot BYOK
sidecar. It is not a provider key, signing key, collector token or operator token.
This new secret and its fixed-origin destinations have been reviewed as part of
the integration. No actual secret value is committed. Copilot authentication,
licensing and BYOK behavior must still be verified against the target GitHub
plan; compiler success alone does not establish runtime compatibility.

## Enroll while GitHub awaits start approval

The recipe requires a protected Environment named `kit-agent-start`. Configure
required human reviewers before dispatching; an unprotected Environment provides
no human gate. Dispatch with `brief` and a `controller_run` such as `WORK-1`.

While the run waits, obtain its run ID, attempt and full head SHA from GitHub and
set the policy's revision and target:

```json
{
  "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "work_item_id": "intent-123",
  "github_target": {
    "repository": "OWNER/REPOSITORY",
    "run_id": 123,
    "attempt": 1
  }
}
```

That fragment belongs inside the complete policy. Use the real values, not the
illustrative SHA. Send `{"policy": POLICY}` to `POST /runs/WORK-1` with the
operator token. Then submit independent signed readiness observations through
the collector token and explicitly resume with:

```json
{"action": "resume", "reason": "Readiness evidence reviewed"}
```

Send that to `POST /runs/WORK-1/commands` with the operator token. Only then
approve the GitHub Environment. Fresh collector heartbeats must continue during
execution. Enrollment, collector operation, operator acceptance and the GitHub
Environment approval are intentionally separate steps; the agent cannot perform
them using its credential.

The start hook binds repository, run ID, attempt and revision to the enrolled
policy. A missing service, bad token, stale observation, mismatched attempt or
paused controller prevents agent execution. Neither hook retries a rejected
decision or automatically resumes a run.

## Collect actual output evidence

The recipe exports the `work/` tree as
`kit-intent-RUN_ID-ATTEMPT`, using a pinned upload action after execution. It does
not read or export gh-aw's protected safe-output files. The independent collector
must verify the platform run/attempt/head SHA and artifact provenance before
downloading; use a separate Actions-read identity. The included collector accepts
an already verified download, not arbitrary agent-supplied provenance.

The downloaded tree has `WORK_ITEM_ID/intent.json` at its root. Collect it with:

```sh
.venv/bin/python -m kit.collector \
  --work-directory /COLLECTOR/VERIFIED_DOWNLOAD \
  --policy /CONTROL/WORK-1/policy.json \
  --run WORK-1 --sequence 3 \
  --key-file /CONTROL/WORK-1/collector.key
```

The command checks the actual inventory, rejects symlinks and out-of-scope paths,
validates the intent schema, and computes the canonical artifact digest. It
prints a signed envelope for `POST /runs/WORK-1/telemetry` using the collector
token. Sequence numbers must increase; timestamps expire under policy. Preserve
repair counts across attempts.

The collector establishes structural quality and declared path scope, not
semantic correctness. Its cost-coverage assertion is valid only where the
deployment routes all inference through the gateway. Add tests, security checks
and a qualified human/task-specific evaluator as required by the approved work.

The final safe-output hook requires healthy state, the configured output checks and an independently observed
artifact digest. It waits at most 60 seconds for that evidence while the controller remains running, then makes
one decision request. A late collector fails safely. It never retries a denied decision or resumes a paused run.

For controller-owned staging, send the binding, logical artifact path and actual
artifact to `POST /runs/WORK-1/stage` using the writer token. The broker recomputes
the digest and checks the exact revision, current health and policy scope under
the controller transaction before writing its own staging store.

Real GitHub safe outputs remain disabled through staged mode. An HTTP output
check is not a durable authorisation token, and a later stop can race a future
platform write. Do not enable real writes until a protected GitHub writer and
idempotency/reconciliation path have passed live boundary tests.

## Compatibility and evidence

| Component | Evidence |
| --- | --- |
| gh-aw v0.92.0 source and lock | Compiles with protected start, BYOK, pre-agent and safe-output hooks |
| Controller HTTP protocol | Real loopback requests in tests and demonstration |
| Provider forwarding and billing | Fake-provider fixtures; no paid provider call |
| OpenAI-compatible streaming | Buffered completion-to-SSE fixture; no live incremental stream |
| Artifact collector/broker | Actual files, schema checks, digest binding and protected local staging |
| GitHub cancellation | Mocked API tests; no live cancellation |
| Copilot BYOK and complete GitHub run | Deployment trial still required |

Admission, ledger and schema failures stay closed. Live deployment also needs
alert delivery, credential rotation, service isolation, retry admission across
attempts and rulesets/required checks for the lifecycle authority path. See the
[implementation roadmap](implementation.md).
