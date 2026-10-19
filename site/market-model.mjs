const allowed = new Set(['query1.finance.yahoo.com', 'deepseek.com', 'www.bis.org', 'www.federalreserve.gov']);
export function validateSnapshot(data) {
  const fail = () => { throw new Error('Invalid historical market snapshot'); };
  const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  const safeURL = value => { try { const u = new URL(value); return u.protocol === 'https:' && allowed.has(u.hostname) && !u.username && !u.password && !u.port; } catch { return false; } };
  if (data?.schema_version !== '1' || data.id !== 'deepseek-2025' || data.case_id !== 'open-model-release'
    || data.currency !== 'USD' || data.price_basis !== 'Adjusted daily close' || data.provider !== 'Yahoo Finance'
    || !Number.isFinite(Date.parse(data.retrieved_at)) || data.timezone !== 'America/New_York'
    || !Array.isArray(data.dates) || data.dates.length < 10 || data.dates.length > 50
    || data.dates.some((date, i) => !validDate(date) || (i && date <= data.dates[i - 1]))) fail();
  if (!Array.isArray(data.series) || data.series.length !== 5 || !Array.isArray(data.events) || data.events.length !== 3) fail();
  const symbols = new Set();
  for (const s of data.series) {
    if (!['NVDA', 'AVGO', 'MSFT', 'GOOGL', 'SPY'].includes(s.symbol) || symbols.has(s.symbol)
      || typeof s.name !== 'string' || s.name.length > 80 || typeof s.role !== 'string' || s.role.length > 80
      || !/^#[0-9a-f]{6}$/i.test(s.color) || !safeURL(s.source_url) || !/^[a-f0-9]{64}$/.test(s.response_sha256)
      || !Array.isArray(s.values) || s.values.length !== data.dates.length || s.values.some(n => !Number.isFinite(n) || n <= 0)) fail();
    symbols.add(s.symbol);
  }
  const events = new Set();
  for (const e of data.events) {
    if (!['release', 'selloff', 'fed'].includes(e.id) || events.has(e.id) || !validDate(e.date)
      || e.date <= data.dates[0] || e.date > data.dates.at(-1) || !safeURL(e.url)
      || typeof e.label !== 'string' || e.label.length > 60 || typeof e.note !== 'string' || e.note.length > 400) fail();
    events.add(e.id);
  }
  return data;
}
export function eventIndices(data, eventDate) {
  const first = data.dates.findIndex(date => date >= eventDate);
  if (first < 1) throw new Error('Event needs a recorded prior session');
  return { baseline: first - 1, first };
}
export const change = (current, baseline) => (current / baseline - 1) * 100;
export function chartValue(data, series, index, baseline, mode) {
  const own = change(series.values[index], series.values[baseline]);
  if (mode === 'relative') {
    const benchmark = data.series.find(s => s.symbol === 'SPY');
    return own - change(benchmark.values[index], benchmark.values[baseline]);
  }
  return 100 + own;
}
export function windowIndices(data, eventDate, window) {
  const { first } = eventIndices(data, eventDate);
  return window === 'full' ? [0, data.dates.length - 1] : [Math.max(0, first - 5), Math.min(data.dates.length - 1, first + 5)];
}
