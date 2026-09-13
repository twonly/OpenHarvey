import hashlib
import json
import time
from pathlib import Path
import test_workbench as fixtures

SAMPLE=Path(__file__).resolve().parents[1]/'runtime/public-examples/sample-contract.txt'

class DemoEntryTests(fixtures.WorkbenchTests):
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
