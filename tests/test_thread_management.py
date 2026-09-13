import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import test_workbench as fixtures
from contract_web.store import Store

class ThreadManagementTests(unittest.TestCase):
    setUp=fixtures.WorkbenchTests.setUp
    tearDown=fixtures.WorkbenchTests.tearDown
    login=fixtures.WorkbenchTests.login
    make_workspace=fixtures.WorkbenchTests.make_workspace
    native=fixtures.WorkbenchTests.native

    def manage(self,t,action):
        return self.client.patch('/api/threads/'+t['id'],json={'action':action},headers=self.headers)
    def threads(self,w):
        return self.client.get('/api/workspaces/'+w['id']).json()['threads']
    def new(self,w):
        return self.client.post(f'/api/workspaces/{w["id"]}/threads',json={},headers=self.headers).json()

    def test_rename_survives_native_title_and_is_owner_scoped(self):
        w,t=self.make_workspace();path='/api/threads/'+t['id']
        for title in ['', '  ', 'x'*121, None]:
            self.assertEqual(self.client.patch(path,json={'action':'rename','title':title},headers=self.headers).status_code,422)
        self.native(t)['status']={'type':'busy'}
        self.assertEqual(self.client.patch(path,json={'action':'rename','title':'  我的审查  '},headers=self.headers).status_code,200)
        self.assertEqual(self.client.get(path).json()['title'],'我的审查')
        self.assertEqual(Store(self.root).one('SELECT custom_title FROM threads WHERE id=?',(t['id'],))['custom_title'],'我的审查')
        self.login('bob')
        self.assertEqual(self.client.patch(path,json={'action':'rename','title':'别人的'},headers=self.headers).status_code,404)

    def test_activity_and_exact_completion_ack(self):
        w,t=self.make_workspace();path=f'/api/workspaces/{w["id"]}/thread-status'
        def activity():return next(row for row in self.client.get(path).json() if row['id']==t['id'])
        self.assertEqual(activity()['activity'],'idle')
        self.native(t)['status']={'type':'busy'}
        self.assertEqual(activity()['activity'],'running')
        self.native(t)['status']={'type':'retry'}
        self.assertEqual(activity()['activity'],'waiting')
        self.native(t)['status']={'type':'idle'}
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        qid=self.app.state.queue.enqueue(u,t['id'],{'text':'hello'})
        self.store.execute("UPDATE queued_messages SET status='completed' WHERE id=?",(qid,))
        self.native(t)['messages']=[{'info':{'id':'answer','role':'assistant','time':{'completed':123}},'parts':[]}]
        self.assertEqual(activity(),{'id':t['id'],'activity':'completed','completion_id':qid})
        seen=f'/api/threads/{t["id"]}/seen'
        self.client.post(seen,json={'completion_id':'stale'},headers=self.headers)
        self.assertEqual(activity()['activity'],'completed')
        self.assertEqual(self.client.get('/api/threads/'+t['id']).json()['completion_id'],qid)
        self.client.post(seen,json={'completion_id':qid},headers=self.headers)
        self.assertEqual(activity()['activity'],'idle')
        self.assertEqual(Store(self.root).one('SELECT seen_completion FROM threads WHERE id=?',(t['id'],))['seen_completion'],qid)
        self.native(t)['messages'][0]['info']['error']={'name':'APIError'}
        self.assertEqual(activity()['activity'],'failed')
        self.login('bob')
        self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post(seen,json={'completion_id':qid},headers=self.headers).status_code,404)

    def test_order_persistence_restore_and_ownership(self):
        w,a=self.make_workspace();b=self.new(w);c=self.new(w)
        self.assertEqual([t['id'] for t in self.threads(w)],[c['id'],b['id'],a['id']])
        self.assertEqual(self.manage(a,'up').status_code,200)
        self.assertEqual([t['id'] for t in self.threads(w)],[c['id'],a['id'],b['id']])
        for action in ['archive','delete']:self.assertEqual(self.manage(a,action).status_code,200)
        deleted=next(t for t in self.threads(w) if t['id']==a['id'])
        self.assertTrue(deleted['deleted_at']);self.assertTrue(deleted['archived_at'])
        self.assertEqual(Store(self.root).one('SELECT position FROM threads WHERE id=?',(a['id'],))['position'],deleted['position'])
        self.assertEqual(self.manage(a,'restore').status_code,200)
        restored=next(t for t in self.threads(w) if t['id']==a['id'])
        self.assertIsNone(restored['deleted_at']);self.assertTrue(restored['archived_at'])
        self.assertEqual(self.manage(a,'restore').status_code,200)
        self.assertEqual([t['id'] for t in self.threads(w)],[c['id'],a['id'],b['id']])
        self.assertIsNotNone(self.store.one("SELECT * FROM audit_log WHERE action='thread.archive' AND target=?",(a['id'],)))
        self.login('bob')
        for action in ['delete','up','restore']:self.assertEqual(self.manage(a,action).status_code,404)

    def test_busy_requests_queue_and_invalid_actions(self):
        w,t=self.make_workspace();self.new(w)
        self.native(t)['status']={'type':'busy'}
        self.assertEqual(self.manage(t,'archive').status_code,409)
        self.assertEqual(self.manage(t,'up').status_code,200)
        self.native(t)['status']={'type':'idle'}
        server=fixtures.FakeRuntime.servers['http://alice']
        server['requests']['question']=[{'id':'q','sessionID':t['session_id']}]
        self.assertEqual(self.manage(t,'delete').status_code,409)
        server['requests']['question']=[]
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        qid=self.app.state.queue.enqueue(u,t['id'],{'text':'pending'})
        self.app.state.queue.pause(t['id'],'paused')
        self.assertEqual(self.manage(t,'archive').status_code,409)
        self.store.execute("UPDATE queued_messages SET status='withdrawn' WHERE id=?",(qid,))
        self.assertEqual(self.manage(t,'archive').status_code,200)
        self.assertEqual(self.manage(t,'purge').status_code,422)

    def test_read_only_history_attachments_artifacts_and_write_boundaries(self):
        w,t=self.make_workspace()
        attachment=self.client.post(f'/api/threads/{t["id"]}/attachments',content='补充约定'.encode(),headers={**self.headers,'X-Filename':'extra.txt'}).json()
        self.native(t)['messages']=[{'info':{'id':'msg_user','role':'user'},'parts':[{'type':'text','text':'历史问题'}]}]
        self.store.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',('saved',w['id'],t['id'],'document','已保存文件','hash','source',1))
        saved=self.store.user_root(self.uid)/'published'/'saved';saved.mkdir()
        (saved/'content.txt').write_text('保存的正文')
        (saved/'report.json').write_text(json.dumps({'format':'txt','kind':'document','content':'保存的正文'}))
        for action in ['archive','delete']:
            self.assertEqual(self.manage(t,action).status_code,200)
            snapshot=self.client.get('/api/threads/'+t['id'])
            self.assertEqual(snapshot.status_code,200);self.assertIn('历史问题',snapshot.text)
            self.assertEqual(self.client.get('/api/traces?scope=all').json()['total'],1)
            for method,path,body in [('post','messages',{'text':'不可发送'}),('post','queue/resume',{}),('put','permission-mode',{'mode':'auto'}),('post','skills/refresh',{}),('post','requests/question/q',{'answers':[]})]:
                response=getattr(self.client,method)(f'/api/threads/{t["id"]}/{path}',json=body,headers=self.headers)
                self.assertEqual(response.status_code,409,(path,response.text))
            self.assertEqual(self.client.post(f'/api/threads/{t["id"]}/attachments',content=b'no',headers={**self.headers,'X-Filename':'no.txt'}).status_code,409)
            self.assertEqual(self.client.delete(f'/api/threads/{t["id"]}/attachments/{attachment["id"]}',headers=self.headers).status_code,409)
            self.assertEqual(self.client.get(f'/api/documents/{attachment["id"]}/file?thread_id={t["id"]}').status_code,200)
            artifacts=self.client.get('/api/workspaces/'+w['id']).json()['artifacts']
            self.assertEqual(artifacts[0]['id'],'saved');self.assertEqual((saved/'content.txt').read_text(),'保存的正文')
            token=(self.store.user_root(self.uid)/'threads'/t['id']/'.publish-token').read_text()
            self.assertEqual(self.client.post('/internal/artifacts',json={},headers={'Authorization':'Bearer '+token}).status_code,409)

    def test_trace_filters_counts_order_and_history(self):
        w,a=self.make_workspace();b=self.new(w)
        for t in [a,b]:self.native(t)['messages']=[{'info':{'id':'msg_'+t['id'],'role':'user'},'parts':[{'type':'text','text':'历史查询'}]}]
        self.client.post('/api/traces/refresh',json={},headers=self.headers)
        path=f'/api/traces/contracts/{w["id"]}/threads'
        self.assertEqual([t['id'] for t in self.client.get(path).json()['threads']],[b['id'],a['id']])
        self.manage(a,'up')
        self.assertEqual([t['id'] for t in self.client.get(path).json()['threads']],[a['id'],b['id']])
        self.manage(a,'archive')
        self.assertEqual(self.client.get('/api/traces').json()['total'],1)
        self.assertEqual(self.client.get('/api/traces/contracts?scope=archived').json()['contracts'][0]['thread_count'],1)
        self.assertEqual(self.client.get(path+'?scope=archived').json()['threads'][0]['id'],a['id'])
        self.manage(a,'delete')
        self.assertEqual(self.client.get('/api/traces?scope=archived').json()['total'],0)
        self.assertEqual(self.client.get('/api/traces?scope=deleted&q=历史查询').json()['total'],1)
        self.assertEqual(self.client.get('/api/traces?scope=all').json()['total'],2)
        self.assertEqual(self.client.get(f'/api/traces/threads/{a["id"]}/runs').json()['total'],1)
        self.assertEqual(self.client.get('/api/traces?scope=invalid').status_code,422)

    def test_legacy_migration_order(self):
        with tempfile.TemporaryDirectory() as root:
            db=sqlite3.connect(Path(root)/'app.sqlite')
            db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,workspace_id TEXT,session_id TEXT,title TEXT,save_token TEXT,created REAL)')
            db.executemany('INSERT INTO threads VALUES(?,?,?,?,?,?)',[('later','w','s2','later','k2',2),('first','w','s1','first','k1',1)])
            db.commit();db.close();store=Store(root)
            self.assertEqual([t['id'] for t in store.all('SELECT * FROM threads ORDER BY position')],['first','later'])
            self.assertTrue(all(t['archived_at'] is None and t['deleted_at'] is None for t in store.all('SELECT * FROM threads')))
