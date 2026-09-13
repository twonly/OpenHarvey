import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from contract_web.app import create_app


class PublicPageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = TestClient(create_app(data_dir=self.directory.name))
        self.addCleanup(self.client.close)

    def test_public_home_and_guide_preserve_private_workbench(self):
        for path in ('/', '/landing', '/landing/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('读懂每一份合同', response.text)
            self.assertIn('href="/spaces"', response.text)
        for path in ('/guide', '/guide/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('Skills：沉淀任务方法', response.text)
        self.assertIn('id="spacesApp"', self.client.get('/spaces').text)
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    @patch.dict(os.environ, {'CW_PUBLIC_ORIGIN': 'https://agent.tokrace.com',
                            'CW_ADDITIONAL_ORIGINS': 'https://web-production-991ee.up.railway.app'})
    def test_primary_and_explicit_legacy_origin_reach_authentication(self):
        for origin in ('https://agent.tokrace.com', 'https://web-production-991ee.up.railway.app'):
            response = self.client.post('/api/login', json={'username': 'unknown', 'password': 'invalid'},
                                        headers={'Origin': origin, 'X-Workbench-Request': '1', 'Sec-Fetch-Site': 'same-origin'})
            self.assertEqual(response.status_code, 401)

    @patch.dict(os.environ, {'CW_PUBLIC_ORIGIN': 'https://agent.tokrace.com',
                            'CW_ADDITIONAL_ORIGINS': 'https://web-production-991ee.up.railway.app'})
    def test_domain_migration_keeps_cross_site_and_request_marker_checks(self):
        for headers in (
            {'Origin': 'https://agent.tokrace.com.evil.example', 'X-Workbench-Request': '1'},
            {'Origin': 'https://evil.example', 'X-Workbench-Request': '1'},
            {'Origin': 'https://agent.tokrace.com', 'X-Workbench-Request': '1', 'Sec-Fetch-Site': 'cross-site'},
            {'Origin': 'https://agent.tokrace.com'},
        ):
            self.assertEqual(self.client.post('/api/login', json={}, headers=headers).status_code, 403)
