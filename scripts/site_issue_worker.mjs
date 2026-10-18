import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { parseIssue } from '../site/model.mjs';

export function evaluateIssue(issue, actorPermission, policy) {
  if (policy.schema_version !== '1' || policy.model_calls !== 0 || policy.merge !== 'human_review'
    || policy.allowed_path_prefix !== 'site/cases/' || policy.maximum_changed_files !== 1
    || !Number.isInteger(policy.maximum_case_bytes) || policy.maximum_case_bytes > 16000
    || policy.maximum_case_bytes < 1 || !Number.isInteger(policy.maximum_open_worker_prs)
    || policy.maximum_open_worker_prs < 1 || policy.maximum_open_worker_prs > 2) throw new Error('Unsupported worker policy');
  const labels = new Set(issue.labels.map(label => label.name));
  if (issue.pull_request || issue.state !== 'open' || !labels.has(policy.approved_label) || !labels.has(policy.case_label)
    || !policy.allowed_author_associations.includes(issue.author_association)
    || !policy.allowed_actor_permissions.includes(actorPermission)) throw new Error('Issue is not approved for this worker');
  const marketCase = parseIssue(issue.body);
  const content = JSON.stringify(marketCase, null, 2) + '\n';
  if (Buffer.byteLength(content) > policy.maximum_case_bytes) throw new Error('Case exceeds policy size ceiling');
  return { path: policy.allowed_path_prefix + marketCase.id + '.json', content, marketCase };
}

export function verifyChangedFiles(comparison, expectedPath) {
  if (comparison.total_commits !== 1 || comparison.files?.length !== 1
    || comparison.files[0].filename !== expectedPath || comparison.files[0].status !== 'added') {
    throw new Error('Proposed commit escaped the approved one-file scope');
  }
}

export async function deliver(api, issueNumber, actor, policy) {
  const issue = await api('GET', `/issues/${issueNumber}`);
  const account = await api('GET', `/collaborators/${encodeURIComponent(actor)}/permission`);
  const proposed = evaluateIssue(issue, account.permission, policy);
  const branch = `codex/market-case-${issueNumber}`;
  const existing = await api('GET', '/pulls?state=all&head=' + encodeURIComponent(api.owner + ':' + branch));
  if (existing.length) return { state: 'already-proposed', pull_request: existing[0].html_url, model_calls: 0 };
  const open = await api('GET', '/pulls?state=open&per_page=100');
  if (open.filter(pr => pr.head.ref.startsWith('codex/market-case-')).length >= policy.maximum_open_worker_prs) throw new Error('Open worker PR ceiling reached');
  const repository = await api('GET', '');
  const base = repository.default_branch;
  const baseRef = await api('GET', '/git/ref/heads/' + encodeURIComponent(base));
  const baseSha = baseRef.object.sha;
  const baseCommit = await api('GET', '/git/commits/' + baseSha);
  const present = await api('GET', '/contents/' + proposed.path + '?ref=' + baseSha, undefined, true);
  if (present) throw new Error('This case already exists; the worker only adds new cases');
  const priorRef = await api('GET', '/git/ref/heads/' + encodeURIComponent(branch), undefined, true);
  if (priorRef) throw new Error('An incomplete prior proposal exists; reconcile it before a new attempt');
  const blob = await api('POST', '/git/blobs', { content: proposed.content, encoding: 'utf-8' });
  const tree = await api('POST', '/git/trees', { base_tree: baseCommit.tree.sha,
    tree: [{ path: proposed.path, mode: '100644', type: 'blob', sha: blob.sha }] });
  const commit = await api('POST', '/git/commits', { message: `feat(site): add ${proposed.marketCase.id}\n\nRefs #${issueNumber}`,
    tree: tree.sha, parents: [baseSha] });
  verifyChangedFiles(await api('GET', `/compare/${baseSha}...${commit.sha}`), proposed.path);
  await api('POST', '/git/refs', { ref: 'refs/heads/' + branch, sha: commit.sha });
  const pr = await api('POST', '/pulls', { title: `feat(site): ${proposed.marketCase.title}`, head: branch, base, draft: true,
    body: `Adds one validated, sourced illustrative market case.\n\nCloses #${issueNumber}\n\n` +
      `Scope: \`${proposed.path}\` only. Policy/base revision: \`${baseSha}\`.\n\n` +
      'The bounded content worker made **zero model calls**. This is deterministic content delivery, not LLM-generated code. ' +
      'Required tests and dependency review run explicitly because PR creation with GITHUB_TOKEN does not trigger ordinary PR workflows. ' +
      'The proposal remains a draft for maintainer review; the worker cannot merge or deploy it.' });
  // Explicit dispatches are permitted GITHUB_TOKEN events. Check runs attach to the proposed head SHA.
  await api('POST', '/actions/workflows/ci.yml/dispatches', { ref: branch });
  await api('POST', '/actions/workflows/dependency-review.yml/dispatches', { ref: branch,
    inputs: { base_ref: baseSha, head_ref: commit.sha } });
  await api('DELETE', `/issues/${issueNumber}/labels/${encodeURIComponent(policy.approved_label)}`);
  await api('POST', `/issues/${issueNumber}/labels`, { labels: ['agent:proposed'] });
  await api('POST', `/issues/${issueNumber}/comments`, { body: `Proposed ${pr.html_url}. Scope and source contracts passed; CI and dependency review have been dispatched. **0 model calls.** A maintainer must review, mark ready and merge after required checks. No feature is deployed merely because its ticket was opened.` });
  return { state: 'proposed', pull_request: pr.html_url, head_sha: commit.sha, changed_files: [proposed.path], model_calls: 0 };
}

async function main() {
  const repo = process.env.GITHUB_REPOSITORY;
  const issue = Number(process.env.ISSUE_NUMBER);
  const actor = process.env.GITHUB_ACTOR;
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo || '') || !Number.isSafeInteger(issue) || issue < 1
    || !/^[\w-]+$/.test(actor || '') || !process.env.GH_TOKEN) throw new Error('Missing trusted workflow context');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const policy = JSON.parse(execFileSync('python3', ['-c',
    'import json,yaml;from kit.profile import Loader;print(json.dumps(yaml.load(open(".kit/site-policy.yml"),Loader=Loader)))'],
    { cwd: root, encoding: 'utf8' }));
  const api = async (method, path, body, missingAllowed = false) => {
    if (!path.startsWith('/') && path !== '') throw new Error('Invalid repository API path');
    const response = await fetch(`https://api.github.com/repos/${repo}${path}`, { method, redirect: 'error',
      signal: AbortSignal.timeout(20000), headers: { Authorization: 'Bearer ' + process.env.GH_TOKEN,
        Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2026-03-10' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    if (missingAllowed && response.status === 404) return null;
    if (!response.ok) throw new Error(`Repository API operation failed (${response.status})`);
    return response.status === 204 ? {} : response.json();
  };
  api.owner = repo.split('/')[0];
  try {
    console.log(JSON.stringify(await deliver(api, issue, actor, policy), null, 2));
  } catch (error) {
    // A rejected proposal remains visible and never becomes an automatic retry/merge.
    await api('DELETE', `/issues/${issue}/labels/${encodeURIComponent(policy.approved_label)}`).catch(() => {});
    await api('POST', `/issues/${issue}/labels`, { labels: ['agent:blocked'] }).catch(() => {});
    console.error('Case worker stopped:', error.message);
    process.exitCode = 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
