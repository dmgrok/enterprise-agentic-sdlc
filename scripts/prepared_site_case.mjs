import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseIssue, validateCase } from '../site/model.mjs';

const PREFIX = '<!-- market-detective:prepared-case:v1';
const digest = body => createHash('sha256').update(body).digest('hex');
export function prepareComment(issue, marketCase) {
  if (!Number.isSafeInteger(issue.number) || issue.number < 1 || typeof issue.body !== 'string'
    || !issue.body.trim() || issue.body.length > 18000) throw new Error('Invalid source request');
  validateCase(marketCase);
  return `${PREFIX} issue=${issue.number} sha256=${digest(issue.body)} -->\n` +
    'Prepared case for this request. Review the evidence and fit to the question before approving delivery.\n\n' +
    '```json\n' + JSON.stringify(marketCase, null, 2) + '\n```\n';
}
export function preparedBody(issue, comments) {
  // Historical machine-authored tickets remain compatible. The human form needs no JSON.
  if (/```json\s*\n/.test(issue.body || '')) return issue.body;
  if (!Array.isArray(comments) || comments.length >= 100) throw new Error('Cannot establish an unambiguous prepared case');
  const trusted = comments.filter(comment => comment.author_association === 'OWNER'
    && typeof comment.body === 'string' && comment.body.startsWith(PREFIX));
  const expected = `${PREFIX} issue=${issue.number} sha256=${digest(issue.body || '')} -->\n`;
  const matching = trusted.filter(comment => comment.body.startsWith(expected));
  if (matching.length > 1) throw new Error('Multiple prepared cases match this request; keep exactly one');
  if (!matching.length) {
    const error = new Error('This text request needs a researched case prepared by the local agent or maintainer. Reprepare after request edits.');
    error.code = 'CASE_PREPARATION_REQUIRED'; throw error;
  }
  parseIssue(matching[0].body);
  return matching[0].body;
}
// Local authoring helper: writes a reviewable comment to stdout; never posts or approves it.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [issuePath, casePath] = process.argv.slice(2);
  if (!issuePath || !casePath) throw new Error('Usage: node scripts/prepared_site_case.mjs ISSUE.json CASE.json');
  process.stdout.write(prepareComment(JSON.parse(readFileSync(issuePath, 'utf8')), JSON.parse(readFileSync(casePath, 'utf8'))));
}
