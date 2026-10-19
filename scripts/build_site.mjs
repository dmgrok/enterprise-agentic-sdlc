import { mkdir, readFile, readdir, writeFile, copyFile, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';
import { validateCase } from '../site/model.mjs';
import { validateSnapshot } from '../site/market-model.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = join(root, '_site');
const repo = process.env.GITHUB_REPOSITORY || 'dmgrok/enterprise-agentic-sdlc';
if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) throw new Error('Invalid repository');
const paths = (await readdir(join(root, 'site/cases'))).filter(name => /^[a-z][a-z0-9-]+\.json$/.test(name)).sort();
if (paths.length < 1 || paths.length > 20) throw new Error('Expected one to twenty case files');
const cases = [];
for (const path of paths) {
  const value = validateCase(JSON.parse(await readFile(join(root, 'site/cases', path), 'utf8')));
  if (path !== value.id + '.json' || cases.some(item => item.id === value.id)) throw new Error('Case path/identifier mismatch');
  cases.push(value);
}
cases.sort((a, b) => a.id === 'stablecoin-fracture' ? -1 : b.id === 'stablecoin-fracture' ? 1 : a.title.localeCompare(b.title));
let issues = [];
if (process.argv.includes('--github')) {
  const headers = { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10' };
  if (process.env.GH_TOKEN) headers.Authorization = 'Bearer ' + process.env.GH_TOKEN;
  const response = await fetch(`https://api.github.com/repos/${repo}/issues?state=all&per_page=100&sort=updated&direction=desc`, { headers, redirect: 'error', signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error(`Issue notebook request failed (${response.status}); refuse a stale release`);
  const items = await response.json();
  issues = items.filter(item => !item.pull_request && item.labels.some(label => ['site:case', 'site:feature'].includes(label.name)))
    .slice(0, 12).map(item => ({ number: item.number, title: item.title.slice(0, 140), state: item.state,
      labels: item.labels.map(label => label.name), url: `https://github.com/${repo}/issues/${item.number}` }));
}
const revision = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
await rm(output, { recursive: true, force: true });
await mkdir(join(output, 'data'), { recursive: true });
const marketSnapshot = validateSnapshot(JSON.parse(await readFile(join(root, 'site/market/deepseek-2025.json'), 'utf8')));
await writeFile(join(output, 'data/deepseek-2025.json'), JSON.stringify(marketSnapshot, null, 2) + '\n');
const csv = [['Date', ...marketSnapshot.series.map(s => s.symbol + '_adjusted_close')].join(','),
  ...marketSnapshot.dates.map((date, i) => [date, ...marketSnapshot.series.map(s => s.values[i])].join(','))].join('\n') + '\n';
await writeFile(join(output, 'data/deepseek-2025.csv'), csv);
const assets = ['index.html', 'style.css', 'app.mjs', 'model.mjs', 'market-analysis.mjs', 'market-model.mjs', 'mark.svg'];
for (const file of assets) {
  if (file.endsWith('.mjs')) {
    const source = await readFile(join(root, 'site', file), 'utf8');
    await writeFile(join(output, file), source.replace(/(['"])(\.\/[a-z-]+\.mjs)\1/g, (_, quote, path) => quote + path + '?v=' + revision.slice(0, 12) + quote));
  } else if (file === 'index.html') {
    const source = await readFile(join(root, 'site', file), 'utf8');
    await writeFile(join(output, file), source.replace('./app.mjs', './app.mjs?v=' + revision.slice(0, 12)).replace('./style.css', './style.css?v=' + revision.slice(0, 12)));
  } else await copyFile(join(root, 'site', file), join(output, file));
}
await writeFile(join(output, '.nojekyll'), '');
await writeFile(join(output, 'data/catalog.json'), JSON.stringify({ schema_version: '1', revision,
  generated_at: new Date().toISOString(), case_automation: process.env.SITE_CASE_AUTOMATION === 'enabled', cases, issues }, null, 2) + '\n');
console.log(`Built Market Detective: ${cases.length} validated cases, ${issues.length} real tickets, revision ${revision.slice(0, 7)}`);
