import { validateCase, reachable } from './model.mjs';

const $ = selector => document.querySelector(selector);
const NS = 'http://www.w3.org/2000/svg';
let cases = [], active, selected, challenged = new Set();
function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}
function svg(tag, attrs, content) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (content !== undefined) node.textContent = content;
  return node;
}
function link(title, url, className) {
  const node = element('a', className, title);
  node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node;
}
function wrapLabel(text, width = 18) {
  const lines = []; let line = '';
  for (const word of text.split(' ')) {
    if (line && (line + ' ' + word).length > width) { lines.push(line); line = word; }
    else line = line ? line + ' ' + word : word;
  }
  if (line) lines.push(line);
  return lines;
}
const position = node => ({ x: 30 + node.column * 248, y: 32 + node.row * 169 });
function remember() {
  const hash = new URLSearchParams({ case: active.id, connection: selected });
  if (challenged.size) hash.set('without', [...challenged].join(','));
  history.replaceState(null, '', '#' + hash);
}
function activate(id, edgeId, removed = []) {
  active = cases.find(item => item.id === id) || cases[0];
  selected = active.edges.some(edge => edge.id === edgeId) ? edgeId : active.edges[0].id;
  challenged = new Set(removed.filter(id => active.edges.some(edge => edge.id === id)));
  for (const button of $('#cases').children) button.setAttribute('aria-pressed', button.dataset.case === active.id);
  $('#case-category').textContent = active.category;
  $('#case-title').textContent = active.title;
  $('#case-subtitle').textContent = active.subtitle;
  $('#case-summary').textContent = active.summary;
  render();
}
function render() {
  const network = $('#network'); network.replaceChildren();
  const defs = svg('defs', {});
  const marker = svg('marker', { id: 'arrow', markerWidth: 7, markerHeight: 7, refX: 6, refY: 3.5, orient: 'auto' });
  marker.append(svg('path', { d: 'M0 0 L7 3.5 L0 7', fill: '#9aafd3' })); defs.append(marker); network.append(defs);
  const nodes = new Map(active.nodes.map(node => [node.id, node]));
  const connected = reachable(active, challenged);
  active.edges.forEach((edge, index) => {
    const a = position(nodes.get(edge.from)), b = position(nodes.get(edge.to));
    const x1 = a.x + 190, y1 = a.y + 43, x2 = b.x - 5, y2 = b.y + 43;
    const middle = (x1 + x2) / 2;
    const d = `M ${x1} ${y1} C ${middle} ${y1},${middle} ${y2},${x2} ${y2}`;
    const current = selected === edge.id;
    const group = svg('g', { class: `edge-control${current ? ' selected' : ''}`, role: 'button', tabindex: 0,
      'aria-label': `Connection ${index + 1}: ${edge.label}`, 'aria-pressed': current, 'data-edge': edge.id });
    group.append(svg('title', {}, edge.label));
    group.append(svg('path', { d, class: `edge${current ? ' selected' : ''}${challenged.has(edge.id) ? ' challenged' : ''}`, 'marker-end': 'url(#arrow)' }));
    group.append(svg('path', { d, class: 'edge-hit' }));
    const cy = (y1 + y2) / 2;
    group.append(svg('circle', { cx: middle, cy, r: 11, class: 'edge-number-circle' }));
    group.append(svg('text', { x: middle, y: cy + 4, 'text-anchor': 'middle', class: 'edge-number-text' }, index + 1));
    const choose = () => { selected = edge.id; render(); };
    group.addEventListener('click', choose);
    group.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); choose(); $('#connection-picker').focus(); } });
    network.append(group);
  });
  active.nodes.forEach(node => {
    const { x, y } = position(node);
    const group = svg('g', { class: `node ${node.kind}${connected.has(node.id) ? '' : ' unreachable'}` });
    group.append(svg('title', {}, node.label + ': ' + node.detail));
    group.append(svg('rect', { x, y, width: 190, height: 90, rx: 10, class: 'node-box' }));
    const lines = wrapLabel(node.label);
    lines.forEach((line, index) => group.append(svg('text', { x: x + 15, y: y + 28 + index * 20, class: 'node-label' }, line)));
    wrapLabel(node.detail, 28).slice(0, 2).forEach((line, index) =>
      group.append(svg('text', { x: x + 15, y: y + 72 + index * 12, class: 'node-detail' }, line)));
    network.append(group);
  });
  const changed = challenged.size;
  $('#reachability').textContent = changed
    ? `${changed} connection${changed === 1 ? '' : 's'} challenged. ${connected.size} of ${active.nodes.length} nodes remain connected.`
    : `${active.nodes.length} connected nodes. ${active.edges.length} connections to investigate.`;
  $('#reset-links').hidden = !changed;
  renderEvidence(); remember();
}
function renderEvidence() {
  const panel = $('#evidence-content'); panel.replaceChildren();
  const edge = active.edges.find(item => item.id === selected);
  const index = active.edges.indexOf(edge);
  const label = element('p', 'connection-count', `Connection ${index + 1} of ${active.edges.length}`);
  panel.append(label, element('h3', '', edge.label), element('span', 'strength', edge.strength),
    element('p', 'evidence-copy', edge.explanation), element('p', 'caveat', edge.caveat));
  const sources = element('div', 'sources-block'); sources.append(element('h4', '', 'Source material'));
  edge.sources.forEach(id => {
    const source = active.sources.find(source => source.id === id);
    sources.append(link(source.title + ' ↗', source.url, 'source-link'));
  });
  panel.append(sources);
  const block = element('div', 'challenge-block');
  const button = element('button', 'challenge', challenged.has(edge.id) ? 'Restore this connection' : 'Challenge this connection');
  button.id = 'challenge-link'; button.setAttribute('aria-pressed', challenged.has(edge.id));
  button.append(element('span', '', challenged.has(edge.id) ? '+' : '−'));
  button.addEventListener('click', () => {
    if (challenged.has(edge.id)) challenged.delete(edge.id); else challenged.add(edge.id);
    render(); $('#challenge-link').focus();
  });
  block.append(button, element('p', 'challenge-note', 'Remove this link and see what remains connected. This tests the diagram, not a financial forecast.'));
  panel.append(block);
  const pickerLabel = element('label', 'connection-picker-label', 'Choose a connection');
  pickerLabel.htmlFor = 'connection-picker'; pickerLabel.className = 'sr-only';
  const picker = element('select', 'connection-picker'); picker.id = 'connection-picker';
  active.edges.forEach((item, index) => { const option = element('option', '', `${index + 1}. ${item.label}`); option.value = item.id; picker.append(option); });
  picker.value = selected;
  picker.addEventListener('change', () => { selected = picker.value; render(); $('#connection-picker').focus(); });
  panel.append(pickerLabel, picker);
}
function renderDelivery(data) {
  const list = $('#delivery-list'); list.replaceChildren();
  $('#automation-note').textContent = data.case_automation
    ? 'Approved case tickets use a bounded content worker with zero model calls. Code changes require engineering review. The LLM controller remains local-only.'
    : 'Automatic case proposals are disabled. Tickets still update this notebook; maintainers can prepare PRs manually. The LLM controller remains local-only.';
  if (!data.issues.length) list.append(element('p', 'empty-notebook', 'The notebook is open. Suggest the next market connection to investigate.'));
  for (const issue of data.issues.slice(0, 6)) {
    const row = element('div', 'delivery-row');
    const description = element('div');
    description.append(link(issue.title, issue.url, 'delivery-title'), element('div', 'delivery-id', `Issue #${issue.number}`));
    const labels = new Set(issue.labels);
    const status = issue.state === 'closed' ? ['Closed', 'shipped'] : labels.has('agent:blocked') ? ['Needs attention', 'blocked']
      : labels.has('agent:proposed') ? ['PR proposed', 'proposed'] : labels.has('agent:ready') ? ['Approved for worker', 'proposed'] : ['Open', ''];
    row.append(description, element('span', 'ticket-state ' + status[1], status[0])); list.append(row);
  }
  $('#build-receipt').textContent = `Release ${data.revision.slice(0, 7)} • Notebook refreshed ${new Date(data.generated_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`;
}
async function load() {
  try {
    const response = await fetch('./data/catalog.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error('Case catalog unavailable');
    const data = await response.json();
    cases = data.cases.map(validateCase);
    if (!cases.length) throw new Error('No cases available');
    $('#case-count').textContent = String(cases.length).padStart(2, '0');
    $('#cases').replaceChildren();
    cases.forEach(item => {
      const button = element('button', 'case-button'); button.dataset.case = item.id;
      button.append(element('span', 'case-tag', item.category), element('strong', '', item.title),
        element('span', 'case-meta', `${item.edges.length} connections · ${item.sources.length} sources`));
      button.addEventListener('click', () => activate(item.id)); $('#cases').append(button);
    });
    const hash = new URLSearchParams(location.hash.slice(1));
    activate(hash.get('case'), hash.get('connection'), (hash.get('without') || '').split(','));
    renderDelivery(data);
  } catch {
    $('#load-error').hidden = false; $('#case-title').textContent = 'Investigation unavailable';
    $('#delivery-list').replaceChildren(element('p', 'empty-notebook', 'The notebook could not be loaded. The GitHub issue tracker remains available.'));
  }
}
$('#reset-links').addEventListener('click', () => { challenged.clear(); render(); });
$('#reload').addEventListener('click', () => location.reload());
load();
