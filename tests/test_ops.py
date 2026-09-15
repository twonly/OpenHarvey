import csv
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from contract_web.app import create_app
from contract_web.documents import prepare
from test_workbench import FakeRuntime


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=create_app(self.tmp.name,FakeRuntime)
        self.store=self.app.state.store
        self.owner=self.store.add_user('owner','owner-password')
        self.member=self.store.add_user('member','member-password')
        self.admin=self.store.add_user('second-admin','admin-password')
        self.demo=self.store.add_user('visitor','demo-password')
        self.store.execute("UPDATE users SET role='admin' WHERE id IN (?,?)",(self.owner,self.admin))
        self.store.execute("UPDATE users SET account_kind='demo',expires_at=?,active=0,cleaned_at=? WHERE id=?",(time.time()-50,time.time(),self.demo))
        self.env=patch.dict(os.environ,{'CW_OPS_OWNER_USER_ID':self.owner});self.env.start();self.addCleanup(self.env.stop)
        self.client=TestClient(self.app)
        self.login(self.owner)
        now=time.time()
        self.now=now
        self.wid='workspace';self.tid='thread';self.did='doc'
        self.store.execute('INSERT INTO documents(id,user_id,workspace_id,filename,suffix,source_hash) VALUES(?,?,?,?,?,?)',(self.did,self.member,self.wid,'原文.txt','.txt','hash'))
        self.store.execute('INSERT INTO workspaces(id,user_id,document_id,title,created,last_activity_at,backend) VALUES(?,?,?,?,?,?,?)',(self.wid,self.member,self.did,'验收合同',now-100,now,'e2b'))
        self.store.execute('INSERT INTO threads(id,workspace_id,session_id,title,save_token,created) VALUES(?,?,?,?,?,?)',(self.tid,self.wid,'session','合同对话','save-token',now-100))
        for i,status in enumerate(['completed','failed','interrupted','running']):
            summary={'status':status,'tokens':100 if i==0 else 0 if i==1 else None,'cost':None,'duration':[10,20,30,999][i],
                     'model':'test/model' if i<3 else None,'tool_errors':2 if i==0 else 0,'prompt':'请看 SENSITIVE-TEST-KEY'}
            self.store.execute('INSERT INTO trace_runs VALUES(?,?,?,?,?,?,?)',(f'run{i}',self.tid,self.member,f'msg{i}',None,now-40+i*5,json.dumps(summary)))
        self.store.execute('INSERT INTO trace_runs VALUES(?,?,?,?,?,?,?)',('owner-run',self.tid,self.owner,'ownmsg',None,now-30,json.dumps({'status':'completed','tokens':9000,'model':'owner/model','duration':1})))
        self.store.execute('INSERT INTO queued_messages(id,thread_id,user_id,request_id,body,status,message_id,created) VALUES(?,?,?,?,?,?,?,?)',('q1',self.tid,self.member,'req','{"skill":"contract-summary"}','completed','msg1',now-30))
        self.store.execute('INSERT INTO trial_runs(queue_id,user_id,platform,day,status,started) VALUES(?,?,?,?,?,?)',('q1',self.member,1,'2026-09-13','done',now-30))
        self.store.execute('INSERT INTO trial_runs(queue_id,user_id,platform,day,status,started) VALUES(?,?,?,?,?,?)',('operation-probe',self.member,0,'2026-09-13','done',now-30))
        self.store.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',('artifact',self.wid,self.tid,'document','=formula','hash','hash',now-10))
        dest=self.store.user_root(self.member)/'published'/'artifact';dest.mkdir(parents=True)
        (dest/'report.json').write_text(json.dumps({'kind':'document','format':'html','title':'测试产出','content':'<p>保存的正文</p>'}))
        (dest/'content.html').write_text('<script>window.test=true</script><p>保存的正文【B0】</p>')
        source=self.store.user_root(self.member)/'sources'/self.did;source.mkdir(parents=True)
        path=source/'source.txt';path.write_text('第一条 付款条件。\n第二条 验收条件。');mapping=prepare(path,self.did)
        self.store.execute('UPDATE documents SET source_hash=? WHERE id=?',(mapping['source_hash'],self.did))
        self.store.execute('UPDATE artifacts SET source_hash=? WHERE id=?',(mapping['source_hash'],'artifact'))
        history=[{'info':{'id':'msg0','role':'user','time':{'created':(now-40)*1000}},'parts':[{'type':'text','text':'问题 SENSITIVE-TEST-KEY'}]},
                 {'info':{'id':'assistant','role':'assistant'},'parts':[{'type':'text','text':'原文【Ddoc:B0】'},{'type':'reasoning','text':'PRIVATE_REASONING'}]},
                 {'info':{'id':'msg1','role':'user'},'parts':[{'type':'text','text':'下一轮不应出现'}]}]
        self.store.execute('INSERT INTO e2b_history VALUES(?,?,?,?)',(self.tid,json.dumps(history),'{}',now))
        self.store.execute('INSERT INTO e2b_bindings(workspace_id,status,last_activity,synced) VALUES(?,?,?,?)',(self.wid,'paused',now,now))
        self.store.execute('INSERT INTO e2b_events(workspace_id,kind,data,created) VALUES(?,?,?,?)',(self.wid,'sandbox.paused','{}',now))

    def login(self,uid):
        self.client.cookies.clear()
        row=self.store.one('SELECT * FROM users WHERE id=?',(uid,))
        self.client.cookies.set('contract_session',self.app.state.accounts.login(row))

    def get(self,path):
        response=self.client.get(path)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_metrics_preserve_distinct_execution_queue_and_delivery_semantics(self):
        d=self.get('/api/ops/overview');m=d['metrics']
        self.assertEqual(m['runs'],4);self.assertEqual(m['active_users'],1)
        self.assertEqual(m['states'],dict(completed=1,failed=1,interrupted=1,running=1))
        self.assertAlmostEqual(m['failure_rate'],1/3)
        self.assertEqual(m['queued_requests'],1);self.assertEqual(m['artifacts'],1)
        self.assertEqual(m['tokens'],100);self.assertEqual(m['token_samples'],2)
        self.assertIsNone(m['cost']);self.assertEqual(m['cost_samples'],0)
        self.assertEqual(m['duration_p50'],20);self.assertEqual(m['duration_p95'],29)
        self.assertEqual(m['duration_samples'],3);self.assertEqual(m['tool_errors'],2)
        self.assertEqual(sum(r['runs'] for r in d['trend']),4)
        self.assertEqual(sum(r['artifacts'] for r in d['trend']),1)
        self.assertEqual(self.get('/api/ops/overview?exclude_owner=0')['metrics']['runs'],5)

    def test_every_surface_requires_unique_owner_even_for_other_admin(self):
        paths=['/ops','/ops/detail','/api/ops/options','/api/ops/overview','/api/ops/users',
               '/api/ops/models','/api/ops/runtime','/api/ops/contracts/workspace','/api/ops/runs/run0',
               '/api/ops/documents/doc','/api/ops/documents/doc/file','/api/ops/artifacts/artifact',
               '/api/ops/artifacts/artifact/preview','/api/ops/artifacts/artifact/file','/api/ops/export/runs']
        for uid in (self.member,self.admin):
            self.login(uid)
            self.assertFalse(self.get('/api/me')['capabilities']['ops'])
            for path in paths:self.assertEqual(self.client.get(path).status_code,403,path)
        self.client.cookies.clear()
        for path in paths:self.assertEqual(self.client.get(path).status_code,401,path)
        self.login(self.owner)
        self.assertTrue(self.get('/api/me')['capabilities']['ops'])
        with patch.dict(os.environ,{'CW_OPS_OWNER_USER_ID':''}):
            for path in paths:self.assertEqual(self.client.get(path).status_code,403,path)

    def test_content_is_audited_scrubbed_and_never_contacts_runtime(self):
        with patch.object(FakeRuntime,'call',side_effect=AssertionError('must not call runtime')),patch.object(self.app.state.traces,'credentials',return_value=['SENSITIVE-TEST-KEY']):
            d=self.get('/api/ops/runs/run0')
            value=json.dumps(d,ensure_ascii=False)
            self.assertNotIn('SENSITIVE-TEST-KEY',value);self.assertNotIn('PRIVATE_REASONING',value)
            self.assertNotIn('下一轮不应出现',value)
            self.assertEqual(d['artifact_association'],'对话级产出；未推定属于本轮')
            self.get('/api/ops/contracts/workspace');self.get('/api/ops/documents/doc')
            self.get('/api/ops/artifacts/artifact')
            preview=self.client.get('/api/ops/artifacts/artifact/preview')
            self.assertEqual(preview.status_code,200)
            self.assertIn('sandbox allow-scripts',preview.headers['content-security-policy'])
            self.assertNotIn('allow-same-origin',preview.headers['content-security-policy'])
            self.assertIn('workbench.citation',preview.text)
            self.assertIn('查看原文',preview.text)
        self.assertEqual(self.store.one("SELECT COUNT(*) n FROM audit_log WHERE action='ops.content.read'")['n'],5)
        self.assertEqual(self.client.get('/api/workspaces/workspace').status_code,404)
        self.assertEqual(self.client.get('/api/artifacts/artifact').status_code,404)

    def test_filters_pagination_csv_and_missing_model(self):
        d=self.get('/api/ops/runs?status=failed&limit=1')
        self.assertEqual(d['total'],1);self.assertEqual(d['items'][0]['explicit_skill'],'contract-summary')
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/ops/export/runs?status=failed').text.lstrip('\ufeff'))))
        self.assertEqual([r['id'] for r in rows],[d['items'][0]['id']])
        self.assertEqual(self.get('/api/ops/runs?offset=2&limit=1')['total'],4)
        self.assertEqual(self.get('/api/ops/runs?model=__missing__')['total'],1)
        models=self.get('/api/ops/models')
        self.assertEqual(sum(m['runs'] for m in models['items']),4)
        self.assertEqual(sum(q['count'] for q in models['quota']),1)
        csvtext=self.client.get('/api/ops/export/artifacts').text
        self.assertIn("'=formula",csvtext)
        self.assertEqual(self.client.get('/api/ops/runs?sort=created;DROP+TABLE+users').status_code,200)
        self.assertEqual(self.client.get('/api/ops/runs?start=nope').status_code,422)
        self.assertEqual(self.client.get('/api/ops/runs?start=2026-01-01&end=2025-01-01').status_code,422)

    def test_html_citation_version_mismatch_never_creates_navigation_or_changes_file(self):
        path=self.store.user_root(self.member)/'published'/'artifact'/'content.html'
        before=path.read_bytes()
        self.store.execute("UPDATE documents SET source_hash='different-version' WHERE id=?",(self.did,))
        preview=self.client.get('/api/ops/artifacts/artifact/preview')
        self.assertEqual(preview.status_code,200)
        self.assertIn('来源待核对',preview.text)
        self.assertNotIn('workbench.citation',preview.text)
        self.assertEqual(before,path.read_bytes())

    def test_stock_expiry_cleaned_content_and_empty_denominators(self):
        users=self.get('/api/ops/users')['items'];demo=next(u for u in users if u['id']==self.demo)
        self.assertFalse(demo['effective_active']);self.assertIsNotNone(demo['cleaned_at'])
        self.store.execute('UPDATE workspaces SET created=?,deleted_at=? WHERE id=?',(self.now-40*86400,self.now,self.wid))
        self.assertEqual(self.get('/api/ops/contracts')['total'],0)
        self.assertEqual(self.get('/api/ops/artifacts')['total'],1)
        self.assertEqual(self.get('/api/ops/contracts/workspace')['workspace']['deleted_at'],self.now)
        path=self.store.user_root(self.member)/'published'/'artifact'/'report.json';path.unlink()
        self.assertEqual(self.client.get('/api/ops/artifacts/artifact').status_code,410)
        self.assertFalse(self.get('/api/ops/artifacts')['items'][0]['available'])
        d=self.get('/api/ops/overview?account_kind=demo')
        self.assertIsNone(d['metrics']['failure_rate']);self.assertIsNone(d['metrics']['tokens'])
        self.assertEqual(self.client.get('/api/ops/runs/missing').status_code,410)

    def test_all_sections_and_export_are_read_only_except_audit(self):
        before=self.store.all('SELECT * FROM queued_messages')
        with patch.object(FakeRuntime,'call',side_effect=AssertionError('runtime call')):
            for section in ('overview','users','runs','contracts','artifacts','models','runtime'):
                self.get('/api/ops/'+section)
                if section!='overview':self.assertEqual(self.client.get('/api/ops/export/'+section).status_code,200)
        self.assertEqual(before,self.store.all('SELECT * FROM queued_messages'))
        self.assertEqual(self.client.get('/ops').status_code,200)
        self.assertIn("frame-ancestors 'none'",self.client.get('/ops').headers['content-security-policy'])
