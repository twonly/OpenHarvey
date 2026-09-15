import time
import json
import os
import httpx
from urllib.parse import urlparse, parse_qs
import unittest
from unittest.mock import patch
import test_workbench as fixtures
from contract_web.store import digest
from contract_web.runtime import visible_event
from contract_web.thread_titles import resolve_title


class SessionContinuityTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace

    def test_email_and_oauth_ignore_short_supabase_access_token_lifetime(self):
        identity={'id':'auth-continuity-user','email':'continuity@example.com','email_confirmed_at':'now'}
        async def request(client,method,url,**kwargs):
            value=identity if url.endswith('/user') else {'access_token':'synthetic-test-token','expires_in':3600}
            return httpx.Response(200,json=value)
        env={'CW_SUPABASE_URL':'https://auth.example.com','CW_SUPABASE_PUBLISHABLE_KEY':'test-key'}
        with patch.dict(os.environ,env),patch('httpx.AsyncClient.request',request),patch('contract_web.auth_api.public_trial_models',return_value=[]):
            for provider in ['email','github','google']:
                self.client.cookies.clear()
                if provider=='email':
                    response=self.client.post('/api/auth/email',json={'email':identity['email'],'password':'test-password'},headers=self.headers)
                else:
                    start=self.client.post('/api/auth/start',json={'provider':provider},headers=self.headers)
                    query=parse_qs(urlparse(start.json()['auth_url']).query)
                    flow=parse_qs(urlparse(query['redirect_to'][0]).query)['flow'][0]
                    response=self.client.post('/api/auth/exchange',json={'flow':flow,'code':'test-code'},headers=self.headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertIn('Max-Age=2592000',response.headers['set-cookie'])
                token=self.client.cookies.get('contract_session')
                row=self.store.one('SELECT expires FROM logins WHERE token=?',(digest(token),))
                self.assertAlmostEqual(row['expires']-time.time(),30*86400,delta=5)
                with patch('contract_web.store.time.time',return_value=time.time()+7200):
                    self.assertIsNotNone(self.store.authenticate(token))

    def test_login_and_sliding_renewal_and_logout(self):
        token=self.client.cookies.get('contract_session')
        row=self.store.one('SELECT expires FROM logins WHERE token=?',(digest(token),))
        self.assertAlmostEqual(row['expires']-time.time(),30*86400,delta=5)
        self.store.execute('UPDATE logins SET expires=? WHERE token=?',(time.time()+600,digest(token)))
        response=self.client.get('/api/me')
        self.assertEqual(response.status_code,200)
        self.assertIn('Max-Age=2592000',response.headers['set-cookie'])
        self.assertNotIn('set-cookie',self.client.get('/api/me').headers)
        self.client.post('/api/logout',headers=self.headers)
        self.assertIsNone(self.store.renew_login(token))

    def test_expired_and_demo_sessions(self):
        token=self.client.cookies.get('contract_session')
        self.store.execute('UPDATE logins SET expires=? WHERE token=?',(time.time()-1,digest(token)))
        self.assertIsNone(self.store.renew_login(token))
        self.assertIsNone(self.store.authenticate(token))
        accounts=self.app.state.accounts
        demo=accounts.create('demo');token=accounts.login(demo)
        row=self.store.one('SELECT expires FROM logins WHERE token=?',(digest(token),))
        self.assertLessEqual(row['expires'],demo['expires_at'])
        self.assertIsNone(self.store.renew_login(token))

    def test_snapshot_replaces_placeholder_and_preserves_custom_title(self):
        w,t=self.make_workspace()
        native=next(s['sessions'][t['session_id']] for s in fixtures.FakeRuntime.servers.values() if t['session_id'] in s['sessions'])
        native['title']='New session - 2026-09-15T12:00:00Z'
        native['messages']=[{'info':{'id':'msg_title','role':'user'},'parts':[{'id':'part_title','type':'text','text':'这个合同的付款条件是什么？'}]}]
        response=self.client.get('/api/threads/'+t['id'])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['title'],'新对话')
        native['title']='付款条件分析'
        self.assertEqual(self.client.get('/api/threads/'+t['id']).json()['title'],'付款条件分析')
        self.store.execute('UPDATE threads SET custom_title=? WHERE id=?',('我的合同',t['id']))
        self.assertEqual(self.client.get('/api/threads/'+t['id']).json()['title'],'我的合同')

    def test_auth_failure_diagnostics_never_include_credentials(self):
        token=self.client.cookies.get('contract_session')
        self.assertEqual(self.store.login_failure_reason(''),'cookie_missing')
        self.assertEqual(self.store.login_failure_reason('invalid'),'credential_unknown_or_revoked')
        self.store.execute('UPDATE logins SET expires=? WHERE token=?',(time.time()-1,digest(token)))
        self.assertEqual(self.store.login_failure_reason(token),'login_expired')
        with self.assertLogs('contract_web.app',level='WARNING') as captured:
            response=self.client.get('/api/me')
        self.assertEqual(response.status_code,401)
        self.assertIn('reason=login_expired',' '.join(captured.output))
        self.assertNotIn(token,' '.join(captured.output))

    def test_first_query_does_not_name_thread_before_native_title(self):
        w,t=self.make_workspace()
        response=fixtures.WorkbenchTests.send(self,t,text='请解释验收后付款的条件')
        self.assertEqual(response.status_code,202,response.text)
        self.assertNotIn('title',response.json())
        self.assertEqual(self.store.one('SELECT title FROM threads WHERE id=?',(t['id'],))['title'],'新对话')

    def test_native_title_uses_selected_provider_and_preserves_project_config(self):
        w,t=self.make_workspace()
        path=self.store.user_root(self.uid)/'threads'/t['id']/'opencode.json'
        config=json.loads(path.read_text()) if path.exists() else {}
        config.update(small_model='unfunded/auto',provider={'trial':{'options':{'headers':{'X-Workbench-Thread':t['id']}}}})
        path.write_text(json.dumps(config))
        response=fixtures.WorkbenchTests.send(self,t,text='请解释付款条件',model='deepseek/flash')
        self.assertEqual(response.status_code,202,response.text)
        installed=json.loads(path.read_text())
        self.assertEqual(installed['agent']['title']['model'],'deepseek/flash')
        self.assertEqual(installed['provider'],config['provider'])
        calls=fixtures.FakeRuntime.servers['http://alice']['calls']
        dispose=next(i for i,c in enumerate(calls) if c[1]=='/instance/dispose')
        prompt=next(i for i,c in enumerate(calls) if c[1].endswith('/prompt_async'))
        self.assertLess(dispose,prompt)
        self.assertEqual(self.store.one('SELECT title FROM threads WHERE id=?',(t['id'],))['title'],'新对话')

    def test_title_event_scope_and_fallback(self):
        event={'type':'session.updated','properties':{'info':{'id':'ses_a','title':'合同付款条款'}}}
        self.assertEqual(visible_event(event,'ses_a',set())['properties']['info']['title'],'合同付款条款')
        self.assertIsNone(visible_event(event,'ses_b',set()))
        self.assertEqual(resolve_title({'title':'新对话'},'New session - 2026-09-15'),'新对话')
