"""Durable per-thread outbox. OpenCode remains the owner of executed messages."""
import asyncio
import json
import secrets
import time

from fastapi import HTTPException
from .settings import encoded
from .traces import redact


ERROR_PAUSES=('上一条消息未正常完成，确认后可继续队列。','有消息未能发送，后续消息已暂停。',
              '发送结果未确认，后续消息已暂停。','原生运行已中断，后续消息已暂停。','已停止当前运行，后续消息已暂停。')

class MessageQueue:
    def __init__(self, store, manager, runtime, thread, dispatch):
        self.store, self.manager = store, manager
        self.runtime, self.thread, self.dispatch = runtime, thread, dispatch
        self.task = None
        self.observers = {}
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS queued_messages (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                  thread_id TEXT NOT NULL, user_id TEXT NOT NULL, request_id TEXT NOT NULL,
                  body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                  message_id TEXT NOT NULL, error TEXT, created REAL NOT NULL,
                  UNIQUE(user_id,thread_id,request_id));
                CREATE INDEX IF NOT EXISTS queue_thread ON queued_messages(thread_id,status,seq);
                CREATE TABLE IF NOT EXISTS queue_state (
                  thread_id TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0, reason TEXT);
            ''')

        with store.connect() as db:
            if 'stage' not in {r[1] for r in db.execute('PRAGMA table_info(queued_messages)')}:
                db.execute('ALTER TABLE queued_messages ADD COLUMN stage TEXT')

    def state(self, tid):
        row = self.store.one('SELECT * FROM queue_state WHERE thread_id=?', (tid,))
        rows = self.store.all("SELECT * FROM queued_messages WHERE thread_id=? AND status IN ('queued','dispatching','submitted','failed') ORDER BY seq", (tid,))
        current=next((r for r in rows if r['status'] in {'dispatching','submitted'}),None)
        def public(r):
            return {'id':r['id'],'request_id':r['request_id'],'message_id':r['message_id'],'status':r['status'],'body':json.loads(r['body']),'error':r['error'],'created':r['created'],'stage':r['stage']}
        return {'current':public(current) if current else None,'paused':bool(row and row['paused']), 'reason':row['reason'] if row else None,
                'resume_on_send':bool(row and row['paused'] and row['reason'] in ERROR_PAUSES and not rows),
                'active':any(r['status'] in {'dispatching','submitted'} for r in rows),
                'items':[public(r) for r in rows if r['status'] in {'queued','failed'}]}

    def pause(self, tid, reason):
        self.store.execute('INSERT INTO queue_state VALUES(?,1,?) ON CONFLICT(thread_id) DO UPDATE SET paused=1,reason=excluded.reason', (tid,reason))

    def activities(self, wid):
        """One lightweight query, without loading queued prompts or history."""
        rows = self.store.all('''SELECT summary.*,q.id,q.status FROM (
            SELECT q.thread_id,MAX(q.seq) AS seq,
              MAX(q.status IN ('dispatching','submitted')) AS active,
              MAX(q.status IN ('queued','failed')) AS pending
            FROM queued_messages q JOIN threads t ON t.id=q.thread_id
            WHERE t.workspace_id=? AND t.deleted_at IS NULL GROUP BY q.thread_id
        ) summary JOIN queued_messages q ON q.seq=summary.seq''', (wid,))
        return {row['thread_id']: row for row in rows}

    def enqueue(self, u, tid, body):
        request_id = body.pop('request_id', None) or secrets.token_hex(16)
        if not isinstance(request_id,str) or not 1 <= len(request_id) <= 100:
            raise HTTPException(422,'消息标识无效')
        old=self.store.one('SELECT * FROM queued_messages WHERE user_id=? AND thread_id=? AND request_id=?',(u['id'],tid,request_id))
        if old:
            if old['body'] != encoded(body):raise HTTPException(409,'这条消息已提交，请刷新后重新发送')
            return old['id']
        qid=secrets.token_hex(12)
        mid=''  # Allocate the native ID only when this item is dispatched.
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute('SELECT * FROM queued_messages WHERE user_id=? AND thread_id=? AND request_id=?',(u['id'],tid,request_id)).fetchone()
            if old:
                if old['body'] != encoded(body):raise HTTPException(409,'这条消息已提交，请刷新后重新发送')
                return old['id']
            if hasattr(self,"accounts"):self.accounts.reserve(db,u,qid,body)
            db.execute("""UPDATE queue_state SET paused=0,reason=NULL
                WHERE thread_id=? AND paused=1 AND reason IN (?,?,?,?,?)
                AND NOT EXISTS(SELECT 1 FROM queued_messages WHERE thread_id=?
                    AND status IN ('queued','failed','dispatching','submitted'))""",
                (tid,*ERROR_PAUSES,tid))
            db.execute('INSERT INTO queued_messages(id,thread_id,user_id,request_id,body,message_id,created) VALUES(?,?,?,?,?,?,?)',
                       (qid,tid,u['id'],request_id,encoded(body),mid,time.time()))
        return qid

    async def withdraw(self,u,tid,qid):
        self.thread(u,tid)
        row=self.store.one('SELECT * FROM queued_messages WHERE id=? AND user_id=? AND thread_id=?',(qid,u['id'],tid))
        if not row:raise HTTPException(404,'排队消息不存在')
        if row['status'] not in {'queued','failed','withdrawn'}:
            raise HTTPException(409,'这条消息已经开始执行，无法撤回；可以停止当前运行')
        with self.store.connect() as db:
            changed=db.execute("UPDATE queued_messages SET status='withdrawn' WHERE id=? AND status IN ('queued','failed','withdrawn')",(qid,)).rowcount
        if not changed:raise HTTPException(409,'这条消息已经开始执行，无法撤回；可以停止当前运行')
        if hasattr(self,'accounts'):self.accounts.finish(qid,True)
        state=self.state(tid)
        if not state['items'] and not state['active'] and state['paused'] and state['reason']=='有消息未能发送，后续消息已暂停。':
            self.store.execute('UPDATE queue_state SET paused=0,reason=NULL WHERE thread_id=?',(tid,))
        return {'body':json.loads(row['body']), 'queue':self.state(tid)}

    async def resume(self,u,tid):
        async with self.manager.lock('queue-thread-'+tid if self.runtime(u,tid).config.get('e2b') else u['id']):
            self.thread(u,tid)
            if self.store.one("SELECT 1 FROM queued_messages WHERE thread_id=? AND status='failed'",(tid,)):
                raise HTTPException(409,'请先撤回并编辑未能发送的消息，再继续队列')
            self.store.execute('UPDATE queue_state SET paused=0,reason=NULL WHERE thread_id=?',(tid,))
        if not self.runtime(u,tid).config.get('e2b'):await self.tick(u,tid)
        return self.state(tid)

    async def tick(self,u,tid):
        # Each cloud dialogue serializes dispatch; withdrawal uses a local atomic claim.
        async with self.manager.lock('queue-thread-'+tid if self.runtime(u,tid).config.get('e2b') else u['id']):
            fresh=self.store.one('SELECT * FROM users WHERE id=? AND active=1',(u['id'],))
            if not fresh:return
            u=fresh;t=self.thread(u,tid);rt=self.runtime(u,tid)
            rows=self.store.all("SELECT * FROM queued_messages WHERE thread_id=? AND status IN ('queued','dispatching','submitted','failed') ORDER BY seq",(tid,))
            if not rows:return
            row=rows[0]
            cloud=rt.config.get('e2b')
            if cloud:
                b=self.manager.e2b.binding(t['workspace_id'])
                if row['status'] in {'dispatching','submitted'}:
                    if b and b['status']=='paused':return
                    if t['workspace_id'] not in self.manager.e2b.handles:
                        rt=await self.manager.e2b.prepare(u,t,recovering=True)
                    if not self.manager.e2b.stream_ready.get(tid,asyncio.Event()).is_set():
                        await self.manager.e2b.collect_thread(u,t)
                    rt=self.runtime(u,tid)
            status,questions,permissions=await asyncio.gather(rt.status(t),rt.call('GET','/question',tid=tid),rt.call('GET','/permission',tid=tid))
            if status['type']!='idle' or any(q.get('sessionID')==t['session_id'] for q in questions+permissions):return
            if row['status'] in {'dispatching','submitted'}:
                messages=await rt.messages(t)
                start=next((i for i,m in enumerate(messages) if m['info']['id']==row['message_id']),None)
                if start is None:
                    # An interrupted dispatch has an uncertain outcome. Never
                    # automatically repeat a request that may already have run.
                    elapsed=self.store.one('SELECT created FROM execution_configs WHERE thread_id=? ORDER BY created DESC LIMIT 1',(tid,))
                    if row['status']=='dispatching' or (cloud and elapsed and time.time()-elapsed['created']>30):
                        self.store.execute("UPDATE queued_messages SET status='failed',error=? WHERE id=?",('发送结果未确认，请检查对话后撤回重发',row['id']))
                        self.pause(tid,'发送结果未确认，后续消息已暂停。')
                    return
                answers=[m['info'] for m in messages[start+1:] if m['info']['role']=='assistant']
                if not answers or not answers[-1].get('time',{}).get('completed'):
                    elapsed=self.store.one('SELECT created FROM execution_configs WHERE thread_id=? ORDER BY created DESC LIMIT 1',(tid,))
                    if cloud and elapsed and time.time()-elapsed['created']>30:
                        self.store.execute("UPDATE queued_messages SET status='failed',error=? WHERE id=?",('原生运行已中断，已保存历史保留；请确认后继续',row['id']))
                        self.pause(tid,'原生运行已中断，后续消息已暂停。')
                    return
                last=answers[-1]
                if last.get('finish') in {'tool-calls','unknown'} and not last.get('error'):return
                if cloud:
                    async with self.manager.lock('e2b-'+t['workspace_id']):
                        await self.manager.e2b.collect_submissions(u,self.store.one('SELECT * FROM workspaces WHERE id=?',(t['workspace_id'],)),self.manager.e2b.handles[t['workspace_id']])
                        self.manager.e2b.pending_checkpoints.add(t['workspace_id'])
                self.store.execute("UPDATE queued_messages SET status='completed',error=NULL WHERE id=?",(row['id'],))
                if last.get('error') or last.get('finish') in {'length','content-filter','content_filter'}:
                    self.pause(tid,'上一条消息未正常完成，确认后可继续队列。')
                if hasattr(self,'accounts'):self.accounts.finish(row['id'],bool(last.get('error')))
                rows=rows[1:]
                if cloud or not rows:return
                row=rows[0]
            if self.state(tid)['paused'] or row['status']=='failed':return
            # Legacy/in-flight turns do not have an outbox entry. Respect their
            # final error as well as native status before starting queued work.
            messages=await rt.messages(t)
            if messages:
                last=messages[-1]['info']
                previous_user=next((m['info']['id'] for m in reversed(messages) if m['info']['role']=='user'),None)
                cancelled=self.store.one("SELECT 1 FROM queued_messages WHERE thread_id=? AND message_id=? AND status='cancelled'",(tid,previous_user))
                if not cancelled and (last['role']=='user' or (last['role']=='assistant' and not last.get('time',{}).get('completed'))):return
            # OpenCode 1.16.2 Identifier.create: six timestamp bytes, then
            # fourteen random characters. Native completion compares these IDs;
            # an enqueue-time ID could sort before the preceding answer.
            stamp=(int(time.time()*1000)*0x1000) & ((1 << 48)-1)
            row['message_id']='msg_'+format(stamp,'012x')+secrets.token_hex(7)
            # Only reserve the turn under the workspace mutation gate. Remote
            # observation and dispatch must never hold this cross-dialogue lock.
            async with self.manager.lock('queue-'+t['workspace_id'] if cloud else 'queue-claim-'+tid):
                self.thread(u,tid)
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if hasattr(self,'accounts') and not self.accounts.claim(db,row['id']):return
                    claimed=db.execute("UPDATE queued_messages SET status='dispatching',stage='checking',message_id=? WHERE id=? AND status='queued'",(row['message_id'],row['id'])).rowcount
                if not claimed:return
            try:
                if cloud:
                    self.manager.e2b.record(t['workspace_id'],'execution.start',{'queue_id':row['id']},tid)
                await self.dispatch(u,tid,json.loads(row['body']),row['message_id'])
            except Exception as exc:
                message=redact(str(getattr(exc,'detail',exc)))[:800]
                stage=self.store.one('SELECT stage FROM queued_messages WHERE id=?',(row['id'],))['stage']
                if cloud and stage!='submitting':
                    message='尚未发送给助手：'+message
                elif not isinstance(exc,(HTTPException,ValueError)):
                    message='提交结果未确认，请先检查对话，避免重复发送。'+message
                self.store.execute("UPDATE queued_messages SET status='failed',error=? WHERE id=?",(message,row['id']))
                if cloud:self.manager.e2b.record(t['workspace_id'],'execution.failed',{'error':message},tid)
                if hasattr(self,'accounts'):self.accounts.finish(row['id'],stage!='submitting')
                self.pause(tid,'有消息未能发送，后续消息已暂停。')
                return
            self.store.execute("UPDATE queued_messages SET status='submitted' WHERE id=?",(row['id'],))

    async def start(self):
        async def work():
            while True:
                rows=self.store.all("SELECT DISTINCT user_id,thread_id FROM queued_messages WHERE status IN ('queued','dispatching','submitted')")
                async def observe(row):
                    u=self.store.one('SELECT * FROM users WHERE id=? AND active=1',(row['user_id'],))
                    if not u:return
                    try:await self.tick(u,row['thread_id'])
                    except Exception as exc:
                        # Retry observation, never blind dispatch. Keep cloud
                        # synchronization failures visible even without a browser.
                        t=self.store.one('SELECT * FROM threads WHERE id=?',(row['thread_id'],))
                        e2b=getattr(self.manager,'e2b',None)
                        if t and e2b and self.runtime(u,t['id']).config.get('e2b'):
                            from .traces import redact
                            message=redact(str(exc),e2b.secrets(u,t['workspace_id']))
                            active=self.store.one("SELECT id,error FROM queued_messages WHERE thread_id=? AND status IN ('dispatching','submitted') ORDER BY seq LIMIT 1",(t['id'],))
                            if active and active['error']!=message:
                                self.store.execute('UPDATE queued_messages SET error=? WHERE id=?',(message,active['id']))
                                e2b.record(t['workspace_id'],'queue.sync_failed',{'error':message},t['id'])
                for row in rows:
                    prior=self.observers.get(row['thread_id'])
                    if not prior or prior.done():
                        self.observers[row['thread_id']]=asyncio.create_task(observe(row))
                self.observers={tid:task for tid,task in self.observers.items() if not task.done()}
                await asyncio.sleep(1)
        self.task=asyncio.create_task(work())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        tasks=list(self.observers.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.observers.clear()
