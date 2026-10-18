# Market Detective: an issue-driven delivery testbed

The product helps a reader investigate connections between market events, equities and digital assets.
It shows explanatory transmission maps, source documents, caveats and a reversible challenged-link state.
Cases are explicitly illustrative. A documented mechanism is not proof of an episode's cause or a price forecast.

The initial cases cover monetary-policy transmission and a stablecoin losing its peg. A third case is intended
to arrive through an actual ticket and PR, proving that the delivery loop changes the deployed product.

## The delivery contract

1. An issue records the user question and acceptance criteria. Its title appears in the site's release notebook.
2. A maintainer reviews a structured case and adds `agent:ready`.
3. A bounded content worker verifies author/actor authority, policy and the case graph. It proposes exactly one
   new JSON file under `site/cases/`, verifies the server-side diff, and opens a **draft** PR.
4. It explicitly dispatches the test and dependency workflows. Both check runs bind to the proposed commit.
5. A maintainer reviews the result, marks it ready, and merges after required checks pass.
6. Pages validates and builds the new main revision, refreshes its real issue notebook and deploys the artifact.

The worker never merges or deploys. Opening arbitrary tickets does not grant code execution or bypass review.
Normal feature tickets remain engineering work; they are not silently interpreted as shell commands or LLM prompts.
No public model gateway, external controller route or provider credential is added by this demo.

The first lane is intentionally deterministic: structured content transforms do not need an LLM. This gives
the kit a real CI/CD baseline with clear scope, quality and consumption controls. Autonomous LLM code delivery
through gh-aw remains a separate integration requiring the approved private controller connection.

## Configure the worker

Edit `.kit/site-policy.yml` through a reviewed PR. Its defaults require an owner-authored issue, a write-capable
actor, both `site:case` and `agent:ready` labels, one new case file, a 16 KB ceiling, at most two open worker PRs,
zero model calls and maintainer-controlled merging. The job has a three-minute execution ceiling. GitHub Actions
minutes/storage are platform consumption, not a claim of zero infrastructure cost.

The site model rejects unknown fields, HTML markup, invalid identifiers, duplicate positions, missing evidence,
disconnected nodes, backward/cyclic connections, oversized content and unapproved source origins. Primary sources
are allowlisted to `www.bis.org`, `www.federalreserve.gov`, `www.sec.gov` and `www.investor.gov`. Schema validation
does not prove that a source supports the explanation; that remains a review responsibility.

## Request a market case

Use **Investigate a market connection** in the GitHub issue chooser. Copy a complete example from `site/cases/`,
choose a new ID and edit the question, nodes, edges and sources. GitHub wraps the JSON textarea in a code fence.
The parser accepts exactly one JSON fence and never evaluates its contents. Use short node labels that fit in
two lines; all sources must be HTTPS primary-source links from the allowed origins.

For a programmatic issue, use this body shape:

````markdown
### What should this explain?
State the user question and observable acceptance criteria.

### Case JSON
```json
{ "complete": "copy and adapt one of the real examples, not this placeholder" }
```
````

Only after reviewing the case should a maintainer add `agent:ready`. A failed proposal gets `agent:blocked`
and the approval label is removed. Fix the evidence or scope, inspect the failure, then explicitly approve
another attempt. Duplicate events cannot create duplicate PRs. An interrupted proposal with an existing branch
requires explicit reconciliation; there is no automatic overwrite, retry, budget reset or auto-merge.

## Required GitHub settings

- Pages publishing source is **GitHub Actions**. The `github-pages` Environment permits only `main`.
- Main's acceptance rules require `test` and `Dependency policy`. Dependency policy blocks newly introduced
  high/critical findings; low/moderate findings can proceed. Existing vulnerabilities need separate handling.
- The repository permits GitHub Actions to create PRs. GitHub exposes this as the combined
  `can_approve_pull_request_reviews` setting. The worker uses PR creation only and has no review-approval or merge step.
- Issues and labels exist. The worker reads trusted default-branch code; it never checks out issue-supplied code.
- The repository variable `SITE_CASE_AUTOMATION` is `enabled` only after the operator approves activation.
  Without it, the worker does not run and the public notebook accurately reports manual proposal mode.
  To stop future jobs, disable that variable. Cancel any in-flight job in Actions; every worker also has a three-minute ceiling.

PRs created with `GITHUB_TOKEN` do not trigger ordinary PR workflows. Explicit `workflow_dispatch` calls are used
for both required checks, with immutable base/head SHAs for dependency review and the head branch for check-run
association. This avoids a PR that appears created but has no checks. The dependency threshold is read from the
base SHA, so the proposed change cannot lower its own acceptance policy.

The worker needs repository contents, issues, PR and Actions writes for these bounded operations. Its code and
policy therefore belong to the protected main trust boundary. Never replace the validator with execution of
ticket prose, install dependencies named by a ticket, or move this to an untrusted checkout with write credentials.

## Run and verify locally

```sh
node --test site/tests/*.test.mjs
node scripts/build_site.mjs
python3 -m http.server 8000 --directory _site
```

Open localhost:8000. The default local build has an honestly empty issue notebook. A release build uses
`node scripts/build_site.mjs --github` to retrieve real public issue metadata; it fails if that retrieval fails.
No token is included in the static files. Copy is inserted with DOM `textContent`, not interpreted as HTML.

The existing diagram tooling supplies the browser dependency for actual desktop/mobile verification:

```sh
cd tools/diagrams
PUPPETEER_SKIP_DOWNLOAD=true npm ci --ignore-scripts
cd ../..
node scripts/check_site_browser.mjs
```

Browser checks cover case switching, evidence selection, source links, challenged/alternate paths, restoration,
shareable state, mobile overflow and the real loading failure/recovery control. Screenshots go to `reports/site/`.
The site has no runtime npm dependencies, third-party font requests, model calls or market-data credentials.

## Sources and limitations

The sources are linked on each connection. Rate and equity-valuation mechanisms use Federal Reserve material;
stablecoin/leverage mechanisms use BIS material; the ETF case should use SEC/investor-education sources.
Digital-asset responses to macro conditions remain explicitly context dependent. The diagrams are curated
investigation aids, not measured causal models, forecasts, investment recommendations or live news.

See [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
and [GITHUB_TOKEN event behavior](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication).
