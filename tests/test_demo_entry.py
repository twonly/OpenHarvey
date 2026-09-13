import hashlib
import json
import time
from pathlib import Path
import test_workbench as fixtures

SAMPLE=Path(__file__).resolve().parents[1]/'runtime/public-examples/sample-contract.txt'

class DemoEntryTests(fixtures.WorkbenchTests):
    def test_primary_source_reads_do_not_create_threads_or_spend_quota(self):
        user=self.app.state.accounts.create('demo')
        self.client.cookies.clear();self.client.cookies.set('contract_session',self.app.state.accounts.login(user))
        wid=self.client.post('/api/demo/workspace',json={},headers=self.headers).json()['workspace_id']
        self.store.execute('UPDATE users SET threads_created=3,trial_used=2 WHERE id=?',(user['id'],))
        before=self.app.state.accounts.usage(user)
        w=self.client.get('/api/workspaces/'+wid).json();docid=w['document_id']
        self.assertEqual(w['threads'],[])
        for path in ('','/file')+(('/pages/1',) if SAMPLE.suffix=='.pdf' else ()):
            response=self.client.get('/api/documents/'+docid+path)
            self.assertEqual(response.status_code,200,response.text[:100] if path!='' and response.status_code!=200 else '')
        self.assertEqual(self.app.state.accounts.usage(user),before)
        denied=self.client.post('/api/workspaces/'+wid+'/threads',json={},headers=self.headers)
        self.assertEqual(denied.status_code,403)
        self.assertIn('新建对话名额',denied.json()['detail'])
        self.assertIn('8 次模型请求',denied.json()['detail'])
        self.assertNotIn('体验额度已用完',denied.json()['detail'])
        self.login('bob')
        self.assertEqual(self.client.get('/api/documents/'+docid).status_code,404)
        self.assertEqual(self.client.get('/api/documents/'+docid+'/file').status_code,404)
        self.assertEqual(self.client.get('/api/documents/'+docid+'/pages/1').status_code,404)

    def test_attachment_cannot_bypass_thread_scope_by_omitting_thread_id(self):
        w,t=self.make_workspace()
        response=self.client.post('/api/threads/'+t['id']+'/attachments',content=b'Private attachment',headers={**self.headers,'X-Filename':'attachment.txt'})
        self.assertEqual(response.status_code,200,response.text)
        docid=response.json()['id']
        self.assertEqual(self.client.get('/api/documents/'+docid).status_code,404)
        self.assertEqual(self.client.get('/api/documents/'+docid+'/file').status_code,404)

    def test_sample_is_text_idempotent_private_and_free_to_open(self):
        user=self.app.state.accounts.create('demo')
        self.client.cookies.clear();self.client.cookies.set('contract_session',self.app.state.accounts.login(user))
        before=self.app.state.accounts.usage(user)
        first=self.client.post('/api/demo/workspace',json={},headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        wid=first.json()['workspace_id']
        second=self.client.post('/api/demo/workspace',json={},headers=self.headers)
        self.assertEqual(second.json()['workspace_id'],wid)
        w=self.client.get('/api/workspaces/'+wid).json()
        doc=self.store.one('SELECT * FROM documents WHERE id=?',(w['document_id'],))
        self.assertEqual(doc['filename'],SAMPLE.name)
        self.assertEqual(doc['source_hash'],hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
        mapped=json.loads((self.store.user_root(user['id'])/'sources'/doc['id']/'document.json').read_text())
        self.assertEqual(mapped['kind'],'text');self.assertTrue(mapped['segments'])
        self.assertIn('OpenHarvey 虚构采购服务合同',mapped['text'])
        self.assertEqual(self.app.state.accounts.usage(user),before)
        self.assertEqual(self.store.one('SELECT COUNT(*) AS n FROM workspaces WHERE user_id=?',(user['id'],))['n'],1)
        self.login('bob');self.assertEqual(self.client.get('/api/workspaces/'+wid).status_code,404)
        self.client.cookies.clear();self.assertEqual(self.client.post('/api/demo/workspace',json={},headers=self.headers).status_code,401)

    def test_old_public_execution_cannot_be_rebound_to_new_source(self):
        eid='old-example';folder=self.store.root/'public-examples'/eid;folder.mkdir(parents=True)
        (folder/'example.json').write_text(json.dumps({'documents':[{'id':'old','source_hash':'old-hash'}]}))
        self.store.execute('INSERT INTO public_examples VALUES(?,?,?,?,?,?)',(eid,'Old','u','w','t',time.time()))
        self.assertEqual(self.client.get('/api/demo/examples').json(),[])
        self.assertEqual(self.client.get('/api/demo/examples/'+eid).status_code,410)
        self.assertEqual(self.client.post('/api/demo/continue',json={'example_id':eid},headers=self.headers).status_code,410)

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(DemoEntryTests):setattr(DemoEntryTests,_name,None)
