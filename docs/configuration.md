# Configure acceptance, instructions and execution

The operator owns the rules. The agent supplies proposed work and receives the gate's decision.
Editing prose in an agent prompt cannot override an enforced controller or GitHub rule.

## YAML files

`.kit/agent-policy.yml` contains `workflow`, `guidelines` and `runtime` sections. It is parsed with duplicate-key
rejection and validated against the runtime schema before provisioning. Unknown top-level and runtime keys fail.
`runtime` is copied into a private per-run policy; enrollment binds its revision, GitHub run/attempt and work item.
Changing the repository YAML does not silently change an already enrolled run or reset its spend.

```yaml
runtime:
  mandatory_checks: [workflow-profile]
  output_mandatory_checks: [scope, artifact-schema]
  max_repair_attempts: 2
  max_runtime_seconds: 600
  telemetry_ttl_seconds: 15
  max_spend_microusd: 2000000
  warn_spend_microusd: 1500000
  max_burn_microusd_per_minute: 1000000
```

This fragment omits required fields; edit the complete checked-in example. One million micro-USD equals $1.
`mandatory_checks` must pass before execution and remain fresh. `output_mandatory_checks` must pass before
accepting output. An intent artifact cannot have a schema result before it exists, so the pilot checks the
workflow profile at admission and independently checks the downloaded artifact before releasing staged output.
Structural checks do not establish semantic correctness; human acceptance remains required.

`.github/dependency-review-config.yml` is the native configuration for the dependency PR gate:

```yaml
fail-on-severity: high
warn-only: false
```

| Finding introduced by the PR | Result |
| --- | --- |
| Critical or high | Check fails; merging is blocked when the check is required |
| Moderate or low | Check passes with findings visible in the review |
| Scanner failure or unavailable evidence | Check fails; never translated into success |

The check uses the policy from the PR's **base SHA**. Agent-authored changes cannot relax the rule in the same PR.
It does not scan every existing dependency or replace secret scanning, SAST or runtime exposure analysis.
This threshold does not automatically add a security collector to an intent-drafting run.

The `guidelines` block is the human-written instruction text. The generated workflow also fixes its narrow task:
draft one proposed intent, never approve, merge or deploy, and keep outputs staged. To change supported tools,
native credit/turn limits or the task itself, change the generator and profile together and review the result.

## Render, compile and install after changes

```sh
python scripts/configure_governed.py
python scripts/compile.py --compiler /absolute/path/to/gh-aw-v0.92.0
python scripts/install_workflow.py
python scripts/install_workflow.py --check
python -m kit.profile .
python -m unittest discover -v
```

Commit the YAML, generated Markdown, and both compiled lock copies together. CI detects installed-copy drift.
Compilation uses the pinned compiler and action commit recorded in `runtime.json`.
Read the [integration guide](integration.md) before using this on another repository.

## Run locally with GitHub-native inference

GitHub's separate Models service was retired on July 30, 2026. This pilot uses models hosted through **Copilot**,
with its API behind the kit's model gateway. Copilot CLI uses the gateway as an OpenAI-compatible endpoint;
the gateway forwards to the fixed GitHub-hosted `api.githubcopilot.com/chat/completions` endpoint.
Only the gateway has the fine-grained Copilot token. The cloud agent receives a separate run-scoped gateway token.

The model catalog must confirm the exact model, enabled policy, chat-completion support, limits and token prices.
Reserve against the largest input/cache price and certified context limit. The native adapter settles using
Copilot's `copilot_usage.total_nano_aiu`, rounded upward to micro-USD (1 AI credit equals $0.01).
Missing billing evidence retains the reservation and pauses the run. Catalog/pricing changes require revalidation;
the adapter currently covers text/tool chat completions only. It does not implement Responses or multimodal input.
The inference ceiling excludes Actions runner/storage and other charges.

The selected pilot is **local only**: no public tunnel and no GitHub workflow dispatch. Run:

```sh
python scripts/configure_copilot_gateway.py --key-file /PRIVATE/copilot.token \
  --output /PRIVATE/verified-gateway.json
python scripts/run_local_pilot.py --directory /PRIVATE/NEW-LOCAL-RUN \
  --gateway-config /PRIVATE/verified-gateway.json --provider-key-file /PRIVATE/copilot.token
```

