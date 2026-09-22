import asyncio
from unittest.mock import AsyncMock,patch
import test_workbench as fixtures
from contract_web.model_settings import Models

class PersonalModelsTests(fixtures.WorkbenchTests):
    def body(self,**changes):
        return {'id':'same-provider','label':'我的服务','base_url':'https://example.com/v1','key':'ALICE_PRIVATE_CREDENTIAL','models':[{'id':'one','label':'模型一'}],**changes}
    def test_member_saves_and_same_provider_ids_are_isolated(self):
        manager=self.app.state.manager;models=self.app.state.models
        def operation(u,kind,target,action):return {'operation_id':'stub','status':'running'}
        with patch.object(manager,'operation',side_effect=operation):
            r=self.client.post('/api/providers',json=self.body(),headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
            self.assertNotIn('ALICE_PRIVATE_CREDENTIAL',r.text)
            self.login('bob');self.assertEqual(self.client.get('/api/providers').json()['providers'],[])
            r=self.client.post('/api/providers',json=self.body(label='Bob服务',key='BOB_PRIVATE_CREDENTIAL'),headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(self.client.get('/api/providers').json()['providers'][0]['label'],'Bob服务')
            self.login('alice');self.assertEqual(self.client.get('/api/providers').json()['providers'][0]['label'],'我的服务')
        a=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));b=self.store.one('SELECT * FROM users WHERE id=?',(self.bid,))
        self.assertEqual(models.connection(models.scope(a),self.body(key=None))[1],'ALICE_PRIVATE_CREDENTIAL')
        self.assertEqual(models.connection(models.scope(b),self.body(key=None))[1],'BOB_PRIVATE_CREDENTIAL')

    def test_apply_touches_only_owner_and_operation_is_private(self):
        models=self.app.state.models;manager=self.app.state.manager
        a=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));models.save(a,self.body())
        manager.state(self.bid,status='ready',applied_revision=7,desired_revision=7)
        with patch.object(manager,'probe',AsyncMock()),patch.object(manager,'ensure',AsyncMock(return_value={'applied_revision':1})) as ensure:
            result=asyncio.run(manager.apply_personal(a,1))
            self.assertTrue(result['applied']);self.assertEqual(ensure.call_count,1)
            self.assertEqual(ensure.call_args.args[0]['id'],self.uid)
        self.assertEqual(manager.instance(self.bid)['desired_revision'],7)
        self.store.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?)",('private-op',a['org_id'],a['id'],'models.apply','1','completed','{}',1,1))
        self.assertEqual(self.client.get('/api/operations/private-op').status_code,200)
        self.login('bob');self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.get('/api/operations/private-op').status_code,404)

    def test_existing_shared_registry_becomes_admin_private_once(self):
        models=self.app.state.models;a=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        models.save(a,self.body());scope=models.scope(a)
        self.store.execute("UPDATE providers SET org_id='default' WHERE org_id=?",(scope,))
        self.store.execute("UPDATE model_versions SET org_id='default',validated=1 WHERE org_id=?",(scope,))
        self.store.execute("DELETE FROM settings_migrations WHERE name='personal-models'")
        self.store.execute("UPDATE users SET username='admin',role='admin' WHERE id=?",(self.uid,))
        models.migrate_personal()
        b=self.store.one('SELECT * FROM users WHERE id=?',(self.bid,))
        self.assertIsNone(models.latest(models.scope(b)))
        self.assertEqual(models.latest(models.scope(a))['validated'],1)
        models.save(a,self.body(revision=1,key='NEW_PRIVATE_KEY'))
        self.assertIsNone(models.connection(models.scope(b),self.body(key=None))[1])
        new_id=self.store.add_user('charlie','password123')
        models.migrate_personal()
        self.assertEqual(models.public(models.scope({'id':new_id})),[])

    def test_protocol_parameters_persist_and_reach_native_config(self):
        models=self.app.state.models;u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        extra={'thinking':{'type':'enabled','budget_tokens':2048},'max_tokens':8192,'temperature':0.4}
        models.save(u,self.body(protocol='anthropic',base_url='https://api.anthropic.com',extra_body=extra))
        public=models.public(models.scope(u))[0]
        self.assertEqual(public['extra_body'],extra);self.assertEqual(public['protocol'],'anthropic')
        native,_=models.native(models.snapshot(models.scope(u)))
        provider=native['provider']['same-provider']
        self.assertEqual(provider['npm'],'@ai-sdk/anthropic')
        self.assertEqual(provider['options']['baseURL'],'https://api.anthropic.com/v1')
        self.assertEqual(provider['options']['workbenchExtraBody'],extra)
        models.save(u,self.body(revision=1,protocol='openai',extra_body={}))
        provider=models.native(models.snapshot(models.scope(u)))[0]['provider']['same-provider']
        self.assertEqual(provider['npm'],'@ai-sdk/openai-compatible')
        self.assertNotIn('workbenchExtraBody',provider['options'])

    def test_reject_invalid_protocol_and_request_parameters(self):
        models=self.app.state.models
        for change in [{'protocol':'invalid'},{'extra_body':[]},{'extra_body':None},{'extra_body':{'temperature':float('nan')}},{'extra_body':{'messages':[]}},{'extra_body':{'tools':[]}},{'extra_body':{'x':'x'*32001}}]:
            with self.subTest(change=str(change)[:80]),self.assertRaises(ValueError):models.validate(self.body(**change))

    def test_delete_is_private_revision_checked_and_last_snapshot_empty(self):
        models=self.app.state.models;u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        models.save(u,self.body());self.login('bob')
        with patch.object(self.app.state.manager,'operation',return_value={'operation_id':'stub'}):
            self.assertEqual(self.client.delete('/api/providers/same-provider?revision=1',headers=self.headers).status_code,404)
            self.login('alice')
            self.assertEqual(self.client.delete('/api/providers/same-provider?revision=0',headers=self.headers).status_code,409)
            response=self.client.delete('/api/providers/same-provider?revision=1',headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.client.delete('/api/providers/trial?revision=1',headers=self.headers).status_code,403)
        self.assertEqual(models.public(models.scope(u)),[])
        self.assertEqual(models.snapshot(models.scope(u)),[])
        self.assertEqual(models.allowed(models.scope(u)),set())
        self.assertEqual(models.native(models.snapshot(models.scope(u)))[0]['enabled_providers'],[])
        self.assertEqual(len(models.snapshot(models.scope(u),1)),1)


for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(PersonalModelsTests):setattr(PersonalModelsTests,_name,None)
