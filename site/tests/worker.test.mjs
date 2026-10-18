import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { evaluateIssue, deliver, verifyChangedFiles } from '../../scripts/site_issue_worker.mjs';

const marketCase = JSON.parse(readFileSync(new URL('../cases/stablecoin-fracture.json', import.meta.url)));
const policy = { schema_version: '1', model_calls: 0, merge: 'human_review', allowed_path_prefix: 'site/cases/',
  maximum_changed_files: 1, maximum_case_bytes: 16000, maximum_open_worker_prs: 2, approved_label: 'agent:ready',
  case_label: 'site:case', allowed_author_associations: ['OWNER'], allowed_actor_permissions: ['admin', 'maintain', 'write'] };
const issue = () => ({ state: 'open', author_association: 'OWNER', labels: [{ name: 'site:case' }, { name: 'agent:ready' }],
  body: '### Case\n```json\n' + JSON.stringify(marketCase) + '\n```' });
test('public or unapproved tickets cannot acquire write authority', () => {
  assert.equal(evaluateIssue(issue(), 'admin', policy).path, 'site/cases/stablecoin-fracture.json');
  for (const mutation of [value => value.author_association = 'CONTRIBUTOR', value => value.labels.pop(),
    value => value.state = 'closed', value => value.pull_request = {}]) {
    const value = issue(); mutation(value); assert.throws(() => evaluateIssue(value, 'admin', policy));
  }
  assert.throws(() => evaluateIssue(issue(), 'read', policy));
  assert.throws(() => evaluateIssue(issue(), 'admin', { ...policy, maximum_changed_files: 2 }));
  assert.throws(() => evaluateIssue(issue(), 'admin', { ...policy, model_calls: 1 }));
});
test('the server-side comparison must prove one added case file', () => {
  verifyChangedFiles({ total_commits: 1, files: [{ filename: 'site/cases/new-case.json', status: 'added' }] }, 'site/cases/new-case.json');
  for (const files of [[], [{ filename: '.github/workflows/ci.yml', status: 'added' }],
    [{ filename: 'site/cases/new-case.json', status: 'modified' }]]) {
    assert.throws(() => verifyChangedFiles({ total_commits: 1, files }, 'site/cases/new-case.json'));
  }
});
function fakeApi({ prior = false, escape = false, consumed = false } = {}) {
  const calls = [];
  const api = async (method, path, body) => {
    calls.push({ method, path, body });
    if (method === 'GET' && path === '/issues/7') {
      const value = issue();
      if (consumed) value.labels = [{ name: 'site:case' }, { name: 'agent:proposed' }];
      return value;
    }
    if (path.includes('/permission')) return { permission: 'admin' };
    if (path.startsWith('/pulls?state=all')) return prior ? [{ html_url: 'https://github.com/example/project/pull/8' }] : [];
    if (path.startsWith('/pulls?state=open')) return [];
    if (path === '') return { default_branch: 'main' };
    if (path === '/git/ref/heads/main') return { object: { sha: 'a'.repeat(40) } };
    if (path === '/git/commits/' + 'a'.repeat(40)) return { tree: { sha: 'tree-base' } };
    if (method === 'GET' && (path.startsWith('/contents/') || path.startsWith('/git/ref/heads/'))) return null;
    if (path === '/git/blobs') return { sha: 'blob' };
    if (path === '/git/trees') return { sha: 'tree-proposal' };
    if (path === '/git/commits') return { sha: 'b'.repeat(40) };
    if (path.startsWith('/compare/')) return { total_commits: 1, files: [{ filename: escape ? '.github/workflows/ci.yml' : 'site/cases/stablecoin-fracture.json', status: 'added' }] };
    if (method === 'POST' && path === '/pulls') return { html_url: 'https://github.com/example/project/pull/8' };
    return {};
  };
  api.owner = 'example'; api.calls = calls; return api;
}
test('delivery opens a draft, dispatches both required checks and never merges', async () => {
  const api = fakeApi(); const result = await deliver(api, 7, 'maintainer', policy);
  assert.equal(result.model_calls, 0);
  assert.equal(api.calls.find(call => call.path === '/pulls' && call.method === 'POST').body.draft, true);
  assert.equal(api.calls.filter(call => call.path.endsWith('/dispatches')).length, 2);
  assert.equal(api.calls.some(call => /merge/.test(call.path)), false);
  assert.equal(api.calls.find(call => call.path === '/git/refs').body.ref, 'refs/heads/codex/market-case-7');
});
test('duplicate events do not create another commit or dispatch', async () => {
  const api = fakeApi({ prior: true }); assert.equal((await deliver(api, 7, 'maintainer', policy)).state, 'already-proposed');
  assert.equal(api.calls.some(call => call.method !== 'GET'), false);
});
test('queued duplicate events remain read-only after approval is consumed', async () => {
  const api = fakeApi({ prior: true, consumed: true });
  assert.equal((await deliver(api, 7, 'maintainer', policy)).state, 'already-proposed');
  assert.equal(api.calls.some(call => call.method !== 'GET'), false);
  await assert.rejects(deliver(fakeApi({ consumed: true }), 7, 'maintainer', policy));
});
test('an escaped diff is rejected before a branch or PR is published', async () => {
  const api = fakeApi({ escape: true }); await assert.rejects(deliver(api, 7, 'maintainer', policy));
  assert.equal(api.calls.some(call => call.path === '/git/refs' || (call.path === '/pulls' && call.method === 'POST')), false);
});
