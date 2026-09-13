import asyncio,json
import httpx
from unittest.mock import AsyncMock, patch
import test_workbench as fixtures
from contract_web.runtime import RuntimeError

class AdminTests(fixtures.WorkbenchTests):
    def admin(self):self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.uid,))
    def provider(self,**changes):
        return {'id':'custom','label':'自定义服务','base_url':'https://example.com/v1','models':[{'id':'model-one','label':'模型一','context':128000,'output':8192}],'key':'PRIVATE_PROVIDER_KEY_123456',**changes}

    def test_provider_encryption_versions_clear_and_permissions(self):
        self.assertEqual(self.client.get('/api/providers').status_code,200)
        self.admin();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));models=self.app.state.models
        saved=models.save(u,self.provider());self.assertEqual(saved['revision'],1)
        row=self.store.one("SELECT * FROM providers WHERE id='custom'")
        self.assertNotIn('PRIVATE_PROVIDER_KEY',row['secret'])
        self.assertEqual(models.decrypt(row['secret']),'PRIVATE_PROVIDER_KEY_123456')
        public=self.client.get('/api/providers');self.assertEqual(public.status_code,200,public.text);self.assertNotIn('PRIVATE_PROVIDER_KEY',public.text)
        self.assertTrue(public.json()['providers'][0]['key_configured'])
        self.assertTrue((self.root/'secrets/master.key').exists())
        with self.assertRaises(Exception):models.save(u,self.provider(revision=0))
        models.save(u,self.provider(revision=1,key=None,clear_key=True))
        self.assertIsNone(models.rows(models.scope(u))[0]['secret']);self.assertFalse(models.rows(models.scope(u))[0]['enabled'])
        self.assertEqual(models.allowed(models.scope(u)),set())
        self.login('bob');body=self.client.get('/api/providers').text
        self.assertNotIn('base_url',body);self.assertNotIn('key_configured',body)

    def test_platform_users_and_self_disable_guard(self):
        self.admin();users=self.client.get('/api/admin/users').json()
        self.assertTrue(any(u['id']==self.uid for u in users))
        self.assertEqual(self.client.patch('/api/admin/users/'+self.uid,json={'active':False},headers=self.headers).status_code,422)
        self.assertEqual(self.client.patch('/api/admin/users/'+self.bid,json={'role':'admin'},headers=self.headers).status_code,422)
        r=self.client.patch('/api/admin/users/'+self.bid,json={'add_requests':5,'active':False},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['trial']['total'],25)
        self.assertEqual(self.client.post('/api/login',json={'username':'bob','password':'bob-password-2026'},headers=self.headers).status_code,401)

    def test_legacy_member_creation_is_retired(self):
        self.admin()
        self.assertEqual(self.client.post('/api/admin/members',json={'username':'new','role':'admin'},headers=self.headers).status_code,404)
        self.login('bob');self.assertEqual(self.client.get('/api/admin/users').status_code,403)

    def test_failed_model_probe_preserves_previous_runtime_revision(self):
        self.admin();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));manager=self.app.state.manager;models=self.app.state.models
        models.save(u,self.provider());manager.state(self.uid,status='ready',desired_revision=1,applied_revision=1)
        models.save(u,self.provider(revision=1,key='new-invalid-key'))
        async def fail(rows):raise RuntimeError('认证失败')
        with patch.object(manager,'probe',side_effect=fail):
            with self.assertRaises(RuntimeError):asyncio.run(manager.apply_personal(u,2))
        state=manager.instance(self.uid)
        self.assertEqual(state['applied_revision'],1);self.assertEqual(state['desired_revision'],2);self.assertIn('认证失败',state['error'])

    def test_model_apply_waits_for_directory_scoped_execution_and_approvals(self):
        w,t=self.make_workspace();self.admin()
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));manager=self.app.state.manager;models=self.app.state.models
        models.save(u,self.provider());models.save(u,self.provider(revision=1))
        config={**self.store.runtime('alice'),'local':True}
        for pending in ('/session/status','/question','/permission'):
            with self.subTest(pending=pending):
                manager.state(self.uid,status='ready',applied_revision=1,desired_revision=2)
                async def native(method,path,*,tid=None,**kwargs):
                    if tid==t['id'] and path==pending:
                        return {t['session_id']:{'type':'busy'}} if path=='/session/status' else [{'sessionID':t['session_id']}]
                    return {} if path=='/session/status' else []
                with patch.object(manager,'config',AsyncMock(return_value=config)),patch.object(manager.driver,'health',AsyncMock(return_value=True)),patch.object(manager.driver,'stop',AsyncMock()) as stop,patch('contract_web.runtime_manager.Runtime.call',side_effect=native):
                    state=asyncio.run(manager.ensure(u,2))
                    stop.assert_not_called();self.assertEqual(state['applied_revision'],1);self.assertEqual(state['desired_revision'],2)

    def discover(self,body,handler):
        client=httpx.AsyncClient
        with patch('contract_web.model_settings.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.215.14',443))]),patch('contract_web.model_settings.httpx.AsyncClient',side_effect=lambda **kw:client(transport=httpx.MockTransport(handler),**kw)):
            return self.client.post('/api/providers/models',json=body,headers=self.headers)

    def test_native_permission_change_applies_without_model_revision_change(self):
        from contract_web.cli import runtime_config, ROOT
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        manager=self.app.state.manager;models=self.app.state.models
        models.save(u,self.provider())
        config={**self.store.runtime('alice'),'local':True}
        native=models.native(models.snapshot(models.scope(u),1))[0]
        installed={**runtime_config(ROOT/'runtime'),**native}
        self.assertEqual(installed['permission']['webfetch'],'allow')
        self.assertEqual(installed['permission']['websearch'],'allow')
        self.assertEqual(installed['permission']['task'],'deny')
        installed['permission']['websearch']='deny'
        folder=self.store.user_root(self.uid)/'opencode';folder.mkdir(exist_ok=True)
        (folder/'opencode.json').write_text(json.dumps(installed))
        manager.state(self.uid,status='ready',applied_revision=1,desired_revision=1)
        with patch.object(manager,'config',AsyncMock(return_value=config)), \
             patch.object(manager.driver,'health',AsyncMock(return_value=True)), \
             patch.object(manager,'busy',AsyncMock(return_value=False)), \
             patch.object(manager.driver,'stop',AsyncMock()) as stop, \
             patch.object(manager.driver,'start',AsyncMock(return_value=123)) as start, \
             patch.object(manager,'auth',AsyncMock()), \
             patch('contract_web.runtime_manager.Runtime.models',AsyncMock(return_value={'models':[{'id':'custom/model-one'}]})):
            asyncio.run(manager.ensure(u,1))
            stop.assert_awaited_once()
            self.assertEqual(start.call_args.args[2]['permission']['websearch'],'allow')

    def test_model_discovery_uses_saved_secret_without_requiring_models_or_saving(self):
        self.admin();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));models=self.app.state.models
        models.save(u,self.provider())
        def upstream(request):
            self.assertEqual(str(request.url),'https://example.com/v1/models')
            self.assertEqual(request.headers['authorization'],'Bearer PRIVATE_PROVIDER_KEY_123456')
            return httpx.Response(200,json={'data':[{'id':'z/model','secret':'HIDDEN'},{'id':'a/model'},{'id':'z/model'},{'id':'PRIVATE_PROVIDER_KEY_123456'},None]})
        response=self.discover({'id':'custom','base_url':'https://example.com/v1/'},upstream)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['models'],['a/model','z/model'])
        self.assertNotIn('HIDDEN',response.text);self.assertNotIn('PRIVATE',response.text)
        self.assertEqual(models.latest(models.scope(u))['revision'],1)

    def test_model_discovery_draft_key_and_permissions_and_organization_scope(self):
        body={'id':'custom','base_url':'https://example.com/v1','key':'DRAFT_KEY'}
        # Members can discover models without administrator privileges.
        def upstream(request):
            self.assertEqual(request.headers['authorization'],'Bearer DRAFT_KEY')
            return httpx.Response(200,json={'models':['second',{'model':'first'}]})
        r=self.discover(body,upstream);self.assertEqual(r.json()['models'],['first','second'])
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));self.app.state.models.save(u,self.provider())
        self.login('bob')
        def isolated(request):
            self.assertNotIn('authorization',request.headers)
            return httpx.Response(200,json=['public-model'])
        r=self.discover({k:v for k,v in body.items() if k!='key'},isolated);self.assertEqual(r.status_code,200,r.text)

    def test_model_discovery_errors_keep_credentials_hidden_and_allow_manual_entry(self):
        self.admin();body={'base_url':'https://example.com/v1','key':'DRAFT_KEY'}
        for status,payload,expected in [(401,{},'认证失败'),(404,{},'手动填写'),(200,{},'手动填写'),(502,{'error':'DRAFT_KEY'},'HTTP 502')]:
            with self.subTest(status=status):
                r=self.discover(body,lambda request:httpx.Response(status,json=payload))
                self.assertNotEqual(r.status_code,200);self.assertIn(expected,r.json()['detail']);self.assertNotIn('DRAFT_KEY',r.text)
        def timeout(request):raise httpx.ReadTimeout('DRAFT_KEY')
        r=self.discover(body,timeout);self.assertEqual(r.status_code,504);self.assertIn('超时',r.json()['detail'])

    def test_disabled_draft_model_can_be_tested_without_being_activated(self):
        self.admin();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));models=self.app.state.models;manager=self.app.state.manager
        body=self.provider(enabled=False);body['models'][0]['enabled']=False;models.save(u,body)
        with patch.object(manager,'operation',return_value={'operation_id':'test-op'}) as operation,patch.object(manager,'probe',AsyncMock(return_value={'message':'ok'})) as probe:
            r=self.client.post('/api/providers/test',json={**body,'key':None},headers=self.headers);self.assertEqual(r.status_code,200,r.text)
            asyncio.run(operation.call_args.args[3]())
            row=probe.call_args.args[0][0];self.assertTrue(row['enabled']);self.assertTrue(row['models'][0]['enabled'])
            self.assertEqual(models.decrypt(row['secret']),'PRIVATE_PROVIDER_KEY_123456')
        self.assertFalse(models.rows(models.scope(u))[0]['enabled']);self.assertEqual(models.latest(models.scope(u))['revision'],1)

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(AdminTests):setattr(AdminTests,_name,None)
