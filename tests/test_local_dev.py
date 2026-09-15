import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.requests import Request
from contract_web.local_dev import bootstrap_session
from contract_web.store import Store


class LocalPreviewTests(unittest.TestCase):
    def test_bootstrap_response_sets_cookie_for_following_api_requests(self):
        from fastapi.testclient import TestClient
        from contract_web.app import create_app
        from test_workbench import FakeRuntime
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CW_LOCAL_DEV_USER': 'local-preview', 'CW_FEISHU_ENABLED': '1'}):
            app = create_app(folder, runtime_factory=FakeRuntime)
            client = TestClient(app, base_url='http://127.0.0.1:8842', client=('127.0.0.1',1234))
            self.assertEqual(client.get('/api/me').status_code, 200)
            self.assertTrue(client.cookies.get('contract_session'))
            self.assertEqual(client.get('/api/connectors/feishu').status_code, 200)
            client.close()

    def test_only_explicit_loopback_preview_bootstraps_a_persistent_account(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CW_LOCAL_DEV_USER': 'local-preview'}):
            store = Store(folder)
            def request(host='127.0.0.1', client='127.0.0.1', headers=()):
                return Request({'type': 'http', 'method': 'GET', 'path': '/api/me', 'scheme': 'http',
                                'query_string': b'', 'server': (host, 8842), 'client': (client, 1234), 'headers': [(b'host',host.encode()), *headers]})
            for r in (request(host='external.example'), request(client='192.168.1.2'), request(headers=[(b'sec-fetch-site',b'cross-site')]), request(headers=[(b'x-forwarded-for',b'127.0.0.1')])):
                bootstrap_session(r, store, 'contract_session')
                self.assertNotIn('contract_session', r.cookies)
            first = request()
            bootstrap_session(first, store, 'contract_session')
            u = store.authenticate(first.cookies['contract_session'])
            self.assertEqual(u['username'], 'local-preview')
            second = request()
            bootstrap_session(second, store, 'contract_session')
            self.assertEqual(store.authenticate(second.cookies['contract_session'])['id'], u['id'])
            with patch.dict(os.environ, {'CW_LOCAL_DEV_USER': ''}):
                r = request()
                bootstrap_session(r, store, 'contract_session')
                self.assertNotIn('contract_session', r.cookies)
