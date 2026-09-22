"""E2B transport fault tests. No cloud credentials or customer documents used."""
import asyncio
import copy
import hashlib
import json
import secrets
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import httpx
import test_workbench as fixtures
from contract_web.runtime import Runtime
from contract_web.e2b_runtime import E2B
from contract_web.settings import encoded


class FakeFiles:
    def __init__(self):self.data={};self.writes=[]
    async def write(self,path,data,**kwargs):
        self.data[path]=data.encode() if isinstance(data,str) else data;self.writes.append(path)
    async def write_files(self,files,**kwargs):
        for item in files:await self.write(item['path'],item['data'],**kwargs)
    async def read(self,path,format='text',**kwargs):
        data=self.data[path];return bytearray(data) if format=='bytes' else data.decode()
    async def make_dir(self,path):return True
    async def remove(self,path):self.data.pop(path,None)
    async def list(self,path,depth=1):
        return [SimpleNamespace(name=Path(p).name,path=p) for p in self.data if p.startswith(path+'/') and p.count('/')==path.count('/')+1]


class FakeSandbox:
    instances={};created=0;connects=[];fault=None;options=[]
    def __init__(self,metadata):
        self.sandbox_id='sbx_'+secrets.token_hex(6);self.metadata=metadata;self.state='running'
        self.started_at=datetime.now(timezone.utc);self.traffic_access_token='traffic-secret-12345'
        self.pending={'question':[],'permission':[]}
        self.files=FakeFiles();self.commands=SimpleNamespace(run=self.command);self.native={};self.config={};self.timeout=300
    @classmethod
    async def create(cls,template,**kwargs):
        if cls.fault:raise cls.fault
        cls.options.append(kwargs);s=cls(kwargs.get('metadata',{}));cls.instances[s.sandbox_id]=s;cls.created+=1;return s
    @classmethod
    async def connect(cls,sandbox_id,**kwargs):
        if cls.fault:raise cls.fault
        cls.connects.append(sandbox_id);s=cls.instances[sandbox_id];s.state='running';return s
    @classmethod
    def list(cls,**kwargs):
        # Exercise the SDK's enum serialization boundary, not just fake inventory.
        for state in kwargs.get('query').state or []:assert state.value in {'running','paused'}
        if cls.fault:raise cls.fault
        class Pages:
            has_next=False
            async def next_items(self):return list(cls.instances.values())
        return Pages()
    def get_host(self,port):return self.sandbox_id+'.test'
    async def get_info(self):return self
    async def pause(self):self.state='paused';return True
    async def kill(self):
        sid=self.sandbox_id if isinstance(self,FakeSandbox) else self
        FakeSandbox.instances.pop(sid,None);return True
    async def set_timeout(self,value):self.timeout=value
    async def command(self,cmd,**kwargs):
        if cmd=='opencode --version':return SimpleNamespace(stdout='1.16.2\n')
        if 'checkpoint.py backup' in cmd:
            self.files.data['/tmp/contract-checkpoint.tar.gz']=encoded(self.native).encode()
        if 'checkpoint.py restore' in cmd:
            self.native=json.loads(self.files.data['/tmp/contract-checkpoint.tar.gz'])
        if 'checkpoint.py log' in cmd:return SimpleNamespace(stdout=encoded({'offset':0,'text':''}))
        return SimpleNamespace(stdout='')

    def http(self,request):
        path=request.url.path;body=json.loads(request.content) if request.content else None
        if path=='/global/health':return httpx.Response(200,json={'healthy':True})
        if path in {'/global/dispose','/instance/dispose'} or path.startswith('/auth/'):return httpx.Response(200,json=True)
        if path=='/path':return httpx.Response(200,json={'worktree':'/'})
        if path=='/session' and request.method=='POST':
            sid='ses_'+secrets.token_hex(10);self.native[sid]={'id':sid,'title':'E2B 对话','messages':[],'status':{'type':'idle'},'permission':body.get('permission',[])}
            return httpx.Response(200,json={'id':sid})
        if path=='/session/status':return httpx.Response(200,json={k:v['status'] for k,v in self.native.items()})
        if path in {'/question','/permission'}:return httpx.Response(200,json=self.pending[path[1:]])
        if path.startswith(('/permission/','/question/')) and path.endswith('/reply'):
            kind,rid=path.strip('/').split('/')[:2]
            self.pending[kind]=[r for r in self.pending[kind] if r['id']!=rid]
            return httpx.Response(200,json=True)
        parts=path.strip('/').split('/');sid=parts[1];s=self.native.get(sid)
        if not s:return httpx.Response(404,json={})
        if len(parts)==2:
            if request.method=='PATCH':s.update(body)
            return httpx.Response(200,json={'id':sid,'title':s['title']})
        if parts[-1]=='todo':return httpx.Response(200,json=[])
        if parts[-1]=='message':return httpx.Response(200,json=s['messages'])
        if parts[-1]=='prompt_async':
            body.setdefault('messageID','msg_'+secrets.token_hex(10))
            now=time.time()*1000
            s['messages'].append({'info':{'id':body['messageID'],'sessionID':sid,'role':'user','time':{'created':now}},'parts':[{'id':'part_'+secrets.token_hex(8),'messageID':body['messageID'],'sessionID':sid,**body['parts'][0]}]})
            s['status']={'type':'busy'}
            if body.get('agent')=='probe':
                s['messages'].append({'info':{'id':'msg_probe','role':'assistant','time':{'completed':now}},'parts':[{'type':'text','text':'OK'}]});s['status']={'type':'idle'}
            return httpx.Response(204)
        if parts[-1]=='abort':s['status']={'type':'idle'};return httpx.Response(200,json=True)
        raise AssertionError(path)


