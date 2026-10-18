import copy
import json
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile
import yaml

from jsonschema import ValidationError
from kit.settings import load
from scripts.install_workflow import install
from scripts.observe_pilot import unpack_verified
from scripts.pilot_server import ingress
from scripts.configure_copilot_gateway import configuration

ROOT = Path(__file__).resolve().parents[1]


class SettingsTests(unittest.TestCase):
    def test_native_catalog_uses_worst_case_cache_price_and_rejects_unknown_tiers(self):
        model = {'id': 'synthetic-model', 'policy': {'state': 'enabled'},
                 'supported_endpoints': ['/chat/completions'],
                 'billing': {'token_prices': {'batch_size': 1000000, 'default': {
                     'input_price': 100, 'cache_read_price': 10, 'cache_write_price': 125, 'output_price': 500}}},
                 'capabilities': {'limits': {'max_prompt_tokens': 10000, 'max_output_tokens': 4096}}}
        result = configuration(model)
        self.assertEqual(1250000, result['input_microusd_per_million'])
        self.assertEqual(5000000, result['output_microusd_per_million'])
        self.assertEqual(2048, result['max_output_tokens'])
        model['billing']['token_prices']['long-context'] = {'input_price': 900}
        with self.assertRaises(ValueError):
            configuration(model)
    def test_checked_in_policy_loads(self):
        policy = load(ROOT / '.kit/agent-policy.yml')
        self.assertEqual(['scope', 'artifact-schema'], policy['runtime']['output_mandatory_checks'])

    def test_unknown_duplicate_and_invalid_rules_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'policy.yml'
            original = load(ROOT / '.kit/agent-policy.yml')
            for change in ('unknown', 'threshold', 'runtime'):
                data = copy.deepcopy(original)
                if change == 'unknown':
                    data['ignore_failures'] = True
                elif change == 'threshold':
                    data['runtime']['warn_spend_microusd'] = data['runtime']['max_spend_microusd']
                else:
                    data['runtime']['max_repair_attempts'] = 0
                target.write_text(yaml.safe_dump(data))
                with self.assertRaises((ValueError, ValidationError)):
                    load(target)
            target.write_text((ROOT / '.kit/agent-policy.yml').read_text() + '\nschema_version: "0.1"\n')
            with self.assertRaises(ValueError):
                load(target)

    def test_installation_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for file in ('workflows/governed-intent.md', 'workflows/governed-intent.lock.yml',
                         'resources/intent-template.json'):
                target = root / file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('fixture')
            install(root)
            install(root, check=True)
            (root / '.github/workflows/governed-intent.lock.yml').write_text('tampered')
            with self.assertRaises(ValueError):
                install(root, check=True)

    def test_verified_artifact_extraction_rejects_digest_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, symlink in [('intent-1/intent.json', False), ('../escape.json', False),
                                   ('/absolute.json', False), ('intent-1/intent.json', True)]:
                data = io.BytesIO()
                with zipfile.ZipFile(data, 'w') as archive:
                    entry = zipfile.ZipInfo(name)
                    if symlink:
                        entry.create_system = 3
                        entry.external_attr = 0o120777 << 16
                    archive.writestr(entry, '{}')
                raw = data.getvalue()
                metadata = {'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
                if name == 'intent-1/intent.json' and not symlink:
                    unpack_verified(raw, metadata, Path(directory))
                    self.assertTrue((Path(directory) / name).is_file())
                else:
                    with self.assertRaises(ValueError):
                        unpack_verified(raw, metadata, Path(directory))
                with self.assertRaises(ValueError):
                    unpack_verified(raw, {'digest': 'sha256:' + 'a' * 64}, Path(directory))

    def test_public_ingress_denies_anonymous_and_privileged_routes(self):
        token = 'synthetic-agent-token-' + 'x' * 32
        instance = ingress(0, 1, 'PILOT-1', token)
        worker = threading.Thread(target=instance.serve_forever)
        worker.start()
        base = f'http://127.0.0.1:{instance.server_port}'
        try:
            for path, credential, expected in [('/v1/chat/completions', None, 401),
                    ('/runs/PILOT-1/commands', token, 403), ('/runs/PILOT-1/telemetry', token, 403),
                    ('/runs/OTHER/admission', token, 403), ('/runs/PILOT-1/stage', token, 403)]:
                request = Request(base + path, data=b'{}', method='POST',
                                  headers={'Authorization': 'Bearer ' + credential} if credential else {})
                with self.assertRaises(HTTPError) as denied:
                    urlopen(request, timeout=3)
                self.assertEqual(expected, denied.exception.code)
                denied.exception.close()
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(timeout=5)
