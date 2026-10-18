"""Build private gateway settings from GitHub's authenticated native model catalog."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.settings import load


def configuration(model):
    if model.get('policy', {}).get('state') != 'enabled' or '/chat/completions' not in model.get('supported_endpoints', []):
        raise ValueError('Model must be enabled and support chat completions')
    prices = model['billing']['token_prices']
    if set(prices) != {'batch_size', 'default'} or prices['batch_size'] != 1000000:
        raise ValueError('Unsupported or unpriced billing tiers')
    rates = prices['default']
    inputs = [Decimal(str(rates[name])) for name in ('input_price', 'cache_read_price', 'cache_write_price')]
    output = Decimal(str(rates['output_price']))
    if any(not value.is_finite() or value < 0 for value in inputs + [output]) or max(inputs) <= 0 or output <= 0:
        raise ValueError('Missing or invalid certified token prices')
    limits = model['capabilities']['limits']
    context = limits['max_prompt_tokens']
    output_limit = min(limits['max_output_tokens'], limits.get('max_non_streaming_output_tokens', 2048), 2048)
    if type(context) is not int or type(output_limit) is not int or min(context, output_limit) < 1:
        raise ValueError('Invalid certified model limits')
    return {'provider': 'github-copilot', 'model': model['id'],
            'upstream': 'https://api.githubcopilot.com/chat/completions',
            'context_tokens': context, 'max_output_tokens': output_limit,
            'input_microusd_per_million': int((max(inputs) * 10000).to_integral_value(rounding=ROUND_CEILING)),
            'output_microusd_per_million': int((output * 10000).to_integral_value(rounding=ROUND_CEILING)),
            'catalog_model_sha256': hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest(),
            'catalog_verified_at': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    token = args.key_file.read_text().strip()
    if not token.startswith('github_pat_'):
        raise SystemExit('A fine-grained Copilot PAT is required')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = Request('https://api.githubcopilot.com/models', headers={
        'Authorization': 'Bearer ' + token, 'Copilot-Integration-Id': 'agentic-workflows',
        'X-GitHub-Api-Version': '2026-07-01', 'User-Agent': 'enterprise-agentic-sdlc-pilot'})
    with build_opener(NoRedirect).open(request, timeout=20) as response:
        data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise SystemExit('Model catalog too large')
        catalog = json.loads(data)
    selected = load(ROOT / '.kit/agent-policy.yml')['workflow']['model']
    matches = [model for model in catalog['data'] if model.get('id') == selected]
    if len(matches) != 1:
        raise SystemExit('Configured model missing or ambiguous')
    settings = configuration(matches[0])
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        json.dump(settings, out, indent=2)
    print('Verified GitHub Copilot gateway configuration written for', selected)


if __name__ == '__main__':
    main()
