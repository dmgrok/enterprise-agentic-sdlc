"""Real Copilot CLI pilot with private loopback gateway, collector and supervision.

No public tunnel, GitHub workflow dispatch or GitHub writes. The model is hosted
by GitHub Copilot; agent execution and control remain on the operator's Mac.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.collector import collect
from kit.control import Controller, Denied, canonical, policy_digest, signed
from kit.gates import allowed_path
from kit.ghaw import inspect_governed
from kit.profile import read_frontmatter
from kit.service import APIError, Application, server
from kit.settings import load
from kit.supervisor import supervise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--gateway-config', required=True, type=Path)
    parser.add_argument('--provider-key-file', required=True, type=Path)
    parser.add_argument('--prior-spend-microusd', type=int, default=0)
    parser.add_argument('--repair-attempts', type=int, default=0)
    args = parser.parse_args()
    executable = shutil.which('copilot')
    if not executable:
        raise SystemExit('Install Copilot CLI first')
    settings = load(ROOT / '.kit/agent-policy.yml')
    gateway = json.loads(args.gateway_config.read_text())
    if gateway.get('provider') != 'github-copilot' or gateway['model'] != settings['workflow']['model']:
        raise Denied('Verified native gateway must match the approved model')
    if inspect_governed(read_frontmatter(ROOT / '.github/workflows/governed-intent.md')):
        raise Denied('Installed workflow profile failed')
    private = args.directory.resolve()
    private.mkdir(mode=0o700)
    workspace = private / 'agent-workspace'
    workspace.mkdir()
    (workspace / 'work').mkdir()
    agent_config = private / 'agent-config'
    agent_config.mkdir()
    run_id, work_item = 'LOCAL-PILOT', 'intent-LOCAL-PILOT'
    (workspace / 'work' / work_item).mkdir()
    policy = settings['runtime']
    if not 0 <= args.prior_spend_microusd < policy['max_spend_microusd']:
        raise Denied('Prior spend must leave a positive approved budget')
    if not 0 <= args.repair_attempts < policy['max_repair_attempts']:
        raise Denied('Repair ceiling reached')
    policy['max_spend_microusd'] -= args.prior_spend_microusd
    policy['warn_spend_microusd'] = min(policy['warn_spend_microusd'], policy['max_spend_microusd'] - 1)
    policy.update(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  work_item_id=work_item)
    key, token = secrets.token_bytes(32), secrets.token_urlsafe(32)
    for name, content in [('collector.key', key), ('policy.json', json.dumps(policy, indent=2).encode())]:
        with os.fdopen(os.open(private / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as out:
            out.write(content)
    database = private / 'controller.sqlite'
    app = Application(database, key, [{'role': 'agent', 'run_id': run_id, 'actor': 'agent',
                      'token_sha256': hashlib.sha256(token.encode()).hexdigest()}], gateway, private / 'staged',
                      provider_key=args.provider_key_file.read_text().strip())
    instance = server(app, port=0)
    service_thread = threading.Thread(target=instance.serve_forever, daemon=True)
    service_thread.start()
    control = Controller(database, key)
    control.create(run_id, policy)
    done, collector_errors = threading.Event(), []
    sequence = 0

    def readiness():
        nonlocal sequence
        files = [p for p in workspace.rglob('*') if p.is_file() or p.is_symlink()]
        scope = all(not p.is_symlink() and allowed_path(p.relative_to(workspace).as_posix(),
                                                     policy['allowed_paths']) for p in files)
        profile = not inspect_governed(read_frontmatter(ROOT / '.github/workflows/governed-intent.md'))
        event = {'run_id': run_id, 'revision': policy['revision'], 'policy_digest': policy_digest(policy),
                 'sequence': sequence, 'observed_at': time.time(),
                 'mission': {'objective_id': policy['objective_id'], 'scope_violation': not scope,
                             'progress': 'advancing'},
                 'quality': {'checks': {'workflow-profile': 'pass' if profile else 'fail'},
                             'repair_attempts': args.repair_attempts},
                 'spend': {'accounting': 'reservation-ledger', 'coverage': 'complete'}}
        sequence += 1
        return event

    control.observe(run_id, signed(readiness(), key))
    control.command(run_id, 'resume', 'operator', 'User authorized local-only native Copilot pilot')

    def collector():
        observer = Controller(database, key)
        try:
            while not done.wait(2):
                observer.observe(run_id, signed(readiness(), key))
        except Exception:
            collector_errors.append('Independent local collection failed')
            observer.command(run_id, 'pause', 'operator', collector_errors[-1])
        finally:
            observer.close()

    collector_thread = threading.Thread(target=collector, daemon=True)
    collector_thread.start()
    target = workspace / 'work' / work_item / 'intent.json'
    schema = json.loads((ROOT / 'schemas/intent.schema.json').read_text())
    prompt = ('Create exactly one JSON file at work/' + work_item + '/intent.json. '
              'Use the create tool. The file must satisfy this JSON Schema: ' + json.dumps(schema) + '\n'
              'Set work_item_id to ' + work_item + ', decision to proposed, risk_tier to unclassified. '
              'Brief: document configurable acceptance rules for an enterprise agent SDLC kit. '
              'New high/critical dependency vulnerabilities must block PR merging; low/moderate may proceed. '
              'Use owner "unassigned" and identify missing approvals as open questions. '
              'This is a proposal, do not claim approval or deployment. Do not create other files.\n'
              + settings['guidelines'])
    environment = {'COPILOT_HOME': str(agent_config), 'COPILOT_OFFLINE': 'true',
                   'COPILOT_PROVIDER_BASE_URL': f'http://127.0.0.1:{instance.server_port}/v1',
                   'COPILOT_PROVIDER_API_KEY': token, 'COPILOT_PROVIDER_TYPE': 'openai',
                   'COPILOT_MODEL': gateway['model'],
                   'COPILOT_PROVIDER_MAX_OUTPUT_TOKENS': str(gateway['max_output_tokens']),
                   'COPILOT_PROVIDER_MAX_PROMPT_TOKENS': str(gateway['context_tokens'])}
    command = [executable, '--no-auto-update', '--no-custom-instructions', '--disable-builtin-mcps',
               '--no-ask-user', '--no-color', '--disallow-temp-dir',
               '--available-tools=create', '--allow-tool', f'write({target})',
               '--deny-tool', 'shell', '--stream', 'off',
               '--log-dir', str(private / 'agent-logs'), '--secret-env-vars=COPILOT_PROVIDER_API_KEY',
               '-p', prompt]
    try:
        execution = supervise(control, run_id, command, workspace, environment=environment)
        done.set()
        collector_thread.join(timeout=5)
        if execution['exit_code'] != 0 or execution['interrupted']:
            raise Denied('Copilot process failed or was interrupted; inspect private controller audit')
        event = collect(workspace / 'work', policy, run_id, sequence, args.repair_attempts)
        event['quality']['checks']['workflow-profile'] = 'pass'
        control.observe(run_id, signed(event, key))
        quality = event['quality']
        if any(quality['checks'].get(name) != 'pass' for name in policy['output_mandatory_checks']):
            raise Denied('Actual artifact failed independent acceptance checks')
        artifact = json.loads(target.read_text())
        destination = private / 'staged' / (quality['artifact_digest'] + '.intent.json')
        _, staged = control.apply_output(run_id, policy['revision'],
            lambda: destination.write_bytes(canonical(artifact)),
            {'artifact_digest': quality['artifact_digest'], 'path': str(target.relative_to(workspace))})
        if not staged['applied']:
            raise Denied('Controller denied candidate staging')
        state = control.status(run_id)
        control.command(run_id, 'stop', 'operator', 'Local pilot complete; proposed artifact awaits human acceptance')
        stopped = False
        try:
            app.handle('POST', '/v1/chat/completions', 'Bearer ' + token,
                       {'model': gateway['model'], 'messages': [{'role': 'user', 'content': 'Try again'}]})
        except APIError as exc:
            stopped = exc.status == 409
        report = {'mode': 'live-local-copilot-cli-pilot', 'model': gateway['model'],
                  'exit_code': execution['exit_code'], 'independent_checks': quality['checks'],
                  'artifact_digest': quality['artifact_digest'], 'staged': staged['applied'],
                  'spent_microusd': state['spent_microusd'], 'model_calls': len(state['reservations']),
                  'prior_spend_microusd': args.prior_spend_microusd,
                  'total_spent_microusd': args.prior_spend_microusd + state['spent_microusd'],
                  'repair_attempts': args.repair_attempts,
                  'stop_denied_next_call': stopped, 'github_dispatches': 0, 'github_writes': 0,
                  'public_tunnel': False, 'human_acceptance': 'pending', 'collector_errors': collector_errors}
        (private / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
    finally:
        done.set()
        collector_thread.join(timeout=5)
        state = control.status(run_id)
        if state['state'] != 'stopped':
            control.command(run_id, 'stop', 'operator', 'Pilot process ended; no automatic restart')
        (private / 'audit.json').write_text(json.dumps(control.audit(run_id), indent=2) + '\n')
        control.close()
        instance.shutdown()
        instance.server_close()
        service_thread.join(timeout=5)


if __name__ == '__main__':
    main()
