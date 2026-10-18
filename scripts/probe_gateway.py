"""One explicit, bounded native inference probe; retain its ledger for inspection."""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.control import Controller, policy_digest, signed
from kit.service import Application
from kit.settings import load


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--gateway-config', required=True, type=Path)
    parser.add_argument('--provider-key-file', required=True, type=Path)
    args = parser.parse_args()
    args.directory.mkdir(mode=0o700)
    key, token = secrets.token_bytes(32), secrets.token_urlsafe(32)
    gateway = json.loads(args.gateway_config.read_text())
    app = Application(args.directory / 'probe.sqlite', key,
                      [{'role': 'agent', 'run_id': 'LOCAL-PROBE', 'actor': 'agent',
                        'token_sha256': hashlib.sha256(token.encode()).hexdigest()}],
                      gateway, args.directory / 'staged',
                      provider_key=args.provider_key_file.read_text().strip())
    policy = load(ROOT / '.kit/agent-policy.yml')['runtime']
    policy.update(objective_id='gateway-connectivity-probe', mandatory_checks=['gateway-config'],
                  revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  max_spend_microusd=250000, warn_spend_microusd=200000)
    control = Controller(args.directory / 'probe.sqlite', key)
    try:
        control.create('LOCAL-PROBE', policy)
        event = {'run_id': 'LOCAL-PROBE', 'revision': policy['revision'], 'policy_digest': policy_digest(policy),
                 'sequence': 0, 'observed_at': time.time(),
                 'mission': {'objective_id': policy['objective_id'], 'scope_violation': False, 'progress': 'advancing'},
                 'quality': {'checks': {'gateway-config': 'pass'}, 'repair_attempts': 0},
                 'spend': {'accounting': 'reservation-ledger', 'coverage': 'complete'}}
        control.observe('LOCAL-PROBE', signed(event, key))
        control.command('LOCAL-PROBE', 'resume', 'operator', 'Explicit operator-authorized bounded connectivity probe')
        status, result, _ = app.handle('POST', '/v1/chat/completions', 'Bearer ' + token,
                                      {'model': gateway['model'], 'messages': [
                                          {'role': 'user', 'content': 'Reply with the single word READY.'}],
                                       'max_tokens': 32})
        state = control.status('LOCAL-PROBE')
        report = {'mode': 'live-copilot-gateway-probe', 'status': status, 'model': result['model'],
                  'reply': result['choices'][0]['message'].get('content'), 'usage': result['usage'],
                  'spent_microusd': state['spent_microusd'],
                  'all_reservations_settled': all(r['state'] == 'settled' for r in state['reservations'].values())}
        control.command('LOCAL-PROBE', 'stop', 'operator', 'Connectivity probe completed')
        (args.directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (args.directory / 'audit.json').write_text(json.dumps(control.audit('LOCAL-PROBE'), indent=2) + '\n')
        print(json.dumps(report, indent=2))
    finally:
        control.close()


if __name__ == '__main__':
    main()
