import io
import json
import unittest
from unittest.mock import patch
from docx import Document
from tests import test_workbench as workbench


class RedlineLabsTests(unittest.TestCase):
    def setUp(self):
        self.base = workbench.WorkbenchTests(); self.base.setUp()
        self.addCleanup(self.base.tearDown)
        self.c, self.store = self.base.client, self.base.store
        self.url = '/api/settings/labs/redline'

    def toggle(self, enabled, revision=None):
        if revision is None: revision = self.c.get(self.url).json()['revision']
        return self.c.patch(self.url, json={'redline_enabled': enabled, 'revision': revision}, headers=self.base.headers)

    def test_personal_opt_in_persists_without_an_allowlist(self):
        self.assertFalse(self.c.get(self.url).json()['effective'])
        with patch.dict('os.environ', {'CW_REDLINE_USERS': ''}):
            self.assertTrue(self.toggle(True).json()['effective'])
        self.assertTrue(self.c.get('/api/me').json()['capabilities']['redline'])
        self.base.login('bob')
        self.assertFalse(self.c.get(self.url).json()['effective'])
        self.base.login('alice')
        self.assertTrue(self.c.get(self.url).json()['effective'])

    def test_shared_revision_conflicts_and_general_reset_preserves_both_labs(self):
        stale = self.c.get(self.url).json()['revision']
        self.assertEqual(self.c.patch('/api/settings/labs', json={'memory_enabled': True, 'revision': stale}, headers=self.base.headers).status_code, 200)
        self.assertEqual(self.toggle(True, stale).status_code, 409)
        self.assertEqual(self.toggle(True).status_code, 200)
        settings = self.c.get('/api/settings').json()
        response = self.c.put('/api/settings', json={'values': {}, 'revision': settings['revision']}, headers=self.base.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.c.get(self.url).json()['effective'])
        self.assertTrue(self.c.get('/api/settings/labs').json()['effective'])
        self.assertEqual(self.toggle(False).status_code, 200)
        self.assertTrue(self.c.get('/api/settings/labs').json()['effective'])

    def test_demo_disabled_and_expired_accounts_cannot_gain_access(self):
        with patch.dict('os.environ', {'CW_REDLINE_ENABLED': '0'}):
            self.assertFalse(self.c.get(self.url).json()['available'])
            self.assertEqual(self.toggle(True).status_code, 403)
        self.store.execute("UPDATE users SET account_kind='demo' WHERE id=?", (self.base.uid,))
        self.assertTrue(self.c.get(self.url).json()['requires_login'])
        self.assertEqual(self.toggle(True).status_code, 403)
        self.store.execute("UPDATE users SET account_kind='personal',expires_at=1 WHERE id=?", (self.base.uid,))
        self.assertEqual(self.c.get(self.url).status_code, 401)

    def test_disable_waits_for_editor_then_keeps_versions_for_reenable(self):
        self.toggle(True)
        doc = Document(); doc.add_paragraph('Payment is due in 30 days.'); buf = io.BytesIO(); doc.save(buf)
        workspace = self.c.post('/api/workspaces', content=buf.getvalue(), headers={**self.base.headers, 'X-Filename': 'labs.docx'}).json()
        thread = self.c.post('/api/workspaces/'+workspace['id']+'/threads', json={}, headers=self.base.headers).json()
        base = '/api/redline/'+workspace['document_id']; query = '?thread_id='+thread['id']
        version = self.c.get(base+query).json()['version']['id']
        self.c.post(base+'/lease'+query, json={'client_id':'labs-test'}, headers=self.base.headers).raise_for_status()
        self.assertEqual(self.toggle(False).status_code, 409)
        self.assertTrue(self.c.get(self.url).json()['effective'])
        self.c.post(base+'/lease'+query, json={'client_id':'labs-test','release':True}, headers=self.base.headers).raise_for_status()
        self.assertEqual(self.toggle(False).status_code, 200)
        self.assertEqual(self.c.get(base+query).status_code, 403)
        self.assertEqual(self.toggle(True).status_code, 200)
        self.assertEqual(self.c.get(base+query).json()['version']['id'], version)

    def test_invalid_fields_do_not_change_preferences(self):
        before = self.store.one('SELECT preferences FROM users WHERE id=?', (self.base.uid,))
        for payload in ({'redline_enabled': 'true', 'revision': 1}, {'redline_enabled': True, 'revision': True}, {'redline_enabled': True, 'revision': 1, 'user_id': 'bob'}):
            self.assertEqual(self.c.patch(self.url, json=payload, headers=self.base.headers).status_code, 422)
        self.assertEqual(self.store.one('SELECT preferences FROM users WHERE id=?', (self.base.uid,)), before)

    def test_legacy_allowlist_migrates_once_without_overriding_opt_out(self):
        from contract_web.redline import Redline
        self.store.execute("DELETE FROM settings_migrations WHERE name='redline-labs-opt-in'")
        with patch.dict('os.environ', {'CW_REDLINE_USERS': 'alice'}):
            Redline(self.store)
        self.assertTrue(self.c.get(self.url).json()['effective'])
        self.assertEqual(self.toggle(False).status_code, 200)
        with patch.dict('os.environ', {'CW_REDLINE_USERS': '*'}):
            Redline(self.store)
        self.assertFalse(self.c.get(self.url).json()['effective'])
        self.base.login('bob')
        self.assertFalse(self.c.get(self.url).json()['effective'])
