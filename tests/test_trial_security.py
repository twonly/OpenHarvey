import asyncio,json,os,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch,AsyncMock
import httpx
from contract_web.store import digest
from contract_web.accounts import PUBLIC_RISK
import test_workbench as fixtures

class TrialSecurityTests(fixtures.WorkbenchTests):
    def setUp(self):super().setUp();self.accounts=self.app.state.accounts
    def use(self,u):
        self.client.cookies.clear();self.client.cookies.set('contract_session',self.accounts.login(u))
    def relay(self,handler,body,headers):
        cls=httpx.AsyncClient
        with patch.dict(os.environ,{'CW_TRIAL_MODEL_KEY':'SERVER_ONLY_SECRET','CW_TRIAL_MODEL_BASE_URL':'https://upstream.test/v1'}),patch('contract_web.trial_proxy.httpx.AsyncClient',side_effect=lambda **kw:cls(transport=httpx.MockTransport(handler),**kw)):
            return self.client.post('/trial-model/v1/chat/completions',json=body,headers=headers)
    def run_lease(self,t):
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));qid=self.app.state.queue.enqueue(u,t['id'],{'model':'trial/glm-5.3','text':'test','request_id':t['id']})
        with self.store.connect() as db:self.accounts.claim(db,qid)
        self.store.execute("UPDATE queued_messages SET status='submitted' WHERE id=?",(qid,));return qid
    def test_relay_requires_exact_owned_active_thread_and_never_returns_platform_key(self):
        w,t=self.make_workspace();qid=self.run_lease(t)
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('bounded-token'),self.uid,time.time()+60))
        body={'model':'glm-5.3','messages':[{'role':'user','content':'Hello'}],'max_tokens':1000000,'base_url':'https://evil.test'}
        headers={'Authorization':'Bearer bounded-token','X-Workbench-Thread':t['id']}
        calls=[]
        def upstream(r):
            calls.append(r);self.assertEqual(r.url.host,'upstream.test');self.assertEqual(r.headers['authorization'],'Bearer SERVER_ONLY_SECRET')
            self.assertEqual(json.loads(r.content)['max_tokens'],128000);self.assertNotIn('base_url',json.loads(r.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'OK'}}]})
        self.assertEqual(self.relay(upstream,body,{**headers,'X-Workbench-Thread':'other'}).status_code,429)
        self.assertEqual(self.relay(upstream,{**body,'model':'expensive'},headers).status_code,403)
        result=self.relay(upstream,body,headers);self.assertEqual(result.status_code,200,result.text);self.assertNotIn('SERVER_ONLY_SECRET',result.text)
        self.accounts.finish(qid,True);self.assertEqual(self.accounts.usage({'id':self.uid})['used'],1)
        self.assertEqual(self.relay(upstream,body,headers).status_code,429);self.assertEqual(len(calls),1)
        self.store.execute('UPDATE users SET active=0 WHERE id=?',(self.uid,));self.assertEqual(self.relay(upstream,body,headers).status_code,401)
    def test_two_conversations_charge_their_own_upstream_acceptance(self):
        w,a=self.make_workspace();b=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        qa=self.run_lease(a);qb=self.run_lease(b)
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('t'),self.uid,time.time()+60))
        r=self.relay(lambda r:httpx.Response(200,json={'choices':[]}),{'model':'glm-5.3','messages':[]},{'Authorization':'Bearer t','X-Workbench-Thread':b['id']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.store.one('SELECT model_accepted FROM trial_runs WHERE queue_id=?',(qa,))['model_accepted'],0)
        self.accounts.finish(qa,True);self.accounts.finish(qb,True)
        self.assertEqual(self.accounts.usage({'id':self.uid})['used'],1)

    def test_native_title_can_overlap_body_without_releasing_its_slot(self):
        _,t=self.make_workspace();qid=self.run_lease(t)
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('title-token'),self.uid,time.time()+60))
        self.store.execute('UPDATE trial_runs SET proxy_active=1 WHERE queue_id=?',(qid,))
        body={'model':'glm-5.3','messages':[]}
        headers={'Authorization':'Bearer title-token','X-Workbench-Thread':t['id']}
        def upstream(request):
            self.assertEqual(self.store.one('SELECT proxy_active FROM trial_runs WHERE queue_id=?',(qid,))['proxy_active'],2)
            return httpx.Response(200,json={'choices':[]})
        self.assertEqual(self.relay(upstream,body,headers).status_code,200)
        self.assertEqual(self.store.one('SELECT proxy_active FROM trial_runs WHERE queue_id=?',(qid,))['proxy_active'],1)
        self.store.execute('UPDATE trial_runs SET proxy_active=2 WHERE queue_id=?',(qid,))
        self.assertEqual(self.relay(upstream,body,headers).status_code,429)
        self.store.execute('UPDATE trial_runs SET proxy_active=1,proxy_calls=? WHERE queue_id=?',(self.accounts.limits()['proxy_calls'],qid))
        self.assertEqual(self.relay(upstream,body,headers).status_code,429)

    def test_upstream_connection_failure_refunds_once(self):
        _,t=self.make_workspace();qid=self.run_lease(t)
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('bounded-token'),self.uid,time.time()+60))
        def fail(request):raise httpx.ConnectError('unreachable',request=request)
        response=self.relay(fail,{'model':'glm-5.3','messages':[]},{'Authorization':'Bearer bounded-token','X-Workbench-Thread':t['id']})
        self.assertEqual(response.status_code,502)
        self.accounts.finish(qid,True);self.accounts.finish(qid,True)
        self.assertEqual(self.accounts.usage({'id':self.uid})['used'],0)
    def test_atomic_parallel_reservations_and_retry_do_not_overdraw(self):
        u=self.accounts.create('demo')
        def reserve(i):
            try:
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE');self.accounts.reserve(db,u,'parallel-'+str(i),{'model':'trial/glm-5.3'})
                return True
            except Exception:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(30)))
        self.assertEqual(sum(results),10);self.assertEqual(self.accounts.usage(u)['used'],10)

    def test_concurrent_duplicate_submission_returns_same_receipt(self):
        _,t=self.make_workspace();u=self.accounts.fresh({'id':self.uid})
        def submit(_):return self.app.state.queue.enqueue(u,t['id'],{'text':'same','model':'trial/glm-5.3','request_id':'stable-client-id'})
        with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(submit,range(20)))
        self.assertEqual(len(set(ids)),1);self.assertEqual(self.accounts.usage(u)['used'],1)

    def test_demo_start_cannot_extend_authenticated_personal_session(self):
        u=self.accounts.fresh({'id':self.uid});token=self.accounts.login(u,60)
        self.client.cookies.clear();self.client.cookies.set('contract_session',token)
        before=self.store.all('SELECT * FROM logins WHERE user_id=?',(u['id'],))
        response=self.client.post('/api/demo/start',json={},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertNotIn('set-cookie',response.headers)
        self.assertEqual(before,self.store.all('SELECT * FROM logins WHERE user_id=?',(u['id'],)))

    def test_long_running_native_survives_and_abandoned_probe_is_released(self):
        _,t=self.make_workspace();qid=self.run_lease(t);u=self.accounts.fresh({'id':self.uid})
        with self.store.connect() as db:
            self.accounts.reserve(db,u,'operation-stale',{'model':'own/test'});self.accounts.claim(db,'operation-stale')
            db.execute('UPDATE trial_runs SET started=?',(time.time()-601,))
        runtime=type('Runtime',(),{'call':AsyncMock()})()
        with patch.object(self.app.state.queue,'runtime',return_value=runtime):asyncio.run(self.accounts.maintain(self.app))
        runtime.call.assert_not_awaited()
        self.assertEqual(self.store.one('SELECT status FROM trial_runs WHERE queue_id=?',(qid,))['status'],'running')
        self.assertEqual(self.store.one('SELECT status FROM queued_messages WHERE id=?',(qid,))['status'],'submitted')
        self.assertEqual(self.store.one('SELECT status FROM trial_runs WHERE queue_id=?',('operation-stale',))['status'],'done')
        self.store.execute('UPDATE users SET active=0 WHERE id=?',(u['id'],))
        with patch.object(self.app.state.queue,'runtime',return_value=runtime):asyncio.run(self.accounts.maintain(self.app))
        runtime.call.assert_awaited_once_with('POST',f'/session/{t["session_id"]}/abort',tid=t['id'])

    def test_model_discovery_rejects_internal_addresses_and_pins_public_dns(self):
        models=self.app.state.models;cls=httpx.AsyncClient;requests=[]
        def upstream(request):requests.append(request);return httpx.Response(200,json=['safe-model'])
        async def check():
            loop=asyncio.get_running_loop()
            for address in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1']:
                with patch.object(loop,'getaddrinfo',AsyncMock(return_value=[(2,1,6,'',(address,443))])):
                    from fastapi import HTTPException
                    with self.assertRaises(HTTPException):await models.discover('user:'+self.uid,{'base_url':'https://provider.test/v1'},public_only=True)
            with patch.object(loop,'getaddrinfo',AsyncMock(return_value=[(2,1,6,'',('1.1.1.1',443))])):
                result=await models.discover('user:'+self.uid,{'base_url':'https://provider.test/v1'},public_only=True)
                self.assertEqual(result['models'],['safe-model'])
        with patch('contract_web.model_settings.httpx.AsyncClient',side_effect=lambda **kw:cls(transport=httpx.MockTransport(upstream),**kw)):asyncio.run(check())
        self.assertEqual(len(requests),1);request=requests[0]
        self.assertEqual(request.url.host,'1.1.1.1');self.assertEqual(request.headers['host'],'provider.test');self.assertEqual(request.extensions['sni_hostname'],'provider.test')
    def test_complete_auth_exchange_and_logout_flow_revocation(self):
        env={'CW_SUPABASE_URL':'https://auth.test','CW_SUPABASE_PUBLISHABLE_KEY':'public'};cls=httpx.AsyncClient
        identity={'id':'external-verified','email':'own@example.test','email_confirmed_at':'now','user_metadata':{'role':'admin'}}
        def provider(r):
            if r.url.path.endswith('/token'):
                self.assertIn('code_verifier',json.loads(r.content));return httpx.Response(200,json={'access_token':'supabase-user-token'})
            return httpx.Response(200,json=identity)
        with patch.dict(os.environ,env),patch('contract_web.auth_api.httpx.AsyncClient',side_effect=lambda **kw:cls(transport=httpx.MockTransport(provider),**kw)):
            self.client.post('/api/auth/start',json={'provider':'google'},headers=self.headers)
            from urllib.parse import urlparse,parse_qs
            response=self.client.post('/api/auth/start',json={'provider':'github'},headers=self.headers)
            state=parse_qs(urlparse(parse_qs(urlparse(response.json()['auth_url']).query)['redirect_to'][0]).query)['flow'][0]
            result=self.client.post('/api/auth/exchange',json={'flow':state,'code':'valid'},headers=self.headers)
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['user']['role'],'member')
            self.assertEqual(self.client.post('/api/auth/exchange',json={'flow':state,'code':'valid'},headers=self.headers).status_code,400)
            self.client.get('/orca/connect-url');self.client.post('/api/logout',json={},headers=self.headers)
            self.assertEqual(self.client.get('/api/me').status_code,401)
            self.assertFalse(self.store.one("SELECT 1 FROM auth_flows WHERE kind='orca'"))

    def test_oauth_callback_stays_on_the_browser_origin(self):
        from urllib.parse import urlparse,parse_qs
        with patch.dict(os.environ,{'CW_SUPABASE_URL':'https://auth.test','CW_SUPABASE_PUBLISHABLE_KEY':'public','CW_PUBLIC_ORIGIN':'https://railway.test','CW_ADDITIONAL_ORIGINS':'https://agent.test'}):
            response=self.client.post('/api/auth/start',json={'provider':'google'},headers=self.headers|{'Origin':'https://agent.test'})
            self.assertEqual(response.status_code,200,response.text)
            callback=parse_qs(urlparse(response.json()['auth_url']).query)['redirect_to'][0]
            self.assertTrue(callback.startswith('https://agent.test/auth/callback?flow='))
            self.assertEqual(self.client.post('/api/auth/start',json={'provider':'google'},headers=self.headers|{'Origin':'https://evil.test'}).status_code,403)

    def test_email_password_signup_upgrades_demo_without_otp(self):
        demo=self.accounts.create('demo');self.use(demo);self.store.execute('UPDATE users SET trial_used=3 WHERE id=?',(demo['id'],))
        cls=httpx.AsyncClient;calls=[]
        def provider(r):
            calls.append(r.url.path)
            if r.url.path.endswith('/signup'):
                self.assertEqual(json.loads(r.content),{'email':'new@example.test','password':'test-password-123'})
                return httpx.Response(200,json={'access_token':'authenticated-token','expires_in':3600})
            return httpx.Response(200,json={'id':'external-new','email':'new@example.test','email_confirmed_at':'auto-confirmed-by-supabase'})
        with patch.dict(os.environ,{'CW_SUPABASE_URL':'https://auth.test','CW_SUPABASE_PUBLISHABLE_KEY':'public'}),patch('contract_web.auth_api.httpx.AsyncClient',side_effect=lambda **kw:cls(transport=httpx.MockTransport(provider),**kw)):
            r=self.client.post('/api/auth/email',json={'email':'new@example.test','password':'test-password-123','action':'signup','role':'admin'},headers=self.headers)
            self.assertEqual(r.status_code,200,r.text);u=r.json()['user']
            self.assertEqual((u['id'],u['role'],u['account_kind']),(demo['id'],'member','personal'));self.assertEqual(u['trial']['remaining'],17)
        self.assertEqual(calls,['/auth/v1/signup','/auth/v1/user'])
        self.assertEqual(self.client.post('/api/auth/verify',json={},headers=self.headers).status_code,404)
    def test_demo_expiration_erases_files_and_credentials_idempotently(self):
        u=self.accounts.create('demo');root=self.store.user_root(u['id']);root.mkdir(exist_ok=True);(root/'temporary.txt').write_text('private demo data')
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('expired'),u['id'],time.time()+60))
        self.accounts.login(u);self.store.execute('UPDATE users SET expires_at=? WHERE id=?',(time.time()-1,u['id']))
        asyncio.run(self.accounts.maintain(self.app));asyncio.run(self.accounts.maintain(self.app))
        self.assertFalse(root.exists());self.assertFalse(self.store.one('SELECT 1 FROM trial_tokens WHERE user_id=?',(u['id'],)))
        self.assertFalse(self.store.one('SELECT 1 FROM logins WHERE user_id=?',(u['id'],)));self.assertIsNotNone(self.accounts.fresh(u)['cleaned_at'])
    def test_public_skill_package_excludes_company_reference_files(self):
        from contract_web.settings import Settings
        settings=Settings(self.store,Path(__file__).resolve().parents[1]/'runtime/skills');self.app.state.e2b.settings=settings
        u=self.accounts.create('demo');_,items,files=self.app.state.e2b.skill_sync.desired(u)
        self.assertEqual({i['name'] for i in items if i['scope']=='builtin'},{'contract-summary','contract-review','contract-redline'})
        self.assertFalse(any('contract-change-risk' in p for p in files))
        self.assertNotIn('华为','\n'.join(v.decode() if isinstance(v,bytes) else v for v in files.values()))

    def test_demo_browser_claim_two_visitors_and_upload_lifetime_limits(self):
        self.app.state.e2b.enabled=True
        env={'CW_TRIAL_MODEL_KEY':'SERVER_SECRET','CW_PUBLIC_ORIGIN':'https://workbench.test'}
        with patch.dict(os.environ,env):
            self.client.cookies.clear()
            a=self.client.post('/api/demo/start',json={},headers=self.headers);self.assertEqual(a.status_code,200,a.text);uid=a.json()['user']['id']
            self.client.post('/api/logout',json={},headers=self.headers)
            again=self.client.post('/api/demo/start',json={},headers=self.headers);self.assertEqual(again.json()['user']['id'],uid)
            work=[]
            for i in range(2):
                r=self.client.post('/api/workspaces',content=b'Private contract content.',headers=self.headers|{'X-Filename':'private.txt'});self.assertEqual(r.status_code,200,r.text);work.append(r.json())
            r=self.client.post('/api/workspaces',content=b'Extra',headers=self.headers|{'X-Filename':'extra.txt'});self.assertEqual(r.status_code,403,r.text)
            threads=[]
            for i in range(3):
                r=self.client.post('/api/workspaces/'+work[0]['id']+'/threads',json={},headers=self.headers);self.assertEqual(r.status_code,200,r.text);threads.append(r.json()['id'])
            self.assertEqual(self.client.post('/api/workspaces/'+work[0]['id']+'/threads',json={},headers=self.headers).status_code,403)
            self.client.cookies.clear();b=self.client.post('/api/demo/start',json={},headers=self.headers).json()['user'];self.assertNotEqual(b['id'],uid)
            self.assertEqual(self.client.get('/api/workspaces/'+work[0]['id']).status_code,404)
            self.assertEqual(self.client.get('/api/threads/'+threads[0]).status_code,404)
            self.assertEqual(self.client.get('/api/documents/'+work[0]['document_id'],params={'thread_id':threads[0]}).status_code,404)
            auser=self.store.one('SELECT * FROM users WHERE id=?',(uid,));self.store.execute('UPDATE users SET expires_at=? WHERE id=?',(time.time()-1,uid))
            asyncio.run(self.accounts.maintain(self.app))
            self.assertFalse(self.store.one('SELECT 1 FROM documents WHERE user_id=?',(uid,)))
            self.assertFalse(self.store.user_root(uid).exists())
            self.assertTrue(self.accounts.fresh(b)['active'])

    def test_public_gallery_is_immutable_and_does_not_start_runtime(self):
        self.client.cookies.clear()
        with patch.object(self.app.state.e2b,'prepare',side_effect=AssertionError('public views must not start a VM')):
            # Retired synthetic executions are not re-seeded for the new PDF.
            self.assertEqual(self.client.get('/api/demo/examples').json(),[])
            self.assertEqual(self.client.get('/api/demo/examples/missing').status_code,404)
            self.assertEqual(self.client.get('/api/demo/examples/missing/artifacts/another-user').status_code,404)
            self.assertEqual(self.client.get('/api/demo/examples/missing/source/another-user').status_code,404)
        self.assertFalse(self.store.all('SELECT * FROM trial_runs'))
        self.assertFalse(self.store.all('SELECT * FROM e2b_bindings'))


    def test_deepseek_connection_and_shared_allowance(self):
        _,t=self.make_workspace();qid=self.run_lease(t)
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('ds-token'),self.uid,time.time()+60))
        calls=[]
        def upstream(r):
            calls.append(r)
            self.assertEqual(str(r.url),'https://api.deepseek.com/chat/completions')
            self.assertEqual(r.headers['authorization'],'Bearer DEEPSEEK_SERVER_ONLY')
            self.assertEqual(json.loads(r.content)['model'],'deepseek-flash')
            return httpx.Response(200,json={'choices':[]})
        with patch.dict(os.environ,{'CW_TRIAL_DEEPSEEK_KEY':'DEEPSEEK_SERVER_ONLY','CW_TRIAL_DEEPSEEK_BASE_URL':'https://api.deepseek.com'}):
            result=self.relay(upstream,{'model':'deepseek-flash','messages':[]},{'Authorization':'Bearer ds-token','X-Workbench-Thread':t['id']})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(calls),1)
        self.accounts.finish(qid)
        u=self.accounts.create('demo')
        for i in range(10):
            with self.store.connect() as db:
                self.accounts.reserve(db,u,'mixed-'+str(i),{'model':'trial/'+('glm-5.3' if i%2 else 'deepseek-flash')})
        self.assertEqual(self.accounts.usage(u)['remaining'],0)
        from fastapi import HTTPException
        for model in ['glm-5.3','deepseek-flash']:
            with self.assertRaises(HTTPException):
                with self.store.connect() as db:self.accounts.reserve(db,u,'extra-'+model,{'model':'trial/'+model})

    def test_existing_demo_catalog_refresh_preserves_token_and_usage(self):
        u=self.accounts.create('demo');models=self.app.state.models;scope=models.scope(u)
        with patch.dict(os.environ,{'CW_TRIAL_MODEL_KEY':'GLM_SERVER_ONLY','CW_TRIAL_MODEL':'glm-5.3','CW_PUBLIC_ORIGIN':'https://workbench.test','CW_TRIAL_DEEPSEEK_KEY':''}):
            self.app.state.ensure_trial(u)
            old=models.rows(scope)[0]
            self.store.execute('UPDATE users SET trial_used=3 WHERE id=?',(u['id'],))
            with patch.dict(os.environ,{'CW_TRIAL_DEEPSEEK_KEY':'DEEPSEEK_SERVER_ONLY'}):
                self.app.state.ensure_trial(u)
                updated=models.rows(scope)[0]
                self.assertEqual([m['label'] for m in updated['models']],['GLM-5.3-flash','deepseek-flash'])
                self.assertEqual(updated['secret'],old['secret'])
                self.assertEqual(self.accounts.usage(u)['used'],3)
                self.app.state.ensure_trial(u)
                self.assertEqual(models.rows(scope)[0]['revision'],updated['revision'])
                public=json.dumps(models.public(scope))
                self.assertNotIn('DEEPSEEK_SERVER_ONLY',public)
                self.assertNotIn('GLM_SERVER_ONLY',public)

    def test_model_budgets_and_old_long_run_relay(self):
        from contract_web.trial_models import public_trial_models
        with patch.dict(os.environ,{'CW_TRIAL_MODEL_KEY':'key','CW_TRIAL_MODEL':'glm-5.3','CW_TRIAL_DEEPSEEK_KEY':'key'}):
            catalog={m['id']:m for m in public_trial_models()}
            self.assertEqual({k:(m['context'],m['output']) for k,m in catalog.items()},
                             {'glm-5.3-flash':(1000000,128000),'deepseek-flash':(1000000,384000)})
        _,t=self.make_workspace();qid=self.run_lease(t)
        self.store.execute('UPDATE trial_runs SET started=? WHERE queue_id=?',(time.time()-7200,qid))
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('long-run'),self.uid,time.time()+60))
        seen=[]
        def upstream(request):seen.append(json.loads(request.content));return httpx.Response(200,json={'choices':[]})
        headers={'Authorization':'Bearer long-run','X-Workbench-Thread':t['id']}
        for requested,expected in [(None,128000),(32768,32768),(999999,128000)]:
            body={'model':'glm-5.3-flash','messages':[]}
            if requested:body['max_tokens']=requested
            response=self.relay(upstream,body,headers);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(seen[-1]['max_tokens'],expected)
        with patch.dict(os.environ,{'CW_TRIAL_DEEPSEEK_KEY':'secret','CW_TRIAL_DEEPSEEK_BASE_URL':'https://upstream.test/v1'}):
            response=self.relay(upstream,{'model':'deepseek-flash','messages':[]},headers)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(seen[-1]['max_tokens'],384000)
        for invalid in [True,0,-1,'384000']:
            response=self.relay(upstream,{'model':'glm-5.3-flash','messages':[],'max_tokens':invalid},headers)
            self.assertEqual(response.status_code,422)
        self.store.execute('INSERT OR REPLACE INTO platform_settings VALUES(1,?)',(json.dumps({'run_seconds':600}),))
        self.assertNotIn('run_seconds',self.accounts.limits())

    def test_platform_model_rename_keeps_selections_quota_and_history(self):
        _,t=self.make_workspace();u=self.accounts.fresh({'id':self.uid})
        self.store.execute('UPDATE users SET model=? WHERE id=?',('trial/glm-5.3',u['id']))
        self.store.execute('UPDATE threads SET model=? WHERE id=?',('trial/glm-5.3',t['id']))
        qid=self.app.state.queue.enqueue(u,t['id'],{'model':'trial/glm-5.3','text':'test','request_id':'rename'})
        with patch.dict(os.environ,{'CW_TRIAL_MODEL_KEY':'key','CW_TRIAL_MODEL':'glm-5.3','CW_PUBLIC_ORIGIN':'https://workbench.test'}):
            self.app.state.ensure_trial(self.accounts.fresh(u))
        self.assertEqual(self.accounts.fresh(u)['model'],'trial/glm-5.3-flash')
        self.assertEqual(self.store.one('SELECT model FROM threads WHERE id=?',(t['id'],))['model'],'trial/glm-5.3-flash')
        row=self.store.one('SELECT body FROM queued_messages WHERE id=?',(qid,))
        self.assertEqual(json.loads(row['body'])['model'],'trial/glm-5.3-flash')
        self.assertEqual(self.accounts.usage(u)['used'],1)

    def test_large_context_and_stream_are_not_cut_by_old_byte_caps(self):
        _,t=self.make_workspace();self.run_lease(t)
        self.store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest('large-token'),self.uid,time.time()+60))
        output=b'x'*4_100_000
        def upstream(request):
            self.assertGreater(len(request.content),2_000_000)
            return httpx.Response(200,content=output)
        response=self.relay(upstream,{'model':'glm-5.3-flash','messages':[{'role':'user','content':'x'*2_100_000}]},
                            {'Authorization':'Bearer large-token','X-Workbench-Thread':t['id']})
        self.assertEqual(response.status_code,200,response.text[:100])
        self.assertEqual(len(response.content),len(output))

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(TrialSecurityTests):setattr(TrialSecurityTests,_name,None)
