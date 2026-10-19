"""Operator-only refresh of the bounded DeepSeek historical window; never run in CI."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
START = int(dt.datetime(2025, 1, 13, tzinfo=dt.timezone.utc).timestamp())
END = int(dt.datetime(2025, 2, 8, tzinfo=dt.timezone.utc).timestamp())
ASSETS = [('NVDA', 'NVIDIA', 'Chip supplier', '#365ee8'), ('AVGO', 'Broadcom', 'Chips and software', '#a96316'),
          ('MSFT', 'Microsoft', 'Diversified cloud company', '#187d78'), ('GOOGL', 'Alphabet', 'Diversified cloud company', '#8956ae'),
          ('SPY', 'SPDR S&P 500 ETF', 'Broad-market comparator', '#62718a')]

def fetch(asset):
    symbol, name, role, color = asset
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={START}&period2={END}&interval=1d'
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read()
    data = json.loads(raw)['chart']['result'][0]
    if data['meta']['currency'] != 'USD' or data['meta']['symbol'] != symbol:
        raise ValueError('Unexpected quote metadata')
    dates = [dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%d') for t in data['timestamp']]
    closes = data['indicators']['adjclose'][0]['adjclose']
    if len(dates) != len(closes) or any(value is None or value <= 0 for value in closes):
        raise ValueError('Missing historical prices; no synthetic fallback')
    return dates, dict(symbol=symbol, name=name, role=role, color=color, values=[round(v, 6) for v in closes],
                       source_url=url, response_sha256=hashlib.sha256(raw).hexdigest())

if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fetch, ASSETS))
    dates = results[0][0]
    if any(item[0] != dates for item in results):
        raise ValueError('Trading calendars must align')
    snapshot = dict(schema_version='1', id='deepseek-2025', case_id='open-model-release', currency='USD',
                    provider='Yahoo Finance', price_basis='Adjusted daily close', timezone='America/New_York',
                    retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat(), dates=dates,
                    series=[item[1] for item in results], events=[
                        dict(id='release', date='2025-01-20', label='R1 release', note='DeepSeek announced R1. US equity markets were closed; the next recorded session is 21 January.', url='https://deepseek.com/en/news/deepseek-r1/'),
                        dict(id='selloff', date='2025-01-27', label='27 Jan sell-off', note='Inspect the recorded price moves. The date label does not establish that DeepSeek caused every move.', url='https://www.bis.org/speeches/20250225-data-science-central-banking'),
                        dict(id='fed', date='2025-01-29', label='Fed decision', note='A separate macro event: the Fed held its target range. Microsoft also reported earnings after the close, affecting the next session.', url='https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm')])
    target = ROOT / 'site/market/deepseek-2025.json'
    target.write_text(json.dumps(snapshot, indent=2) + '\n')
    print(f'Saved {len(dates)} aligned sessions for {len(results)} assets to {target}')
