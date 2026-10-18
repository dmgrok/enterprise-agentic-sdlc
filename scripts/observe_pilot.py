"""Bounded local pilot collector and watchdog, outside the GitHub agent job.

Readiness checks the installed workflow profile, not an artifact that does not
yet exist. Actual artifact scope/schema evidence is required separately for output.
Semantic acceptance remains a human decision. No automatic retry or resume.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.collector import collect
from kit.control import Controller, Denied, policy_digest, signed
from kit.ghaw import inspect_governed
from kit.profile import read_frontmatter
from kit.settings import load
from kit.supervisor import GitHubCancellation, watch_github


def github(method, url):
    result = subprocess.run(['gh', 'api', '--method', method, url], capture_output=True, timeout=20)
    if result.returncode:
        return 0, {}
    return (200 if method == 'GET' else 202), json.loads(result.stdout) if result.stdout else {}


def unpack_verified(archive, artifact, destination):
    if len(archive) > 2 * 1024 * 1024:
        raise ValueError('Artifact archive too large')
    if artifact.get('digest') != 'sha256:' + hashlib.sha256(archive).hexdigest():
        raise ValueError('GitHub artifact digest missing or mismatched')
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        entries = [entry for entry in package.infolist() if not entry.is_dir()]
        if len(entries) != 1 or entries[0].file_size > 1024 * 1024:
            raise ValueError('Expected one bounded intent file')
        entry = entries[0]
        path = PurePosixPath(entry.filename)
        if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                or stat.S_ISLNK(entry.external_attr >> 16)):
            raise ValueError('Unsafe artifact path')
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(package.read(entry))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--run', required=True)
    parser.add_argument('--github-run', required=True, type=int)
    parser.add_argument('--repository', default='dmgrok/enterprise-agentic-sdlc')
    args = parser.parse_args()
    folder = args.directory
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    policy = load(ROOT / '.kit/agent-policy.yml')['runtime']
    policy.update(revision=revision, work_item_id='intent-' + str(args.github_run),
                  github_target={'repository': args.repository, 'run_id': args.github_run, 'attempt': 1})
    key = (folder / 'collector.key').read_bytes()
    adapter = GitHubCancellation(args.repository, args.github_run, revision, 1, transport=github)
    run = adapter.status()
    if run.get('status') == 'completed' or run.get('event') != 'workflow_dispatch':
        raise Denied('Expected a newly dispatched live workflow')
    if inspect_governed(read_frontmatter(ROOT / '.github/workflows/governed-intent.md')):
        raise Denied('Installed workflow profile failed')
    (folder / 'policy.json').write_text(json.dumps(policy, indent=2))
    control = Controller(folder / 'controller.sqlite', key)
    control.create(args.run, policy)
    finished = threading.Event()
    errors = []

    def observation(sequence):
        # Verify platform binding every time, independently of the agent's claims.
        adapter.status()
        profile_ok = not inspect_governed(read_frontmatter(ROOT / '.github/workflows/governed-intent.md'))
        code, listing = github('GET', f'/repos/{args.repository}/actions/runs/{args.github_run}/artifacts')
        if code != 200:
            raise Denied('Artifact metadata unavailable')
        name = f'kit-intent-{args.github_run}-1'
        artifacts = [a for a in listing.get('artifacts', []) if a['name'] == name]
        if len(artifacts) > 1:
            raise Denied('Ambiguous artifact provenance')
        if artifacts:
            artifact = artifacts[0]
            provenance = artifact.get('workflow_run', {})
            if (artifact.get('expired') or provenance.get('id') != args.github_run
                    or provenance.get('head_sha') != revision):
                raise Denied('Artifact provenance mismatch')
            response = subprocess.run(['gh', 'api',
                f'/repos/{args.repository}/actions/artifacts/{artifact["id"]}/zip'],
                capture_output=True, timeout=20)
            if response.returncode:
                raise Denied('Artifact download failed')
            with tempfile.TemporaryDirectory(dir=folder) as temporary:
                unpack_verified(response.stdout, artifact, Path(temporary))
                event = collect(temporary, policy, args.run, sequence)
                event['quality']['checks']['workflow-profile'] = 'pass' if profile_ok else 'fail'
                return event
        return {'run_id': args.run, 'revision': revision, 'policy_digest': policy_digest(policy),
                'sequence': sequence, 'observed_at': time.time(),
                'mission': {'objective_id': policy['objective_id'], 'scope_violation': False, 'progress': 'advancing'},
                'quality': {'checks': {'workflow-profile': 'pass' if profile_ok else 'fail'}, 'repair_attempts': 0},
                'spend': {'accounting': 'reservation-ledger', 'coverage': 'complete'}}

    first = observation(0)
    control.observe(args.run, signed(first, key))
    control.command(args.run, 'resume', 'operator', 'User authorized local pilot; installed workflow profile verified')

    def collector():
        connection = Controller(folder / 'controller.sqlite', key)
        sequence = 1
        try:
            while not finished.wait(4):
                event = observation(sequence)
                sequence += 1
                connection.observe(args.run, signed(event, key))
                checks = event['quality']['checks']
                if 'artifact-schema' in checks and any(checks.get(name) != 'pass'
                        for name in policy.get('output_mandatory_checks', [])):
                    connection.command(args.run, 'pause', 'operator', 'Independent artifact check failed')
                    return
        except Exception:
            errors.append('Independent collection unavailable; run paused')
            connection.command(args.run, 'pause', 'operator', errors[-1])
        finally:
            connection.close()

    worker = threading.Thread(target=collector, daemon=True)
    worker.start()
    print('Run enrolled and readiness verified. Awaiting human GitHub Environment approval.', flush=True)
    try:
        result = watch_github(control, args.run, adapter, poll_seconds=2, execute=True)
    finally:
        finished.set()
        worker.join(timeout=25)
    state = control.status(args.run)
    report = {'github_run': args.github_run, 'revision': revision, 'state': state['state'],
              'reasons': state['reasons'], 'spent_microusd': state['spent_microusd'],
              'artifact_digest': state['axes'].get('quality', {}).get('artifact_digest'),
              'github': result, 'collector_errors': errors}
    (folder / 'pilot-result.json').write_text(json.dumps(report, indent=2) + '\n')
    (folder / 'audit.json').write_text(json.dumps(control.audit(args.run), indent=2) + '\n')
    control.close()
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