The directory must be new. Copilot CLI runs in an isolated work directory with only its create-file tool enabled,
an exact allowed output file, shell tools denied, custom instructions and built-in MCPs disabled, automatic updates
disabled and `COPILOT_OFFLINE=true`. In this mode the CLI reaches only the local gateway; that gateway calls GitHub.
The child receives a limited run token, never the provider token or collector/operator credentials. A collector
checks actual local file scope during execution; final schema and digest checks gate staging. The controller
supervises the process group and stops it on an unhealthy axis. Candidate staging is followed by a terminal stop
and a test that another model request is denied. Human acceptance remains pending.
The CLI's tool/path controls and same-user processes are suitable for this pilot, not an adversarial OS sandbox.
The native gateway settings are generated from the authenticated catalog, with unsupported pricing tiers rejected.
Configuration output must be a new private file. There is no automatic retry of a failed local attempt. An explicit
repair invocation must carry prior spend through `--prior-spend-microusd` and the repair count through
`--repair-attempts`; these remain operator assertions in this prototype, not an organization-wide budget ledger.

The installed cloud workflow remains closed at `.invalid` and has no `KIT_AGENT_TOKEN` secret. The protected
Environment exists, but GitHub-hosted runners cannot reach a loopback-only controller on the Mac. Use a separately
approved private network or runner deployment before enabling that path. The local pilot is not a gh-aw Actions run.

## Optional temporary tunnel deployment

This alternative was **not selected** for the current pilot. It requires explicit approval to transmit the limited
agent credential and traffic through the TLS-terminating intermediary. The tunnel used during setup was closed,
and its cloud agent credential was removed. No public tunnel is required for the local command above.

The pilot process exposes two loopback ports. The tunnel connects only to the bounded agent-only ingress on 8080.
The complete operator/collector API remains on 8081. Public ingress authenticates before reading a request body,
limits request size, connection duration, concurrency and request rate, and denies operator/collector/writer routes.
Cloudflare terminates public TLS and can inspect pilot traffic and its limited agent credential. A quick tunnel
is temporary and is not a production deployment. No credential belongs in Git or the YAML files.

```sh
python scripts/provision_control.py --directory /PRIVATE/PILOT-1 --run PILOT-1
# Configure gateway.json from verified Copilot catalog data, never guessed pricing.
python scripts/pilot_server.py --directory /PRIVATE/PILOT-1 --run PILOT-1 \
  --provider-key-file /PRIVATE/copilot.token
cloudflared tunnel --url http://127.0.0.1:8080 --no-autoupdate
```

Set `workflow.controller_url` to the actual temporary HTTPS origin, then render/compile/install.
Store only the `agent` credential from private provisioning as the repository secret `KIT_AGENT_TOKEN`.
Keep the provider token, operator token, signing key and private database on the Mac.
Configure `kit-agent-start` to require the human reviewer and allow only `main` before dispatching:

```sh
gh workflow run governed-intent.lock.yml --repo OWNER/REPO --ref main \
  -f controller_run=PILOT-1 -f brief='Draft an intent for documenting the acceptance policy.'
python scripts/observe_pilot.py --directory /PRIVATE/PILOT-1 --run PILOT-1 \
  --repository OWNER/REPO --github-run ACTUAL_RUN_ID
```

The observer verifies the GitHub SHA/run/attempt, enrolls the immutable policy and checks actual workflow readiness.
It maintains signed observations, independently verifies/downloads the output artifact and checks its scope/schema.
Artifact verification includes the platform digest, run ID and head SHA, with bounded extraction and no symlinks.
The final hook waits at most 60 seconds for this independent evidence; it does not retry a rejected decision.
The watchdog cancels on unhealthy state, operator pause/stop or collector loss. Neither observation nor a workflow
retry automatically resumes the controller. **Approve the pending Environment job in GitHub as the human reviewer.**

Pause or stop through the private local operator interface (no public operator endpoint):

```sh
python -m kit.control_cli --database /PRIVATE/PILOT-1/controller.sqlite \
  --key-file /PRIVATE/PILOT-1/collector.key --run PILOT-1 pause --actor operator --reason 'Review requested'
python -m kit.control_cli --database /PRIVATE/PILOT-1/controller.sqlite \
  --key-file /PRIVATE/PILOT-1/collector.key --run PILOT-1 stop --actor operator --reason 'Emergency stop'
```

The pilot's clock starts at enrollment and ends after the configured 600 seconds, including approval waiting time.
After expiry, a new pilot needs explicit enrollment, a new agent credential and a reviewed budget; no automatic restart.
When finished, stop the observer/server/tunnel, delete the run-scoped repository secret and rotate exposed credentials.
The agent runs in GitHub's sandbox, separate from the Mac. Same-user local services are a pilot deployment boundary,
not production multi-tenant isolation, SSO or an always-available control plane.

## Sources

- [GitHub Models retirement](https://docs.github.com/en/github-models)
- [gh-aw authentication](https://github.github.com/gh-aw/reference/auth/)
- [GitHub Copilot billing](https://docs.github.com/en/billing/concepts/product-billing/github-copilot-billing)
- [Dependency review configuration](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/configure-dependency-review-action)
