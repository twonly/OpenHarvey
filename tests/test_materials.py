import json
import unittest
from urllib.parse import quote

import test_workbench as fixtures
from contract_web import materials


class MaterialsTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace

    def enable(self, value=True):
        status=self.client.get('/api/settings/labs').json()
        return self.client.patch('/api/settings/labs',json={'materials_enabled':value,'revision':status['revision']},headers=self.headers)

    def upload(self,w,t,text='报价总额 120000 元。',name='报价.txt'):
        return self.client.post(f'/api/workspaces/{w["id"]}/attachments?thread_id={t["id"]}',content=text.encode(),headers={**self.headers,'X-Filename':quote(name)})

    def docs(self,w):
        return self.client.get(f'/api/workspaces/{w["id"]}/documents')

    def change(self,w,d,action):
        return self.client.patch(f'/api/workspaces/{w["id"]}/documents/{d}',json={'action':action},headers=self.headers)

    def test_labs_off_by_default_api_gated_and_personal(self):
        w,t=self.make_workspace()
        self.assertFalse(self.client.get('/api/settings/labs').json()['materials_enabled'])
        self.assertEqual(self.docs(w).status_code,403)
        self.assertEqual(self.upload(w,t).status_code,403)
        self.assertEqual(self.change(w,w['document_id'],'remove').status_code,403)
        old=self.client.get('/api/settings/labs').json()
        self.assertEqual(self.enable().status_code,200)
        self.assertEqual(self.client.patch('/api/settings/labs',json={'materials_enabled':False,'revision':old['revision']},headers=self.headers).status_code,409)
        prefs=self.client.get('/api/settings').json()
        self.assertEqual(self.client.put('/api/settings',json={'values':{},'revision':prefs['revision']},headers=self.headers).status_code,200)
        self.assertTrue(self.client.get('/api/settings/labs').json()['materials_enabled'])
        self.login('bob')
        self.assertFalse(self.client.get('/api/settings/labs').json()['materials_enabled'])
        self.assertEqual(self.docs(w).status_code,404)

    def test_local_scope_enable_disable_keeps_history_separate_from_next_task(self):
        w,t=self.make_workspace()
        a=self.client.post(f'/api/threads/{t["id"]}/attachments',content=b'legacy extra',headers={**self.headers,'X-Filename':'extra.txt'}).json()
        t2=self.client.post(f'/api/workspaces/{w["id"]}/threads',json={},headers=self.headers).json()
        url=f'/api/documents/{a["id"]}?thread_id={t2["id"]}'
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.enable().status_code,200)
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(len(self.docs(w).json()['documents']),2)
        self.assertEqual(self.enable(False).status_code,200)
        self.assertEqual(self.client.get(url).status_code,200)  # old citations stay navigable
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        self.assertEqual([d['id'] for d in materials.documents(self.store,u,t2)],[w['document_id']])
        snapshot=self.client.get('/api/threads/'+t2['id']).json()
        self.assertFalse(snapshot['materials_enabled'])
        self.assertTrue(next(d for d in snapshot['documents'] if d['id']==a['id'])['historical_only'])

    def test_remove_restore_preserves_source_and_rejects_new_quotes(self):
        self.enable();w,t=self.make_workspace();a=self.upload(w,t).json()
        self.assertEqual(self.change(w,a['id'],'remove').status_code,200)
        self.assertTrue((self.store.user_root(self.uid)/'sources'/a['id']/'source.txt').exists())
        source=self.client.get(f'/api/documents/{a["id"]}?thread_id={t["id"]}').json()
        self.assertTrue(source['removed_at'])
        context=json.loads((self.store.user_root(self.uid)/'threads'/t['id']/'context.json').read_text())
        self.assertEqual([d['id'] for d in context['documents']],[w['document_id']])
        bad=self.client.post(f'/api/threads/{t["id"]}/messages',json={'text':'看这段','quotes':[{'document_id':a['id'],'source_hash':a['source_hash'],'block_ids':['B0'],'text':'报价总额 120000 元。'}]},headers=self.headers)
        self.assertEqual(bad.status_code,422)
        self.assertEqual(self.change(w,w['document_id'],'remove').status_code,422)
        self.assertEqual(self.change(w,a['id'],'restore').status_code,200)
        context=json.loads((self.store.user_root(self.uid)/'threads'/t['id']/'context.json').read_text())
        self.assertEqual(len(context['documents']),2)

    def test_duplicate_retry_same_name_different_content_and_partial_failure(self):
        self.enable();w,t=self.make_workspace();a=self.upload(w,t).json()
        duplicate=self.upload(w,t).json()
        self.assertEqual(a['id'],duplicate['id']);self.assertTrue(duplicate['reused'])
        different=self.upload(w,t,'不同的报价 130000 元。').json()
        self.assertNotEqual(a['id'],different['id'])
        bad=self.upload(w,t,'not a docx','broken.docx')
        self.assertEqual(bad.status_code,422)
        self.assertEqual(len(self.docs(w).json()['documents']),3)
        self.assertEqual(self.upload(w,t,'补充说明','notes.txt').status_code,200)

    def test_other_space_and_account_sources_cannot_be_used_or_changed(self):
        self.enable();w,t=self.make_workspace();a=self.upload(w,t).json();w2,t2=self.make_workspace()
        self.assertEqual(self.upload(w,t2).status_code,404)
        self.assertEqual(self.change(w2,a['id'],'remove').status_code,404)
        self.assertEqual(self.client.get(f'/api/documents/{a["id"]}?thread_id={t2["id"]}').status_code,404)
        self.login('bob');self.enable()
        self.assertEqual(self.change(w,a['id'],'remove').status_code,404)
        self.assertEqual(self.client.get('/api/documents/'+a['id']).status_code,404)

    def test_busy_other_thread_blocks_materials_and_labs_changes(self):
        self.enable();w,t=self.make_workspace();a=self.upload(w,t).json()
        t2=self.client.post(f'/api/workspaces/{w["id"]}/threads',json={},headers=self.headers).json()
        fixtures.FakeRuntime.servers['http://alice']['sessions'][t2['session_id']]['status']={'type':'busy'}
        self.assertEqual(self.upload(w,t).status_code,409)
        self.assertEqual(self.change(w,a['id'],'remove').status_code,409)
        self.assertEqual(self.enable(False).status_code,409)
        self.assertIsNone(self.store.one('SELECT removed_at FROM documents WHERE id=?',(a['id'],))['removed_at'])

    def test_disabling_does_not_reactivate_removed_sources_or_destroy_legacy_deletes(self):
        self.enable();w,t=self.make_workspace();a=self.upload(w,t).json()
        self.enable(False)
        self.assertEqual(self.client.delete(f'/api/threads/{t["id"]}/attachments/{a["id"]}',headers=self.headers).status_code,200)
        self.assertTrue(self.store.one('SELECT removed_at FROM documents WHERE id=?',(a['id'],))['removed_at'])
        self.assertEqual(self.docs(w).status_code,403)
        self.enable()
        self.assertEqual(self.change(w,a['id'],'restore').status_code,200)
