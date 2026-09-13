"""Recoverable conversation lifecycle; native history and saved files stay intact."""
import asyncio
import time
from fastapi import HTTPException, Request


def scope_sql(scope, alias="t"):
    filters = {
        "active": f"{alias}.deleted_at IS NULL AND {alias}.archived_at IS NULL",
        "archived": f"{alias}.deleted_at IS NULL AND {alias}.archived_at IS NOT NULL",
        "deleted": f"{alias}.deleted_at IS NOT NULL",
        "all": "1=1",
    }
    if scope not in filters:
        raise HTTPException(422, "对话范围无效")
    return filters[scope]


def register_thread_management(app, store, settings, user, thread, runtime, manager, locks, queue, traces):
    @app.patch('/api/threads/{tid}')
    async def manage(tid: str, request: Request):
        u = user(request)
        thread(u, tid)
        body = await request.json()
        action = body.get('action') if isinstance(body, dict) else None
        if action=='rename':
            name=body.get('title')
            if not isinstance(name,str) or not 1<=len(name.strip())<=120:
                raise HTTPException(422,'请输入 1–120 字的对话名称')
            store.execute('UPDATE threads SET title=?,custom_title=? WHERE id=?',(name.strip(),name.strip(),tid))
            settings.audit(u,'thread.rename',tid)
            return {'id':tid,'title':name.strip()}
        if action not in {'up', 'down', 'archive', 'delete', 'restore'}:
            raise HTTPException(422, '请选择上移、下移、归档、删除或恢复')
        # Share both existing locks: enqueue/dispatch and document/skill writes
        # cannot cross the lifecycle transition.
        async with manager.lock('queue-'+thread(u,tid)['workspace_id'] if runtime(u,tid).config.get('e2b') else u['id']), locks.setdefault(tid, asyncio.Lock()):
            t = thread(u, tid)
            if action in {'archive', 'delete'}:
                if t['deleted_at'] or (action == 'archive' and t['archived_at']):
                    raise HTTPException(409, '对话状态已变化，请刷新列表')
                rt = runtime(u,tid)
                status, questions, permissions = await asyncio.gather(
                    rt.status(t), rt.call('GET', '/question', tid=tid), rt.call('GET', '/permission', tid=tid))
                pending = queue.state(tid)
                if status['type'] != 'idle' or pending['active'] or pending['items'] or any(
                        q.get('sessionID') == t['session_id'] for q in questions + permissions):
                    raise HTTPException(409, '请先完成或取消当前任务，并处理待回答请求及排队消息')
                traces.sync(u, t, await rt.messages(t), status)
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if action in {'up', 'down'}:
                    scope = 'deleted' if t['deleted_at'] else 'archived' if t['archived_at'] else 'active'
                    rows = db.execute('SELECT t.id,t.position FROM threads t WHERE t.workspace_id=? AND ' +
                                      scope_sql(scope) + ' ORDER BY t.position,t.created,t.id', (t['workspace_id'],)).fetchall()
                    index = next(i for i, row in enumerate(rows) if row['id'] == tid)
                    other = index + (-1 if action == 'up' else 1)
                    if not 0 <= other < len(rows):
                        raise HTTPException(409, '已到列表边界，请刷新列表')
                    db.executemany('UPDATE threads SET position=? WHERE id=?', [
                        (rows[other]['position'], tid), (rows[index]['position'], rows[other]['id'])])
                elif action == 'restore':
                    column = 'deleted_at' if t['deleted_at'] else 'archived_at'
                    db.execute(f'UPDATE threads SET {column}=NULL WHERE id=?', (tid,))
                else:
                    column = 'archived_at' if action == 'archive' else 'deleted_at'
                    db.execute(f'UPDATE threads SET {column}=? WHERE id=?', (time.time(), tid))
            settings.audit(u, 'thread.' + action, tid)
        result = thread(u, tid)
        return {k: v for k, v in result.items() if k != 'save_token'}
