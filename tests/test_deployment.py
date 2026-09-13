import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from contract_web.store import Store

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('provision',ROOT/'scripts/provision.py')
provision=importlib.util.module_from_spec(spec);spec.loader.exec_module(provision)


class DeploymentTests(unittest.TestCase):
    def test_multiple_provider_keys_are_separate_env_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / 'data')
            store.add_user('alice', 'alice-password-2026')
            provider = {'model': 'glm/test', 'provider': {
                'glm': {'options': {'apiKey': '{env:CW_GLM_API_KEY}'}},
                'deepseek': {'options': {'apiKey': '{env:CW_DEEPSEEK_API_KEY}'}}}}
            file = provision.generate(store.root, root / 'generated', provider)
            compose = yaml.safe_load(file.read_text())
            env = compose['services']['agent-alice']['environment']
            self.assertEqual(set(env), {'CW_GLM_API_KEY', 'CW_DEEPSEEK_API_KEY'})
            self.assertNotIn('CW_GLM_API_KEY', compose['services']['web']['environment'])
            provider['provider']['glm']['options']['apiKey'] = 'literal-secret'
            with self.assertRaises(ValueError):
                provision.generate(store.root, root / 'generated', provider)

    def test_each_user_has_separate_network_and_mounts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=Store(root/'data')
            ids={name:s.add_user(name,name+'-password-2026') for name in ['alice','bob']}
            file=provision.generate(s.root,root/'generated',{'model':'company/test'})
            cfg=yaml.safe_load(file.read_text())
            self.assertEqual(cfg['services']['web']['environment']['CW_SANDBOX_BACKEND'],'local')
            a,b=cfg['services']['agent-alice'],cfg['services']['agent-bob']
            self.assertFalse(set(a['networks'])&set(b['networks']))
            self.assertNotIn('ports',a);self.assertNotIn('ports',b)
            self.assertTrue(any(v.endswith(':/sources:ro') for v in a['volumes']))
            self.assertFalse(any(ids['bob'] in v for v in a['volumes']))
            self.assertFalse(any('/published' in v or '/app.sqlite' in v for v in a['volumes']))
            self.assertTrue(a['read_only']);self.assertNotEqual(a['user'].split(':')[0],'0')
            before=json.loads((s.root/'runtimes.json').read_text())
            provision.generate(s.root,root/'generated',{'model':'company/test'})
            self.assertEqual(before,json.loads((s.root/'runtimes.json').read_text()))