class E2BTests(unittest.TestCase):
    login=fixtures.WorkbenchTests.login
    make_workspace=fixtures.WorkbenchTests.make_workspace
    def send(self,t,text="合同价款是多少？",**kwargs):
        response=fixtures.WorkbenchTests.send(self,t,text,**kwargs)
        if response.status_code==202:
            # Tests drive the durable worker explicitly; HTTP acceptance itself
            # no longer waits for cloud initialization.
            self.run_async(self.app.state.queue.tick(self.u,t['id']))
            body=response.json();row=self.store.one('SELECT status FROM queued_messages WHERE id=?',(body['id'],))
            return httpx.Response(202,json={**body,'status':row['status'],'queue':self.app.state.queue.state(t['id'])})
        return response
    tearDown=fixtures.WorkbenchTests.tearDown

    def setUp(self):
        fixtures.WorkbenchTests.setUp(self)
        self.cloud=self.app.state.e2b;self.cloud.enabled=True;self.cloud.sandbox_class=FakeSandbox
        FakeSandbox.instances={};FakeSandbox.created=0;FakeSandbox.connects=[];FakeSandbox.fault=None;FakeSandbox.options=[]
        # Runtime concurrency tests are independent of the trial account limiter.
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.uid,))
        self.u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        models=self.app.state.models
        saved=models.save(self.u,{'id':'test','label':'Test','base_url':'https://model.test/v1','key':'model-secret-123456','models':[{'id':'demo','label':'Demo','context':128000,'output':8192}],'revision':0})
        self.store.execute('UPDATE model_versions SET validated=1 WHERE org_id=?',(models.scope(self.u),))
        self.transport=patch.object(Runtime,'client',lambda rt,**kw:httpx.AsyncClient(base_url=rt.config['url'],transport=httpx.MockTransport(lambda r:FakeSandbox.instances[r.url.host.split('.')[0]].http(r))))
        self.transport.start();self.addCleanup(self.transport.stop)
        ready=asyncio.Event();ready.set()
        watch=patch.object(self.cloud,'watch',return_value=ready);watch.start();self.addCleanup(watch.stop)

    def run_async(self,coroutine):return asyncio.run(coroutine)

    def current(self,t):return self.store.one('SELECT * FROM threads WHERE id=?',(t['id'],))

    def sandbox(self,w):return self.cloud.handles[w['id']]

    def finish(self,w,t):
        t=self.current(t);s=self.sandbox(w).native[t['session_id']];mid='msg_'+secrets.token_hex(10)
        s['messages'].append({'info':{'id':mid,'sessionID':t['session_id'],'role':'assistant','finish':'stop','time':{'created':time.time()*1000,'completed':time.time()*1000}},'parts':[{'id':'part_'+mid,'messageID':mid,'sessionID':t['session_id'],'type':'text','text':'合同价款 128000 元。'}]})
        s['status']={'type':'idle'}
        self.run_async(self.cloud.collect_thread(self.u,t))

    def test_failed_boot_invalidates_model_revision_before_recovery(self):
        from contract_web.runtime import RuntimeError as RuntimeFailure
        w,t=self.make_workspace();self.send(t);self.finish(w,t);t=self.current(t)
        sbx=self.sandbox(w);latest,native,auth=self.cloud.catalog(self.u)
        original=Runtime.call
        async def fail_auth(rt,method,path,**kw):
            if method=='PUT' and path.startswith('/auth/'):
                raise RuntimeFailure('connection interrupted') from httpx.ReadError('closed')
            return await original(rt,method,path,**kw)
        with patch.object(Runtime,'call',fail_auth):
            with self.assertRaises(RuntimeFailure):self.run_async(self.cloud.boot(self.u,w,sbx,native,auth))
        self.assertEqual(self.cloud.binding(w['id'])['revision'],0)
        self.run_async(self.cloud.prepare(self.u,t))
        self.assertEqual(self.cloud.binding(w['id'])['revision'],latest['revision'])
        self.assertEqual(self.cloud.binding(w['id'])['status'],'ready')

    def test_full_execution_is_remembered_without_starting_a_sandbox(self):
        w,t=self.make_workspace()
        result=self.client.put('/api/threads/'+t['id']+'/permission-mode',json={'mode':'full'},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(FakeSandbox.created,0)
        self.assertEqual(self.client.get('/api/settings').json()['effective']['permission_mode'],'full')
        other=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        self.assertEqual(self.current(other)['permission_mode'],'full')
        self.send(t)
        rules=self.sandbox(w).native[self.current(t)['session_id']]['permission']
        self.assertEqual(rules,[{'permission':'*','pattern':'*','action':'allow'}])

    def test_full_execution_releases_only_current_native_permissions(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t)
        other=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        self.send(other);other=self.current(other);sbx=self.sandbox(w)
        sbx.pending['permission']=[{'id':'p1','sessionID':t['session_id'],'permission':'bash','patterns':['python convert.py']},{'id':'p2','sessionID':other['session_id'],'permission':'bash','patterns':['python other.py']}]
        sbx.pending['question']=[{'id':'q1','sessionID':t['session_id'],'questions':[]}]
        self.run_async(self.cloud.collect_thread(self.u,t))
        response=self.client.put('/api/threads/'+t['id']+'/permission-mode',json={'mode':'full'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([p['id'] for p in sbx.pending['permission']],['p2'])
        self.assertEqual([q['id'] for q in sbx.pending['question']],['q1'])
        self.assertEqual(sbx.native[t['session_id']]['permission'],[{'permission':'*','pattern':'*','action':'allow'}])
        self.assertIn({'permission':'bash','pattern':'*','action':'ask'},sbx.native[other['session_id']]['permission'])
        # The account default changes future tasks, not the other running session.
        self.assertEqual(self.current(other)['permission_mode'],'auto')

    def test_missing_key_is_visible_before_native_session_exists(self):
        w,t=self.make_workspace();self.cloud.sandbox_class=None
        with patch.dict('os.environ',{},clear=True):r=self.send(t)
        self.assertEqual(r.json()['status'],'failed',r.text)
        diagnostics=self.client.get('/api/traces/sandboxes')
        self.assertIn('E2B_API_KEY',diagnostics.text)
        self.assertTrue(self.current(t)['session_id'].startswith('pending_'))
        self.assertEqual(FakeSandbox.created,0)

    def test_cloud_send_acknowledges_durable_queue_without_waiting_for_dispatch(self):
        w,t=self.make_workspace()
        with patch.object(self.app.state.manager,'lock',side_effect=AssertionError('Acceptance must not wait for dispatch lock')):
            with patch.object(self.app.state.queue,'tick',AsyncMock(side_effect=AssertionError('HTTP must not dispatch'))) as tick:
                response=fixtures.WorkbenchTests.send(self,t,request_id='immediate-send')
                self.assertEqual(response.status_code,202,response.text)
                self.assertEqual(response.json()['status'],'queued');tick.assert_not_awaited()
                retry=fixtures.WorkbenchTests.send(self,t,request_id='immediate-send')
                self.assertEqual(retry.json()['id'],response.json()['id'])
        self.assertEqual(FakeSandbox.created,0)
        self.assertEqual(len(self.store.all('SELECT * FROM queued_messages')),1)
        self.run_async(self.app.state.queue.tick(self.u,t['id']))
        current=self.app.state.queue.state(t['id'])['current']
        self.assertEqual(current['status'],'submitted');self.assertTrue(current['message_id'])

    def test_native_sse_updates_text_directly_and_filters_other_sessions(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);sid=t['session_id']
        def emit(kind,properties):self.cloud.ingest_event(self.u,t,{'type':kind,'properties':properties})
        emit('session.updated',{'info':{'id':sid,'title':'付款条款分析'}})
        emit('session.updated',{'info':{'id':'other','title':'不属于本对话'}})
        self.assertEqual(self.cloud.snapshot(t['id'])['info']['title'],'付款条款分析')
        emit('message.updated',{'info':{'id':'streamed','sessionID':sid,'role':'assistant','time':{'created':1}}})
        emit('message.part.updated',{'part':{'id':'text1','messageID':'streamed','sessionID':sid,'type':'text','text':'金额'}})
        emit('message.part.delta',{'sessionID':sid,'messageID':'streamed','partID':'text1','field':'text','delta':'128000元'})
        emit('message.part.delta',{'sessionID':'other','messageID':'streamed','partID':'text1','field':'text','delta':'wrong'})
        self.assertEqual(self.cloud.history(t['id'])[0][-1]['parts'][0]['text'],'金额128000元')
        # A snapshot started before a native delta must not overwrite newer text.
        async def old_snapshot(*args):
            emit('message.part.delta',{'sessionID':sid,'messageID':'streamed','partID':'text1','field':'text','delta':'。'})
            return []
        with patch.object(Runtime,'messages',side_effect=old_snapshot):self.run_async(self.cloud.collect_thread(self.u,t))
        self.assertEqual(self.cloud.history(t['id'])[0][-1]['parts'][0]['text'],'金额128000元。')
        with patch.object(self.cloud,'history_changed') as notify:
            emit('message.part.delta',{'sessionID':'other','messageID':'streamed','partID':'text1','field':'text','delta':'wrong'})
            emit('message.part.updated',{'part':{'id':'reason','messageID':'streamed','sessionID':sid,'type':'reasoning','text':'hidden'}})
            notify.assert_not_called()

    def test_stream_persistence_does_not_block_other_http_requests(self):
        import threading
        w,t=self.make_workspace();self.send(t);t=self.current(t)
        entered=threading.Event();release=threading.Event()
        original=self.cloud.persist_history
        def slow(*args):
            entered.set()
            if not release.wait(3):raise AssertionError('HTTP could not run while persistence was busy')
            return original(*args)
        async def events(*args):
            yield {'type':'session.status','properties':{'sessionID':t['session_id'],'status':{'type':'busy'}}}
            await asyncio.Event().wait()
        async def check():
            started=time.monotonic();task=asyncio.create_task(self.cloud.stream(self.u,t))
            try:
                for _ in range(200):
                    if entered.is_set():break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set())
                self.assertLess(time.monotonic()-started,1,'stream persistence blocked the event loop')
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://testserver',cookies=self.client.cookies,headers=self.headers) as client:
                    paths=['/health','/api/threads/'+t['id']]
                    results=await asyncio.wait_for(asyncio.gather(*(client.get(path) for path in paths),client.post('/api/workspaces/'+w['id']+'/threads',json={}),client.post('/api/workspaces',content=b'Payment within 30 days.',headers={'X-Filename':'parallel.txt'})),1.5)
                    self.assertTrue(all(r.is_success for r in results),[r.status_code for r in results])
                    self.assertFalse(release.is_set())
            finally:
                release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)
        with patch.object(Runtime,'events',events),patch.object(self.cloud,'persist_history',slow):self.run_async(check())

    def test_model_probe_runs_in_ephemeral_e2b_and_kills_it(self):
        rows=self.app.state.models.snapshot(self.app.state.models.scope(self.u))
        result=self.run_async(self.app.state.manager.probe(rows))
        self.assertTrue(result['models'][0]['ok']);self.assertIn('E2B',result['message'])
        self.assertEqual(FakeSandbox.created,1);self.assertEqual(FakeSandbox.instances,{})
        self.assertEqual(self.store.all('SELECT * FROM e2b_bindings'),[])
        self.assertEqual(FakeSandbox.options[0]['lifecycle']['on_timeout'],'kill')

    def test_tokens_reach_viewers_while_database_save_is_blocked(self):
        import threading
        w,t=self.make_workspace();self.send(t);t=self.current(t);sid=t['session_id']
        entered=threading.Event();release=threading.Event()
        original=self.cloud.persist_history
        def slow(*args):
            entered.set()
            if not release.wait(4):raise AssertionError('Visible tokens waited for the database')
            return original(*args)
        async def native(*args):
            yield {'type':'message.updated','properties':{'info':{'id':'fast','sessionID':sid,'role':'assistant'}}}
            yield {'type':'message.part.updated','properties':{'part':{'id':'fast-text','messageID':'fast','sessionID':sid,'type':'text','text':''}}}
            while not entered.is_set():await asyncio.sleep(.005)
            for _ in range(40):
                yield {'type':'message.part.delta','properties':{'sessionID':sid,'messageID':'fast','partID':'fast-text','field':'text','delta':'快'}}
                await asyncio.sleep(.005)
            await asyncio.Event().wait()
        async def check():
            task=asyncio.create_task(self.cloud.stream(self.u,t))
            async def viewer():
                stream=self.cloud.runtime(self.u,w).events(t);updates=[]
                try:
                    async for event in stream:
                        part=event.get('properties',{}).get('part',{})
                        if part.get('id')=='fast-text':
                            updates.append(part.get('text',''))
                            if len(part.get('text',''))==40:return updates
                finally:await stream.aclose()
            try:
                a,b=await asyncio.wait_for(asyncio.gather(viewer(),viewer()),2)
                self.assertGreater(len(a),3);self.assertGreater(len(b),3)
                self.assertFalse(release.is_set())
                saved=self.store.one('SELECT messages FROM e2b_history WHERE thread_id=?',(t['id'],))
                self.assertNotIn('快',saved['messages'] if saved else '')
                self.assertEqual(self.cloud.history(t['id'])[0][-1]['parts'][0]['text'],'快'*40)
            finally:
                release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)
            self.assertIn('快'*40,self.store.one('SELECT messages FROM e2b_history WHERE thread_id=?',(t['id'],))['messages'])
            self.assertFalse(self.cloud.history_listeners[t['id']])
        with patch.object(Runtime,'events',native),patch.object(self.cloud,'persist_history',slow):self.run_async(check())

    def test_failed_background_save_retries_and_recovery_can_lose_unsaved_tail(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);sid=t['session_id']
        self.cloud.ingest_event(self.u,t,{'type':'message.updated','properties':{'info':{'id':'saved','sessionID':sid,'role':'assistant'}}})
        self.cloud.ingest_event(self.u,t,{'type':'message.part.updated','properties':{'part':{'id':'p','messageID':'saved','sessionID':sid,'type':'text','text':'已保存'}}})
        original=self.cloud.persist_history;calls=[]
        def flaky(*args):
            calls.append(1)
            if len(calls)==1:raise OSError('temporary storage failure')
            return original(*args)
        async def check():
            task=asyncio.create_task(self.cloud.persist_loop(self.u,t))
            try:
                for _ in range(160):
                    await asyncio.sleep(.01)
                    if self.cloud.saved_revisions.get(t['id'])==self.cloud.event_revisions[t['id']]:break
                self.assertGreaterEqual(len(calls),2)
                self.assertEqual(self.cloud.saved_revisions[t['id']],self.cloud.event_revisions[t['id']])
                self.assertFalse(task.done())
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
        with patch.object(self.cloud,'persist_history',flaky):self.run_async(check())
        self.cloud.ingest_event(self.u,t,{'type':'message.part.delta','properties':{'sessionID':sid,'messageID':'saved','partID':'p','field':'text','delta':'未保存尾部'}})
        self.assertEqual(self.cloud.history(t['id'])[0][-1]['parts'][0]['text'],'已保存未保存尾部')
        self.cloud.live_history.pop(t['id']) # Simulate process loss before the next save.
        self.assertEqual(self.cloud.history(t['id'])[0][-1]['parts'][0]['text'],'已保存')

    def test_live_history_redacts_secrets_and_does_not_write_per_token(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);sid=t['session_id']
        self.cloud.load_live_history(self.u,t)
        with patch.object(self.store,'execute',side_effect=AssertionError('No per-token disk writes')):
            self.cloud.ingest_event(self.u,t,{'type':'message.updated','properties':{'info':{'id':'live','sessionID':sid,'role':'assistant'}}})
            self.cloud.ingest_event(self.u,t,{'type':'message.part.updated','properties':{'part':{'id':'p','messageID':'live','sessionID':sid,'type':'text','text':'model-secret-'}}})
            self.cloud.ingest_event(self.u,t,{'type':'message.part.delta','properties':{'sessionID':sid,'messageID':'live','partID':'p','field':'text','delta':'123456'}})
        self.assertNotIn('model-secret-123456',encoded(self.cloud.history(t['id'])))
        self.cloud.persist_history(self.u,t)
        self.assertNotIn('model-secret-123456',self.store.one('SELECT messages FROM e2b_history WHERE thread_id=?',(t['id'],))['messages'])
        # An existing SSE connection also picks up credentials rotated between turns.
        self.cloud.streams[t['id']]=SimpleNamespace(done=lambda:False)
        self.cloud.stream_ready[t['id']]=asyncio.Event()
        try:
            with patch.object(self.cloud,'secrets',return_value=['rotated-private-value']):
                E2B.watch(self.cloud,self.u,t)
            self.cloud.ingest_event(self.u,t,{'type':'message.part.updated','properties':{'part':{'id':'p','messageID':'live','sessionID':sid,'type':'text','text':'rotated-private-value'}}})
            self.assertNotIn('rotated-private-value',encoded(self.cloud.history(t['id'])))
        finally:self.cloud.streams.pop(t['id'])

    def test_waiting_for_input_pauses_and_retains_request(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);sbx=self.sandbox(w)
        sbx.pending['question']=[{'id':'question1','sessionID':t['session_id'],'questions':[{'question':'请选择立场'}]}]
        self.cloud.state(w['id'],last_activity=time.time()-301)
        async def observe():
            task=asyncio.create_task(self.cloud.maintenance())
            try:
                for _ in range(100):
                    if self.cloud.binding(w['id'])['status']=='paused':return
                    await asyncio.sleep(.01)
                self.fail('Idle waiting sandbox did not pause')
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True);await self.cloud.close()
        self.run_async(observe())
        snap=self.client.get('/api/threads/'+t['id']).json()
        self.assertEqual(snap['questions'][0]['id'],'question1')
        self.assertEqual(sbx.state,'paused')

    def test_idle_event_stream_emits_changes_and_transport_heartbeats_only(self):
        w,t=self.make_workspace()
        async def observe():
            stream=self.cloud.runtime(self.u,w).events(t)
            async def cycle():
                events=[]
                async for event in stream:
                    if event['type']=='workbench.heartbeat':return events
                    events.append(event)
            try:
                with patch('contract_web.e2b_runtime.asyncio.sleep',AsyncMock()):
                    self.assertEqual([e['type'] for e in await cycle()],['todo.updated','session.status'])
                    self.assertEqual(await cycle(),[])
                    self.store.execute('INSERT INTO e2b_history VALUES(?,?,?,?)',(t['id'],'[]',encoded({'status':{'type':'busy'},'todos':[{'id':'one','status':'pending'}]}),time.time()))
                    self.assertEqual([e['type'] for e in await cycle()],['todo.updated','session.status'])
                    self.assertEqual(await cycle(),[])
                    self.store.execute('UPDATE e2b_history SET snapshot=?,synced=? WHERE thread_id=?',(encoded({'status':{'type':'idle'},'todos':[{'id':'one','status':'pending'}]}),time.time(),t['id']))
                    self.assertEqual([e['type'] for e in await cycle()],['session.status'])
            finally:await stream.aclose()
        self.run_async(observe())
        self.assertEqual(FakeSandbox.created,0)

    def test_upload_and_history_never_create_or_connect(self):
        w,t=self.make_workspace()
        self.assertEqual(w['backend'],'e2b');self.assertTrue(t['session_id'].startswith('pending_'))
        self.assertEqual(self.client.get('/api/threads/'+t['id']).status_code,200)
        self.assertEqual(self.client.get('/api/workspaces/'+w['id']+'/sandbox').json()['binding']['status'],'new')
        self.assertEqual((FakeSandbox.created,len(FakeSandbox.connects)),(0,0))
        self.login('bob');self.assertEqual(self.client.get('/api/workspaces/'+w['id']+'/sandbox').status_code,404)

    def test_attachment_shared_only_within_contract(self):
        w,t=self.make_workspace();second=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        d=self.client.post('/api/threads/'+t['id']+'/attachments',content='付款附件'.encode(),headers={**self.headers,'X-Filename':'contract.txt'}).json()
        self.assertEqual(self.client.get('/api/documents/'+d['id']+'?thread_id='+second['id']).status_code,200)
        other,ot=self.make_workspace();self.assertEqual(self.client.get('/api/documents/'+d['id']+'?thread_id='+ot['id']).status_code,404)
        self.assertEqual(FakeSandbox.created,0)

    def test_dispatch_syncs_versioned_materials_and_private_port(self):
        w,t=self.make_workspace();r=self.send(t)
        self.assertEqual(r.status_code,202,r.text);self.assertEqual(r.json()['status'],'submitted',r.text)
        sbx=self.sandbox(w);self.assertEqual(FakeSandbox.created,1)
        rules=self.run_async(self.cloud.runtime(self.u,w).permissions(t['id'],[]))
        for executable in ['python','python3']:
            self.assertIn({'permission':'bash','pattern':executable+' /opt/contract-runtime/scripts/submit.py *','action':'allow'},rules)
        self.assertFalse(FakeSandbox.options[0]['network']['allow_public_traffic'])
        self.assertEqual(FakeSandbox.options[0]['lifecycle'],{'on_timeout':'pause','auto_resume':False})
        context=json.loads(sbx.files.data['/workspace/threads/'+t['id']+'/context.json'])
        d=context['documents'][0]
        self.assertIn(d['source_hash'],d['path']);self.assertIn(d['path'],sbx.files.data)
        self.assertTrue(context['publish_script'].endswith('/submit.py'));self.assertTrue(context['execution_id'])
        self.assertFalse(any('.publish-token' in p for p in sbx.files.data))
        cfg=json.loads(sbx.files.data['/var/lib/contract-opencode/opencode.json']);self.assertIn('test',cfg['provider'])
        self.assertNotIn('model-secret',encoded(cfg))

    def test_new_dialogue_during_execution_does_not_touch_native_instance(self):
        w,t=self.make_workspace();self.send(t)
        sbx=self.sandbox(w);writes=len(sbx.files.writes)
        response=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['session_id'].startswith('pending_'))
        self.assertEqual(len(sbx.files.writes),writes)
        self.assertEqual(len(sbx.native),1)

    def test_shared_attachment_cannot_change_while_another_dialogue_runs(self):
        w,t=self.make_workspace();t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        self.send(t)
        r=self.client.post('/api/threads/'+t2['id']+'/attachments',content=b'test',headers={**self.headers,'X-Filename':'a.txt'})
        self.assertEqual(r.status_code,409,r.text)

    def test_same_workspace_parallel_and_separate_native_sessions(self):
        w,t=self.make_workspace();t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        self.assertEqual(self.send(t).json()['status'],'submitted')
        self.assertEqual(self.send(t2).json()['status'],'submitted')
        self.assertEqual(len(self.sandbox(w).native),2)
        self.assertTrue(all(s['status']['type']=='busy' for s in self.sandbox(w).native.values()))
        self.assertEqual(self.send(t,text='下一条').json()['status'],'queued')
        self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.run_async(self.app.state.queue.tick(self.u,t2['id']))
        self.assertEqual(len(self.sandbox(w).native),2);self.assertEqual(FakeSandbox.created,1)
        self.assertNotEqual(self.current(t)['session_id'],self.current(t2)['session_id'])

    def test_parallel_prepare_does_not_restart_an_older_running_environment(self):
        w,t=self.make_workspace();self.send(t)
        self.cloud.state(w['id'],started=time.time()-1200)
        t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        with patch.object(self.cloud,'pause',AsyncMock(side_effect=AssertionError('must not pause another dialogue'))), patch.object(self.cloud,'boot',AsyncMock(side_effect=AssertionError('must not restart another dialogue'))):
            self.assertEqual(self.send(t2).json()['status'],'submitted')

    def test_waiting_dialogue_does_not_prevent_parallel_renewal(self):
        w,t=self.make_workspace();self.send(t)
        t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json();self.send(t2)
        sbx=self.sandbox(w)
        sbx.pending['question']=[{'id':'question1','sessionID':self.current(t)['session_id']}]
        self.cloud.state(w['id'],last_activity=time.time()-290)
        async def check():
            with patch.object(sbx,'set_timeout',AsyncMock()) as renew, patch.object(self.cloud,'pause',AsyncMock()) as pause:
                task=asyncio.create_task(self.cloud.maintenance())
                try:
                    for _ in range(100):
                        if renew.await_count:break
                        await asyncio.sleep(.01)
                    renew.assert_awaited();pause.assert_not_awaited()
                finally:
                    task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.run_async(check())
        self.assertEqual(self.cloud.history(t2['id'])[1]['questions'],[])

    def test_long_running_dialogues_continue_without_wall_clock_abort(self):
        w,t=self.make_workspace();self.send(t)
        t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json();self.send(t2)
        self.store.execute('UPDATE execution_configs SET created=? WHERE thread_id=?',(time.time()-7200,t['id']))
        sbx=self.sandbox(w);sid=self.current(t)['session_id'];sid2=self.current(t2)['session_id']
        async def check():
            task=asyncio.create_task(self.cloud.maintenance())
            try:
                for _ in range(100):
                    if self.store.one("SELECT 1 FROM e2b_events WHERE workspace_id=? AND kind='checkpoint.saved'",(w['id'],)):break
                    await asyncio.sleep(.01)
                self.assertEqual(sbx.native[sid]['status']['type'],'busy')
                self.assertFalse(self.store.one("SELECT 1 FROM e2b_events WHERE workspace_id=? AND kind='execution.timeout'",(w['id'],)))
                self.assertEqual(sbx.native[sid2]['status']['type'],'busy')
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.run_async(check())

    def test_preparation_stages_are_exposed_in_durable_queue(self):
        w,t=self.make_workspace();stages=[];progress=self.cloud.progress
        def observe(thread,stage):
            progress(thread,stage)
            stages.append(self.app.state.queue.state(thread['id'])['current']['stage'])
        with patch.object(self.cloud,'progress',side_effect=observe):self.send(t)
        self.assertEqual(stages,['creating','starting','syncing','syncing','connecting','submitting'])

    def test_cloud_skill_listing_does_not_wait_for_busy_workspace_lock(self):
        w,t=self.make_workspace();self.send(t)
        t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
        with patch.object(self.app.state.manager,'lock',side_effect=AssertionError('listing must be read only')):
            r=self.client.post('/api/threads/'+t2['id']+'/skills/refresh',json={},headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)

    def test_permission_reply_uses_native_owner_and_skips_full_history_sync(self):
        w,t=self.make_workspace();self.send(t)
        t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json();self.send(t2)
        sid=self.current(t)['session_id'];sbx=self.sandbox(w)
        sbx.pending['permission']=[{'id':'per_test','sessionID':sid,'permission':'bash','patterns':['echo test']}]
        path='/requests/permission/per_test'
        r=self.client.post('/api/threads/'+t2['id']+path,json={'reply':'once'},headers=self.headers)
        self.assertEqual(r.status_code,404)
        with patch.object(self.cloud,'collect_thread',AsyncMock(side_effect=AssertionError('reply must not wait for full history'))):
            r=self.client.post('/api/threads/'+t['id']+path,json={'reply':'once'},headers=self.headers)
            self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(sbx.pending['permission'],[])
        self.assertEqual(self.cloud.history(t['id'])[1].get('permissions',[]),[])
        self.assertEqual(self.client.post('/api/threads/'+t['id']+path,json={'reply':'once'},headers=self.headers).status_code,404)

    def test_slow_history_in_one_dialogue_does_not_block_another_dispatch(self):
        for maintenance in (False,True):
            with self.subTest(maintenance=maintenance):
                w,t=self.make_workspace();self.send(t)
                t2=self.client.post('/api/workspaces/'+w['id']+'/threads',json={},headers=self.headers).json()
                self.assertEqual(fixtures.WorkbenchTests.send(self,t2).status_code,202)
                original=self.cloud.collect_thread
                async def check():
                    entered=asyncio.Event();release=asyncio.Event()
                    async def slow(u,thread):
                        if thread['id']==t['id']:
                            entered.set();await release.wait()
                        return await original(u,thread)
                    with patch.object(self.cloud,'collect_thread',side_effect=slow):
                        blocked=asyncio.create_task(self.cloud.maintenance() if maintenance else self.app.state.queue.tick(self.u,t['id']))
                        try:
                            await asyncio.wait_for(entered.wait(),2)
                            await asyncio.wait_for(self.app.state.queue.tick(self.u,t2['id']),2)
                            self.assertEqual(self.app.state.queue.state(t2['id'])['current']['status'],'submitted')
                            self.assertFalse(release.is_set())
                        finally:
                            release.set();blocked.cancel();await asyncio.gather(blocked,return_exceptions=True)
                self.run_async(check())

    def add_test_skill(self):
        r=self.client.post('/api/skills',json={'name':'live-guide','content':{'label':'实时指引','description':'用于更新验证','body':'请读取 references/a.md。','files':{'references/a.md':'版本一'}}},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def sync_idle_skills(self,w):
        async def run():
            task=asyncio.create_task(self.cloud.skill_sync.run())
            try:
                for _ in range(100):
                    status=next(r for r in self.cloud.skill_sync.status(self.u) if r['workspace_id']==w['id'])
                    if status['status'] in {'applied','failed'}:return status
                    await asyncio.sleep(.01)
                self.fail('skill update did not complete')
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
        return self.run_async(run())

    def test_skill_save_updates_idle_environment_without_another_query(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        execution=json.loads(self.store.one('SELECT config FROM execution_configs WHERE thread_id=?',(t['id'],))['config'])
        self.assertEqual(execution['skill_environment_revision'],self.cloud.skill_sync.row(w['id'])['revision'])
        item=self.add_test_skill();before=len(self.sandbox(w).native[self.current(t)['session_id']]['messages'])
        self.assertEqual(self.sync_idle_skills(w)['status'],'applied')
        root='/opt/contract-runtime/user-skills/'+item['name']
        self.assertEqual(self.sandbox(w).files.data[root+'/references/a.md'],b'\xe7\x89\x88\xe6\x9c\xac\xe4\xb8\x80')
        self.assertEqual(len(self.sandbox(w).native[self.current(t)['session_id']]['messages']),before)
        self.assertFalse((self.store.user_root(self.uid)/'threads'/t['id']/'.skill-versions').exists())
        self.client.delete('/api/skills/'+item['id']+'?revision=1',headers=self.headers)
        self.assertEqual(self.sync_idle_skills(w)['status'],'applied')
        self.assertNotIn(root+'/SKILL.md',self.sandbox(w).files.data)

    def test_skill_update_waits_for_all_active_dialogues(self):
        w,t=self.make_workspace();self.send(t);prior=self.cloud.skill_sync.row(w['id'])['revision']
        item=self.add_test_skill()
        self.run_async(self.cloud.skill_sync.apply(self.u,w,self.sandbox(w)))
        self.assertEqual(self.cloud.skill_sync.status(self.u)[0]['status'],'waiting')
        self.assertEqual(self.cloud.skill_sync.row(w['id'])['revision'],prior)
        self.assertNotIn(item['name'],[s['name'] for s in self.run_async(self.cloud.runtime(self.u,w).skills(t['id']))])
        self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.assertEqual(self.sync_idle_skills(w)['status'],'applied')

    def test_skill_update_does_not_wake_paused_environment(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.run_async(self.cloud.pause(self.u,w));self.add_test_skill();before=len(FakeSandbox.connects)
        self.assertEqual(self.client.get('/api/skill-environments').json()[0]['status'],'on_start')
        self.assertEqual(len(FakeSandbox.connects),before)
        self.send(t,text='恢复后的问题')
        self.assertEqual(self.cloud.skill_sync.status(self.u)[0]['status'],'applied')

    def test_skill_failure_is_visible_and_retry_preserves_scope(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.add_test_skill()
        with patch.object(self.sandbox(w).files,'write_files',AsyncMock(side_effect=OSError('test upload failure'))):
            self.assertEqual(self.sync_idle_skills(w)['status'],'failed')
        self.assertEqual(self.client.post('/api/skill-environments/retry',json={},headers=self.headers).status_code,200)
        self.assertEqual(self.sync_idle_skills(w)['status'],'applied')
        self.login('bob');self.assertEqual(self.client.get('/api/skill-environments').json(),[])

    def test_failed_preparation_is_unsent_and_withdrawal_unpauses_empty_queue(self):
        w,t=self.make_workspace()
        with patch.object(self.cloud,'prepare',AsyncMock(side_effect=RuntimeError('environment unavailable'))):
            r=self.send(t)
        q=self.app.state.queue.state(t['id']);self.assertTrue(q['paused'])
        self.assertIn('尚未发送给助手',q['items'][0]['error'])
        self.run_async(self.app.state.queue.withdraw(self.u,t['id'],r.json()['id']))
        self.assertFalse(self.app.state.queue.state(t['id'])['paused'])

    def test_cloud_resume_returns_without_waiting_for_dispatch(self):
        w,t=self.make_workspace();fixtures.WorkbenchTests.send(self,t)
        self.app.state.queue.pause(t['id'],'已停止当前运行，后续消息已暂停。')
        with patch.object(self.app.state.queue,'tick',AsyncMock(side_effect=AssertionError('resume must not wait for cloud'))):
            result=self.run_async(self.app.state.queue.resume(self.u,t['id']))
        self.assertFalse(result['paused']);self.assertEqual(result['items'][0]['status'],'queued')

    def test_health_request_is_bounded_and_prepare_renews_before_boot(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        sbx=self.sandbox(w);calls=[]
        self.cloud.renewed.clear()
        async def renew(seconds):calls.append('renew')
        async def health(rt):calls.append('health');return True
        # Linux runners may have monotonic uptime below TTL immediately after boot.
        # An absent renewal timestamp must never count as a valid warm lease.
        with patch('contract_web.e2b_runtime.time.monotonic',return_value=10),patch.object(sbx,'set_timeout',side_effect=renew),patch.object(self.cloud,'healthy',side_effect=health):
            self.run_async(self.cloud.prepare(self.u,self.current(t)))
        self.assertLess(calls.index('renew'),calls.index('health'))
        async def hanging(*args,**kwargs):await asyncio.sleep(10)
        with patch.object(Runtime,'call',side_effect=hanging):
            began=time.monotonic();self.assertFalse(self.run_async(self.cloud.healthy(self.cloud.runtime(self.u,w))))
            self.assertLess(time.monotonic()-began,4)

    def test_different_contracts_dispatch_independently(self):
        w,t=self.make_workspace();w2,t2=self.make_workspace()
        self.assertEqual(self.send(t).json()['status'],'submitted')
        self.assertEqual(self.send(t2).json()['status'],'submitted');self.assertEqual(FakeSandbox.created,2)

    def test_completed_trace_survives_pause_and_destroy(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        self.run_async(self.app.state.queue.tick(self.u,t['id']))
        before=len(FakeSandbox.connects)
        self.run_async(self.cloud.pause(self.u,w))
        rid=self.store.one('SELECT id FROM trace_runs WHERE thread_id=?',(t['id'],))['id']
        response=self.client.get('/api/traces/'+rid);self.assertEqual(response.status_code,200,response.text)
        self.assertIn('128000',response.text);self.assertIn('sandbox.pause',response.text)
        self.assertEqual(before,len(FakeSandbox.connects))
        self.run_async(self.cloud.destroy(self.u,w));self.assertEqual(self.client.get('/api/traces/'+rid).status_code,200)
        self.assertEqual(self.client.get('/api/threads/'+t['id']).status_code,200)

    def test_rebuild_restores_native_history_not_synthetic_messages(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        self.run_async(self.app.state.queue.tick(self.u,t['id']))
        original=copy.deepcopy(self.sandbox(w).native);old_id=self.sandbox(w).sandbox_id
        self.run_async(self.cloud.destroy(self.u,w))
        self.assertEqual(self.send(t,'继续读取金额').json()['status'],'submitted')
        new=self.sandbox(w);self.assertNotEqual(new.sandbox_id,old_id)
        sid=self.current(t)['session_id'];self.assertEqual(new.native[sid]['messages'][:2],original[sid]['messages'])

    def test_background_checkpoint_failure_is_visible_and_retry_does_not_replay(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        original=copy.deepcopy(self.sandbox(w).native)
        self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.assertFalse(self.app.state.queue.state(t['id'])['active'])
        self.assertIn(w['id'],self.cloud.pending_checkpoints)
        async def cycle(fail):
            with patch.object(self.cloud,'checkpoint',AsyncMock(side_effect=OSError('archive unavailable')) if fail else AsyncMock()) as save:
                task=asyncio.create_task(self.cloud.maintenance())
                try:
                    for _ in range(100):
                        if save.await_count:break
                        await asyncio.sleep(.01)
                    await asyncio.sleep(.01)
                finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.run_async(cycle(True))
        self.assertTrue(self.store.one("SELECT 1 FROM e2b_events WHERE workspace_id=? AND kind='sync.failed'",(w['id'],)))
        self.assertIn(w['id'],self.cloud.pending_checkpoints)
        self.run_async(cycle(False))
        self.assertNotIn(w['id'],self.cloud.pending_checkpoints)
        self.assertEqual(self.sandbox(w).native,original)

    def test_connection_error_does_not_create_replacement(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.run_async(self.cloud.pause(self.u,w));FakeSandbox.fault=OSError('network unavailable')
        with self.assertRaises(OSError):self.run_async(self.cloud.prepare(self.u,self.current(t)))
        self.assertEqual(FakeSandbox.created,1)

    def test_reconcile_observes_paused_without_waking(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);self.run_async(self.app.state.queue.tick(self.u,t['id']))
        self.run_async(self.cloud.pause(self.u,w));before=len(FakeSandbox.connects)
        self.run_async(self.cloud.reconcile());self.assertEqual(before,len(FakeSandbox.connects))
        self.assertEqual(self.cloud.binding(w['id'])['status'],'paused')

    def test_collector_is_idempotent_and_acknowledges_only_saved_bytes(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);sbx=self.sandbox(w)
        eid=self.store.one('SELECT id FROM execution_configs WHERE thread_id=?',(t['id'],))['id']
        report={'kind':'document','title':'调试文件','format':'txt','content':'验收后 30 日付款','source_hash':w.get('source_hash') or self.store.one('SELECT source_hash FROM documents WHERE id=?',(w['document_id'],))['source_hash']}
        req={'request_id':'a'*64,'thread_id':t['id'],'execution_id':eid,'report':report};path='/workspace/exchange/'+'a'*64+'.request.json'
        sbx.files.data[path]=encoded(req).encode()
        self.run_async(self.cloud.collect_submissions(self.u,w,sbx))
        receipt=json.loads(sbx.files.data['/workspace/exchange/'+'a'*64+'.receipt.json'])
        self.assertTrue(receipt.get('saved'),receipt)
        self.assertEqual(self.client.get('/api/artifacts/'+receipt['artifact_id']+'/file?format=txt').text,report['content'])
        sbx.files.data[path]=encoded(req).encode();self.run_async(self.cloud.collect_submissions(self.u,w,sbx))
        self.assertEqual(len(self.store.all('SELECT * FROM artifacts')),1)
        req['report']['content']='changed';sbx.files.data[path]=encoded(req).encode()
        with self.assertRaises(Exception):self.run_async(self.cloud.collect_submissions(self.u,w,sbx))
        self.assertEqual(len(self.store.all('SELECT * FROM artifacts')),1)

    def test_redline_working_files_and_attachment_exports_are_not_shared(self):
        w,t=self.make_workspace()
        root=self.store.user_root(self.uid)
        private=root/'sources'/w['document_id']/'redline';private.mkdir();(private/'working-native-secret.docx').write_bytes(b'private working bytes')
        self.store.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',('attached-redline',self.uid,w['id'],t['id'],'private.docx','.docx','private-hash'))
        out=root/'published'/'private-redline';out.mkdir(parents=True)
        (out/'content.docx').write_bytes(b'private exported bytes')
        (out/'report.json').write_text(encoded({'redline':True,'document_id':'attached-redline','format':'docx'}))
        self.store.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',('private-redline',w['id'],t['id'],'document','附件修订','export-hash','private-hash',time.time()))
        self.send(t);t=self.current(t);sbx=self.sandbox(w)
        self.assertFalse(any('working-native-secret' in p or '/published/private-redline/' in p for p in sbx.files.data))
        self.assertTrue(any(p.startswith('/workspace/input/') for p in sbx.files.data))

    def test_sync_is_incremental_and_removes_deleted_source(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);sbx=self.sandbox(w)
        before=len(sbx.files.writes);self.run_async(self.cloud.sync_files(self.u,t));self.assertEqual(before,len(sbx.files.writes))
        self.store.execute('DELETE FROM documents WHERE id=?',(w['document_id'],))
        self.run_async(self.cloud.sync_files(self.u,t))
        self.assertFalse(any(p.startswith('/workspace/input/') for p in sbx.files.data))

    def test_history_and_diagnostics_redact_credentials(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t);s=self.sandbox(w).native[t['session_id']]
        s['messages'][0]['parts'][0]['text']='model-secret-123456 traffic-secret-12345'
        self.run_async(self.cloud.collect_thread(self.u,t))
        self.cloud.record(w['id'],'test',{'message':'model-secret-123456 traffic-secret-12345'})
        data=self.client.get('/api/threads/'+t['id']).text+self.client.get('/api/workspaces/'+w['id']+'/sandbox').text
        self.assertNotIn('model-secret-123456',data);self.assertNotIn('traffic-secret-12345',data)


    def test_warm_prepare_skips_remote_checks_and_checkpoint_lock(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        sbx=self.sandbox(w)
        self.cloud.state(w['id'],error='background log download temporarily failed')
        async def check():
            async with self.cloud.manager.lock('e2b-'+w['id']):
                with patch.object(sbx,'get_info',AsyncMock(side_effect=AssertionError('inventory'))),patch.object(sbx,'set_timeout',AsyncMock(side_effect=AssertionError('renew'))),patch.object(self.cloud,'healthy',AsyncMock(side_effect=AssertionError('health'))),patch.object(self.cloud.skill_sync,'apply',AsyncMock(side_effect=AssertionError('skills'))),patch.object(self.cloud,'sync_files',AsyncMock(side_effect=AssertionError('files'))):
                    await asyncio.wait_for(self.cloud.prepare(self.u,self.current(t)),.2)
        self.run_async(check())

    def test_warm_turn_uploads_only_context_and_reuses_permissions(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        self.run_async(self.app.state.queue.tick(self.u,t['id']))
        sbx=self.sandbox(w);sbx.files.writes.clear();calls=[];original=sbx.http
        def record(request):
            calls.append((request.method,request.url.path))
            return original(request)
        with patch.object(sbx,'http',side_effect=record),patch.object(Path,'rglob',side_effect=AssertionError('no recursive scan')):
            result=self.send(t,'继续')
        self.assertEqual(result.json()['status'],'submitted',result.text)
        self.assertEqual([Path(p).name for p in sbx.files.writes],['context.json'])
        self.assertNotIn(('GET','/path'),calls)
        self.assertFalse(any(method=='PATCH' for method,path in calls))

    def test_warm_new_thread_has_fixed_skill_config(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        other=self.client.post(f'/api/workspaces/{w["id"]}/threads',json={},headers=self.headers).json()
        self.assertEqual(self.send(other).json()['status'],'submitted')
        remote=self.cloud.runtime(self.u,w).directory(other['id'])+'/opencode.json'
        self.assertIn('/opt/contract-runtime/user-skills',self.sandbox(w).files.data[remote].decode())

    def test_attachment_is_synced_before_send_and_unchanged_source_is_not_reuploaded(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t)
        self.run_async(self.app.state.queue.tick(self.u,t['id']))
        response=self.client.post(f'/api/threads/{t["id"]}/attachments',content='新附件，金额42元'.encode(),headers={**self.headers,'X-Filename':'new.txt'})
        self.assertEqual(response.status_code,200,response.text)
        sbx=self.sandbox(w)
        self.assertTrue(any('/'+response.json()['id']+'/' in path for path in sbx.files.data))
        sbx.files.writes.clear()
        self.assertEqual(self.send(t,'读新附件').json()['status'],'submitted')
        self.assertFalse(any(p.startswith('/workspace/input/') for p in sbx.files.writes))

    def test_cancel_then_new_query_dispatches_without_pending_queue_card(self):
        w,t=self.make_workspace();self.send(t)
        result=self.client.post(f'/api/threads/{t["id"]}/abort',json={},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        queue=self.app.state.queue.state(t['id'])
        self.assertFalse(queue['active']);self.assertFalse(queue['paused']);self.assertEqual(queue['items'],[])
        self.assertEqual(self.send(t,'取消后新问题').json()['status'],'submitted')
        messages=self.sandbox(w).native[self.current(t)['session_id']]['messages']
        self.assertEqual(messages[-1]['parts'][0]['text'],'取消后新问题')


class CheckpointTests(unittest.TestCase):
    def test_live_wal_backup_restore_and_credential_exclusion(self):
        import importlib.util
        import sqlite3
        import tempfile
        spec=importlib.util.spec_from_file_location('checkpoint',Path(__file__).parents[1]/'runtime/scripts/checkpoint.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source';dest=Path(tmp)/'restored';archive=Path(tmp)/'state.tar.gz'
            data=root/'var/lib/contract-opencode/data/opencode';data.mkdir(parents=True)
            (root/'workspace/threads/t').mkdir(parents=True)
            (root/'workspace/threads/t/draft.md').write_text('saved draft')
            (data/'auth.json').write_text('PRIVATE_AUTH')
            with sqlite3.connect(data/'opencode.db') as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE messages(id TEXT PRIMARY KEY, content TEXT)')
                db.execute("INSERT INTO messages VALUES('native-id','native answer')");db.commit()
                module.backup(root,archive)
            dest.mkdir();module.restore(dest,archive)
            with sqlite3.connect(dest/'var/lib/contract-opencode/data/opencode/opencode.db') as db:
                self.assertEqual(db.execute('SELECT * FROM messages').fetchone(),('native-id','native answer'))
            self.assertFalse((dest/'var/lib/contract-opencode/data/opencode/auth.json').exists())
            self.assertEqual((dest/'workspace/threads/t/draft.md').read_text(),'saved draft')

    def test_restore_rejects_paths_outside_sandbox_roots(self):
        import importlib.util
        import tarfile
        import io
        import tempfile
        spec=importlib.util.spec_from_file_location('checkpoint',Path(__file__).parents[1]/'runtime/scripts/checkpoint.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'unsafe.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                item=tarfile.TarInfo('../../escape');item.size=1;tar.addfile(item,io.BytesIO(b'x'))
            with self.assertRaises(ValueError):module.restore(Path(tmp),archive)
