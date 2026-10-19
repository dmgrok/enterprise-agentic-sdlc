import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { prepareComment, preparedBody } from '../../scripts/prepared_site_case.mjs';
import { parseIssue } from '../model.mjs';
const value = JSON.parse(readFileSync(new URL('../cases/rate-surprise.json', import.meta.url)));
const request = { number: 8, body: '### Event\nA major open-source AI model is released.\n\n### Question\nDoes cheaper AI reduce chip demand, or expand adoption?' };
const comment = () => ({ author_association: 'OWNER', body: prepareComment(request, value) });
test('a text-only request can use a trusted, revision-bound prepared case', () => {
  assert.equal(parseIssue(preparedBody(request, [comment()])).id, value.id);
  assert.equal(request.body.includes('```'), false);
});
test('untrusted comments cannot supply the prepared case', () => {
  for (const author_association of ['NONE', 'CONTRIBUTOR', 'MEMBER']) {
    assert.throws(() => preparedBody(request, [{ ...comment(), author_association }]), { code: 'CASE_PREPARATION_REQUIRED' });
  }
});
test('editing the request invalidates its preparation; another ticket cannot reuse it', () => {
  assert.throws(() => preparedBody({ ...request, body: request.body + '\nNew requirement' }, [comment()]), { code: 'CASE_PREPARATION_REQUIRED' });
  assert.throws(() => preparedBody({ ...request, number: 9 }, [comment()]), { code: 'CASE_PREPARATION_REQUIRED' });
});
test('ambiguous preparation and invalid evidence fail closed', () => {
  assert.throws(() => preparedBody(request, [comment(), comment()]), /Multiple prepared/);
  assert.throws(() => preparedBody(request, Array.from({length:100}, comment)), /unambiguous/);
  const bad = structuredClone(value); bad.sources[0].url = 'https://example.com/claim';
  assert.throws(() => prepareComment(request, bad), /source origin/);
});
