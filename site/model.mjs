export const SOURCE_HOSTS = new Set(['www.bis.org', 'www.federalreserve.gov', 'www.sec.gov', 'www.investor.gov']);
const ID = /^[a-z][a-z0-9-]{1,47}$/;
const exact = (obj, fields) => obj && typeof obj === 'object' && !Array.isArray(obj)
  && Object.keys(obj).sort().join(',') === [...fields].sort().join(',');
function text(value, maximum = 240) {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= maximum
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f<>]/.test(value);
}
function fits(value, width) {
  let lines = 1, length = 0;
  for (const word of value.split(/\s+/)) {
    if (word.length > width) return false;
    if (length && length + word.length + 1 > width) { lines += 1; length = word.length; }
    else length += word.length + (length ? 1 : 0);
  }
  return lines <= 2;
}

export function validateCase(value) {
  const fail = message => { throw new Error(`Invalid market case: ${message}`); };
  if (!exact(value, ['schema_version', 'id', 'title', 'subtitle', 'summary', 'category', 'episode', 'nodes', 'edges', 'sources'])) fail('fields');
  if (value.schema_version !== '1' || !ID.test(value.id)) fail('version or identifier');
  if (!text(value.title, 72) || !text(value.subtitle, 120) || !text(value.summary, 650)) fail('copy');
  if (!['Macro', 'Digital assets', 'Market structure'].includes(value.category) || value.episode !== 'illustrative') fail('category or episode');
  if (!Array.isArray(value.nodes) || value.nodes.length < 3 || value.nodes.length > 9) fail('node count');
  if (!Array.isArray(value.edges) || value.edges.length < 2 || value.edges.length > 12) fail('edge count');
  if (!Array.isArray(value.sources) || value.sources.length < 1 || value.sources.length > 6) fail('source count');
  const sources = new Set();
  for (const source of value.sources) {
    if (!exact(source, ['id', 'title', 'url']) || !ID.test(source.id) || !text(source.title, 150) || sources.has(source.id)) fail('source fields');
    let url;
    if (typeof source.url !== 'string' || source.url.length > 500) fail('source URL');
    try { url = new URL(source.url); } catch { fail('source URL'); }
    if (url.protocol !== 'https:' || !SOURCE_HOSTS.has(url.hostname) || url.username || url.password || url.port) fail('source origin');
    sources.add(source.id);
  }
  const nodes = new Map();
  const positions = new Set();
  for (const node of value.nodes) {
    if (!exact(node, ['id', 'label', 'detail', 'kind', 'column', 'row']) || !ID.test(node.id) || nodes.has(node.id)
      || !text(node.label, 40) || !fits(node.label, 18) || !text(node.detail, 56) || !fits(node.detail, 28)
      || !['event', 'mechanism', 'asset'].includes(node.kind)
      || !Number.isInteger(node.column) || node.column < 0 || node.column > 3
      || !Number.isInteger(node.row) || node.row < 0 || node.row > 2) fail('node fields');
    const position = `${node.column}:${node.row}`;
    if (positions.has(position)) fail('overlapping nodes');
    positions.add(position); nodes.set(node.id, node);
  }
  const roots = value.nodes.filter(node => node.kind === 'event');
  if (roots.length !== 1 || roots[0].column !== 0) fail('one root event required');
  const edges = new Set();
  for (const edge of value.edges) {
    if (!exact(edge, ['id', 'from', 'to', 'label', 'explanation', 'caveat', 'strength', 'sources'])
      || !ID.test(edge.id) || edges.has(edge.id) || !nodes.has(edge.from) || !nodes.has(edge.to)
      || nodes.get(edge.from).column >= nodes.get(edge.to).column || nodes.get(edge.to).kind === 'event'
      || !text(edge.label, 52) || !text(edge.explanation, 650) || !text(edge.caveat, 400)
      || !['Documented mechanism', 'Context dependent'].includes(edge.strength)
      || !Array.isArray(edge.sources) || edge.sources.length < 1
      || edge.sources.some(id => !sources.has(id))) fail('connection or evidence');
    edges.add(edge.id);
  }
  if (reachable(value).size !== nodes.size) fail('disconnected case');
  return value;
}

export function reachable(marketCase, challenged = new Set()) {
  const root = marketCase.nodes.find(node => node.kind === 'event');
  const seen = new Set(root ? [root.id] : []);
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of marketCase.edges) {
      if (!challenged.has(edge.id) && seen.has(edge.from) && !seen.has(edge.to)) {
        seen.add(edge.to); changed = true;
      }
    }
  }
  return seen;
}

export function parseIssue(body) {
  if (typeof body !== 'string' || body.length > 18000) throw new Error('Issue body missing or too large');
  const matches = [...body.matchAll(/```json\s*\n([\s\S]*?)\n```/g)];
  if (matches.length !== 1) throw new Error('Provide exactly one fenced JSON market case');
  return validateCase(JSON.parse(matches[0][1]));
}
