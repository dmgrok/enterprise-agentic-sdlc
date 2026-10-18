# From contract spike to enterprise kit

The first executable slice establishes a proposed contract. Release remains
blocked until an independent authority path is working against real GitHub
records. Staged outputs stay on until that proof exists.

## Next vertical slice: approved plan to bounded implementation

The three-axis controller now has a role-scoped HTTP API, reservation-aware chat
proxy, independent artifact collector and controller-owned staging broker. The
installable gh-aw recipe calls admission before the agent, routes BYOK inference
through that gateway and checks output evidence before safe-output handling.
See the [integration guide](integration.md). Local HTTP fixtures and compilation
prove those interfaces; a paid Copilot run, trusted artifact-provenance download,
production service deployment and live cancellation still need verification.
Safe outputs remain staged. The original unconnected recipe is a regression
fixture and is no longer installed by the package manifest.

1. Build a trusted adapter that takes repository and PR identity from the event,
   fetches all review pages, verifies human account types and excludes every
   automation credential owner. Resolve current effective reviews and reject
   stale, dismissed and superseded approvals. Never accept a PR-authored snapshot.
2. Read policy and evaluator code from an immutable trusted revision. Fetch the
   merged plan at its recorded commit, prove default-branch reachability and the
   approved artifact PR, verify its content digest and derive the artifact chain.
   Re-evaluate risk from actual paths and policy, rather than a declared field.
3. Fetch trusted required-check runs bound to the implementation head and their
   command, conclusion and artifact digests. A success string in a PR is not
   test evidence. Define which check-producing Apps are authorised.
4. Publish the validator as a SHA-pinned Action and run it before the agent.
   The workflow must fail closed on missing metadata or invalid policy. A PR
   cannot edit or replace the Action that evaluates it.
5. Add the implementation workflow with scope from the approved plan. Until
   accepted deviation evidence has its own contract, require a newly approved
   plan for scope changes. Account for renames, deletions, symlinks, protected
   paths and nested instruction files, not only filename strings.
6. Exercise the required check independently of all agent workflows. Verify
   checks re-evaluate after reviews and head updates. Test review events and
   merge queue behavior on the target GitHub plan before selecting a trigger.

## Runtime and packaging spikes still required

| Question | Required proof |
|---|---|
| Jobs in imports | Compile and execute a minimal custom gate job; keep jobs in main workflows until proved |
| Resources and existing files | `gh aw add` in a clean consumer and one with existing CODEOWNERS; prove collision behavior |
| Safe-output identity | Dedicated GitHub App permissions; opened PR triggers required CI without approval powers |
| High-risk work | Protected Environment before agent and before writes, both revision-bound; prove denial blocks writes |
| Cost | Synthetic golden path with Copilot and Claude under an explicit budget; measure cost, do not estimate from credit count |
| Enforcement | Required rulesets/checks, CODEOWNERS, dismissed stale reviews, latest-push approval and no bot approvals |

## Complete the package

Add specification, plan, implementation, release-readiness and incident workflows
only as their predecessors can be verified. Introduce shared hardened imports
after merge semantics have a test. JSON Schemas now cover intent, telemetry,
control policy, GitHub binding and offline gate evidence. Extend them with the
remaining lifecycle artifacts, settings guide and read-only settings audit.
Support a human-readable rendering without making prose an authority source.
Publish compatibility results for exact compiler, engine and GitHub plan
combinations. Add attribution for any reused upstream sample code.

The existing target acceptance tests K1-K11 have **not** passed. Local tests
exercise portions of K2-K4, K6, K8 and K9 with synthetic inputs; they are not
substitutes for live gate enforcement. K1 installation, K5 independent merge
enforcement, K7 fork/injection behavior, K10 installed lock drift, and K11 egress
denial need dedicated consumer runs. K12 needs external adoption trials.

Before a technical release: recheck upstream advisories for the exact pinned
version, verify licensing and attribution for any newly reused code, and scan
the release export. This public prototype is MIT-licensed and contains newly
written generic code and synthetic fixtures. Publication is not evidence that
the technical release criteria have passed.
