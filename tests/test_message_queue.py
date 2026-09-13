import asyncio
import test_workbench as fixtures
from contract_web.message_queue import MessageQueue

class MessageQueueTests(fixtures.WorkbenchTests):
    def tick(self,t):
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        asyncio.run(self.app.state.queue.tick(u,t['id']))
    def queue(self,t):return self.client.get(f'/api/threads/{t["id"]}/queue').json()
    def withdraw(self,t,qid):return self.client.delete(f'/api/threads/{t["id"]}/queue/{qid}',headers=self.headers)

    def test_fifo_withdraw_dedup(self):
        _,t=self.make_workspace();first=self.send(t,'第一条').json()
        second=self.send(t,'第二条',request_id='second').json();self.send(t,'第三条')
        again=self.send(t,'第二条',request_id='second').json()
        self.assertEqual(second['id'],again['id'])
        self.assertEqual([m['body']['text'] for m in self.queue(t)['items']],['第二条','第三条'])
        self.assertEqual(len(self.native(t)['messages']),1)
        self.assertEqual(self.withdraw(t,first['id']).status_code,409)
        recovered=self.withdraw(t,second['id']).json()
        self.assertEqual(recovered['body']['text'],'第二条')
        self.assertEqual(self.withdraw(t,second['id']).json()['body'],recovered['body'])
        self.send(t,'第二条修改版');self.finish(t);self.tick(t)
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'第三条')
        self.finish(t);self.tick(t)
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'第二条修改版')
        self.finish(t);self.tick(t)
        self.assertFalse(self.queue(t)['active']);self.assertEqual(self.queue(t)['items'],[])
        before=len(self.native(t)['messages']);self.send(t,'第二条',request_id='second')
        self.assertEqual(len(self.native(t)['messages']),before)

    def test_native_id_is_created_on_dispatch_and_sorts_after_prior_answer(self):
        from unittest.mock import patch
        _,t=self.make_workspace()
        first=self.send(t,'第一条').json()
        pending=self.send(t,'第二条').json()
        self.assertEqual(self.store.one('SELECT message_id FROM queued_messages WHERE id=?',(pending['id'],))['message_id'],'')
        self.finish(t)
        import time
        now=time.time()+60
        with patch('contract_web.message_queue.time.time',return_value=now):self.tick(t)
        mid=self.native(t)['messages'][-1]['info']['id']
        self.assertEqual(len(mid),30)
        self.assertEqual(mid[4:16],format((int(now*1000)*4096)&((1<<48)-1),'012x'))
        self.assertLess(self.native(t)['messages'][0]['info']['id'],mid)

    def test_owned_even_for_admin_and_model_frozen(self):
        _,t=self.make_workspace();self.send(t);pending=self.send(t,'独立消息',model='glm/glm-test').json()
        self.login('bob');self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.get(f'/api/threads/{t["id"]}/queue').status_code,404)
        self.assertEqual(self.withdraw(t,pending['id']).status_code,404)
        self.login('alice');self.finish(t);self.tick(t)
        call=fixtures.FakeRuntime.servers['http://alice']['calls'][-1]
        self.assertEqual(call[3]['model'],{'providerID':'glm','modelID':'glm-test'})

    def test_native_question_blocks_even_when_idle(self):
        _,t=self.make_workspace();self.send(t);self.send(t,'后续');self.finish(t)
        requests=fixtures.FakeRuntime.servers['http://alice']['requests']
        requests['question']=[{'id':'question','sessionID':t['session_id']}]
        self.tick(t);self.assertEqual(len(self.native(t)['messages']),2)
        requests['question']=[];self.tick(t)
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'后续')

    def test_stop_and_error_pause_until_resume(self):
        _,t=self.make_workspace();self.send(t);self.send(t,'后续')
        self.client.post(f'/api/threads/{t["id"]}/abort',headers=self.headers)
        self.finish(t,{'name':'MessageAbortedError'});self.tick(t)
        self.assertTrue(self.queue(t)['paused']);self.assertEqual(len(self.native(t)['messages']),2)
        r=self.client.post(f'/api/threads/{t["id"]}/queue/resume',json={},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'后续')

    def test_cancel_capacity_retry_preserves_queue_and_owner_boundary(self):
        _,t=self.make_workspace();self.send(t);pending=self.send(t,'保留后续消息').json()
        self.native(t)['status']={'type':'retry','attempt':2,'next':9999999999999,
            'message':'Free model capacity is limited right now. Retry shortly.'}
        self.login('bob')
        self.assertEqual(self.client.post(f'/api/threads/{t["id"]}/abort',headers=self.headers).status_code,404)
        self.assertEqual(self.native(t)['status']['type'],'retry')
        self.login('alice')
        response=self.client.post(f'/api/threads/{t["id"]}/abort',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.native(t)['status']['type'],'idle')
        self.finish(t,{'name':'MessageAbortedError'});self.tick(t);self.tick(t)
        self.assertTrue(self.queue(t)['paused'])
        self.assertFalse(self.queue(t)['active'])
        self.assertEqual(self.queue(t)['items'][0]['id'],pending['id'])
        self.assertEqual(sum(m['info']['role']=='user' for m in self.native(t)['messages']),1)

    def test_worker_restart_does_not_duplicate(self):
        _,t=self.make_workspace();self.send(t);self.send(t,'恢复后发送')
        old=self.app.state.queue
        self.app.state.queue=MessageQueue(self.store,old.manager,old.runtime,old.thread,old.dispatch)
        self.finish(t);self.tick(t);self.tick(t)
        self.assertEqual(sum(m['info']['role']=='user' for m in self.native(t)['messages']),2)
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'恢复后发送')

    def test_uncertain_dispatch_not_replayed(self):
        _,t=self.make_workspace();self.send(t);pending=self.send(t,'不确定消息').json();self.finish(t);self.tick(t)
        mid=self.store.one('SELECT message_id FROM queued_messages WHERE id=?',(pending['id'],))['message_id']
        self.native(t)['messages']=[m for m in self.native(t)['messages'] if m['info']['id']!=mid]
        self.native(t)['status']={'type':'idle'}
        self.store.execute("UPDATE queued_messages SET status='dispatching' WHERE id=?",(pending['id'],));self.tick(t);self.tick(t)
        self.assertTrue(self.queue(t)['paused']);self.assertEqual(self.queue(t)['items'][0]['status'],'failed')
        self.assertEqual(sum(m['info']['role']=='user' for m in self.native(t)['messages']),1)

    def test_withdraw_dispatch_race_one_winner(self):
        _,t=self.make_workspace();self.send(t);pending=self.send(t,'竞争消息').json();self.finish(t)
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));q=self.app.state.queue
        async def race():return await asyncio.gather(q.tick(u,t['id']),q.withdraw(u,t['id'],pending['id']),return_exceptions=True)
        asyncio.run(race())
        row=self.store.one('SELECT status FROM queued_messages WHERE id=?',(pending['id'],))
        count=sum(m['parts'][0].get('text')=='竞争消息' for m in self.native(t)['messages'])
        self.assertIn((row['status'],count),{('submitted',1),('withdrawn',0)})

    def test_changed_materials_pause_with_error(self):
        w,t=self.make_workspace();self.send(t);self.send(t,'旧材料请求');self.send(t,'第三条');self.finish(t)
        self.store.execute('UPDATE documents SET source_hash=? WHERE id=?',('changed',w['document_id']));self.tick(t)
        state=self.queue(t);self.assertTrue(state['paused']);self.assertIn('材料已变化',state['items'][0]['error'])
        self.assertEqual(len(self.native(t)['messages']),2)
        self.assertEqual(self.client.post(f'/api/threads/{t["id"]}/queue/resume',json={},headers=self.headers).status_code,409)

    def test_withdraw_does_not_wait_for_dispatch_lock(self):
        _,t=self.make_workspace()
        self.send(t,'运行中')
        pending=self.send(t,'等待中').json()
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        async def check():
            async with self.app.state.queue.manager.lock(u['id']):
                result=await asyncio.wait_for(self.app.state.queue.withdraw(u,t['id'],pending['id']),0.2)
                self.assertEqual(result['body']['text'],'等待中')
        asyncio.run(check())

    def test_fresh_send_resumes_empty_error_or_cancel_queue_but_preserves_pending(self):
        _,t=self.make_workspace();self.send(t);self.finish(t,{'name':'APIError'});self.tick(t)
        self.assertTrue(self.queue(t)['resume_on_send'])
        self.send(t,'继续')
        self.assertFalse(self.queue(t)['paused'])
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'继续')
        self.send(t,'原队列');self.finish(t,{'name':'APIError'});self.tick(t)
        self.send(t,'新消息')
        self.assertTrue(self.queue(t)['paused'])
        self.assertEqual([r['body']['text'] for r in self.queue(t)['items']],['原队列','新消息'])
        _,other=self.make_workspace()
        self.app.state.queue.pause(other['id'],'已停止当前运行，后续消息已暂停。')
        self.send(other,'取消后继续')
        self.assertFalse(self.queue(other)['paused'])

    def test_cancel_then_send_does_not_wait_for_cancelled_native_answer(self):
        _,t=self.make_workspace();first=self.send(t).json()
        response=self.client.post(f'/api/threads/{t["id"]}/abort',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.queue(t)['active']);self.assertFalse(self.queue(t)['paused'])
        self.assertEqual(self.store.one('SELECT status FROM queued_messages WHERE id=?',(first['id'],))['status'],'cancelled')
        self.send(t,'新指令')
        self.assertEqual(self.native(t)['messages'][-1]['parts'][0]['text'],'新指令')
        self.assertEqual(self.queue(t)['items'],[])

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(MessageQueueTests):setattr(MessageQueueTests,_name,None)
