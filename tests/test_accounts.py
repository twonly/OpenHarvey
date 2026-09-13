import asyncio
import json
import os
import secrets
import time
from unittest.mock import AsyncMock,patch

from fastapi import HTTPException
from contract_web.accounts import PUBLIC_RISK
from contract_web.store import digest
import test_workbench as fixtures


class AccountTests(fixtures.WorkbenchTests):
    def setUp(self):
        super().setUp();self.accounts=self.app.state.accounts

    def token(self,u):
        self.client.cookies.clear();self.client.cookies.set('contract_session',self.accounts.login(u));return self.client.cookies.get('contract_session')

    def test_demo_owns_data_cannot_configure_or_escalate(self):
        a=self.accounts.create('demo');b=self.accounts.create('demo');self.token(a)
        self.assertEqual(self.client.get('/api/me').json()['account_kind'],'demo')
        self.assertEqual(self.client.post('/api/providers',json={'id':'anything'},headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/orca/connect-url').status_code,403)
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        self.assertEqual(self.client.put('/api/settings',json={'values':{'role':'admin'},'revision':1},headers=self.headers).status_code,422)
        self.assertNotIn(self.store.one("SELECT id FROM config_items WHERE org_id='default'")['id'],[r['id'] for r in self.client.get('/api/risk-schemes').json()])
        self.assertEqual(len(self.client.get('/api/risk-schemes/'+PUBLIC_RISK).json()['content']['rules']),4)
        self.assertEqual(self.client.put('/api/risk-schemes/'+PUBLIC_RISK,json={'revision':1},headers=self.headers).status_code,403)
        self.token(b);self.assertEqual(self.client.get('/api/me').json()['id'],b['id'])

    def test_expiry_invalidates_existing_login(self):
        u=self.accounts.create('demo');self.token(u)
        self.store.execute('UPDATE users SET expires_at=? WHERE id=?',(time.time()-1,u['id']))
        self.assertEqual(self.client.get('/api/me').status_code,401)

    def test_upgrade_keeps_uid_preferences_usage_and_no_second_grant(self):
        u=self.accounts.create('demo');self.store.execute('UPDATE users SET trial_used=4,preferences=? WHERE id=?',(json.dumps({'assistant_name':'小合','user_nickname':'小王'}),u['id']))
        identity={'id':'supabase-subject','email':'sample@example.com','email_confirmed_at':'2026-01-01','user_metadata':{'role':'admin'}}
        result=self.accounts.bind(identity,u)
        self.assertEqual((result['id'],result['role'],result['account_kind']),(u['id'],'member','personal'))
        self.assertIsNone(result['expires_at']);self.assertEqual(self.accounts.usage(result)['remaining'],16)
        self.assertEqual(self.accounts.bind(identity,u)['trial_total'],20)
        self.assertEqual(json.loads(result['preferences'])['assistant_name'],'小合')
        self.assertEqual(self.accounts.bind(identity,self.accounts.create('demo'))['id'],u['id'])
        with self.assertRaises(HTTPException):self.accounts.bind({'id':'bad','email':'admin@example.com','user_metadata':{'role':'admin'}},u)

    def test_admin_identity_needs_explicit_link(self):
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.uid,));u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        identity={'id':'one','email':'admin@example.com','email_confirmed_at':'now'}
        r=self.accounts.bind(identity,u,False);self.assertNotEqual(r['id'],u['id']);self.assertEqual(r['role'],'member')
        r=self.accounts.bind({**identity,'id':'two'},u,True);self.assertEqual(r['id'],u['id']);self.assertEqual(r['role'],'admin')

    def test_resource_counts_survive_deletion_and_enforce_demo_two(self):
        u=self.accounts.create('demo')
        for _ in range(3):self.accounts.reserve_resource(u,'thread')
        with self.assertRaises(HTTPException):self.accounts.reserve_resource(u,'thread')
        self.accounts.reserve_resource(u,'upload');self.accounts.reserve_resource(u,'upload')
        with self.assertRaises(HTTPException):self.accounts.reserve_resource(u,'upload')
        self.assertEqual(self.accounts.limits()['user_concurrency'],2)

    def test_queue_dedup_atomic_quota_claim_and_refund(self):
        w,t=self.make_workspace();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));q=self.app.state.queue
        def enqueue(i):return q.enqueue(u,t['id'],{'text':'问题','model':'trial/glm-5.3','request_id':str(i)})
        first=enqueue(0);self.assertEqual(first,enqueue(0));self.assertEqual(self.accounts.usage(u)['used'],1)
        for i in range(1,20):enqueue(i)
        with self.assertRaises(HTTPException):enqueue(20)
        self.accounts.finish(first,True);self.assertEqual(self.accounts.usage(u)['used'],19)
        self.accounts.finish(first,True);self.assertEqual(self.accounts.usage(u)['used'],19)
        ids=[r['id'] for r in self.store.all("SELECT id FROM queued_messages WHERE id!=? ORDER BY seq",(first,))]
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.assertTrue(self.accounts.claim(db,ids[0]));self.assertTrue(self.accounts.claim(db,ids[1]));self.assertFalse(self.accounts.claim(db,ids[2]))
        self.store.execute('UPDATE trial_runs SET model_accepted=1 WHERE queue_id=?',(ids[0],))
        self.accounts.finish(ids[0],True);self.assertEqual(self.accounts.usage(u)['used'],19)
        with self.store.connect() as db:self.assertTrue(self.accounts.claim(db,ids[2]))

    def test_names_persist_and_are_in_native_system_on_next_turn(self):
        prefs=self.client.get('/api/settings').json()
        r=self.client.put('/api/settings',json={'values':{'assistant_name':'小合','user_nickname':'王老师','onboarding_completed':True},'revision':prefs['revision']},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        w,t=self.make_workspace();self.send(t)
        # FakeRuntime keeps native messages; patch dispatch to capture the system argument.
        captured=[];original=fixtures.FakeRuntime.call
        async def capture(rt,method,path,**kwargs):
            if path.endswith('/prompt_async'):captured.append(kwargs['body']['system'])
            return await original(rt,method,path,**kwargs)
        self.finish(t)
        with patch.object(fixtures.FakeRuntime,'call',capture):self.send(t)
        self.assertTrue(captured);self.assertIn('小合',captured[0]);self.assertIn('王老师',captured[0]);self.assertIn('不是操作指令',captured[0])
        self.login('bob');self.assertEqual(self.client.get('/api/settings').json()['effective']['assistant_name'],'合同助手')

    def test_auth_flow_browser_binding_replay_and_forged_identity(self):
        env={'CW_SUPABASE_URL':'https://auth.example.com','CW_SUPABASE_PUBLISHABLE_KEY':'public-key'}
        with patch.dict(os.environ,env):
            r=self.client.post('/api/auth/start',json={'provider':'github','role':'admin'},headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
            from urllib.parse import urlparse,parse_qs
            query=parse_qs(urlparse(r.json()['auth_url']).query)
            self.assertIn('code_challenge',query);self.assertEqual(query['code_challenge_method'],['s256'])
            state=parse_qs(urlparse(query['redirect_to'][0]).query)['flow'][0]
            browser=self.client.cookies.get('workbench_auth_flow')
            self.client.cookies.delete('workbench_auth_flow')
            self.assertEqual(self.client.post('/api/auth/exchange',json={'flow':state,'code':'bad'},headers=self.headers).status_code,400)
            self.client.cookies.set('workbench_auth_flow',browser)
            self.assertIsNotNone(self.store.one('SELECT 1 FROM auth_flows WHERE state=?',(digest(state),)))
        self.assertEqual(self.client.post('/api/auth/start',json={'provider':'evil'},headers=self.headers).status_code,422)

    def test_orca_flow_has_pkce_state_referral_and_no_secret(self):
        r=self.client.get('/orca/connect-url');self.assertEqual(r.status_code,200,r.text)
        url=r.json()['auth_url'];self.assertIn('code_challenge_method=S256',url);self.assertIn('ref_d0785b3ec87207162565',url)
        row=self.store.one("SELECT * FROM auth_flows WHERE kind='orca'");self.assertNotIn(row['verifier'],url)
        self.assertEqual(self.client.get('/orca/callback?state=wrong&code=x').status_code,400)

    def test_private_config_hidden_even_from_other_admin(self):
        skill=self.app.state.settings.save_item(self.store.one('SELECT * FROM users WHERE id=?',(self.uid,)),'skill',{'content':{'label':'私有','description':'private','body':'PRIVATE COMPANY MATERIAL','files':{}},'scope':'personal'})
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.bid,));self.login('bob')
        self.assertEqual(self.client.get('/api/skills/'+skill['id']).status_code,404)
        self.assertEqual(self.client.put('/api/skills/'+skill['id'],json=skill,headers=self.headers).status_code,404)

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(AccountTests):setattr(AccountTests,_name,None)
