"""Bounded trial-only OpenAI-compatible relay. Platform keys never enter a VM."""
import asyncio
import json
import os
import time

import httpx
from fastapi import HTTPException,Request
from fastapi.responses import StreamingResponse,Response
from .store import digest


def register_trial_proxy(app,accounts):
    store=accounts.store
    @app.post('/trial-model/v1/chat/completions')
    async def completion(request:Request):
        token=request.headers.get('authorization','').removeprefix('Bearer ')
        u=store.one('SELECT u.* FROM users u JOIN trial_tokens t ON t.user_id=u.id WHERE t.token=? AND t.expires>? AND u.active=1 AND (u.expires_at IS NULL OR u.expires_at>?)',(digest(token),time.time(),time.time()))
        if not u:raise HTTPException(401,'试用调用凭据已失效')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>2_000_000:raise HTTPException(413,'请求过大')
        try:body=json.loads(raw)
        except (ValueError,UnicodeError):raise HTTPException(422,'请求无效')
        if not isinstance(body,dict) or not isinstance(body.get('messages'),list):raise HTTPException(422,'请求无效')
        model=os.environ.get('CW_TRIAL_MODEL','glm-5.3')
        if body.get('model')!=model:raise HTTPException(403,'此模型不在试用范围内')
        allowed={'model','messages','stream','tools','tool_choice','temperature','top_p','stop','parallel_tool_calls','stream_options','thinking','reasoning_effort'}
        body={k:v for k,v in body.items() if k in allowed};body['max_tokens']=8192
        body.pop('stream_options',None)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            r=db.execute("SELECT r.* FROM trial_runs r JOIN queued_messages q ON q.id=r.queue_id WHERE r.user_id=? AND q.thread_id=? AND platform=1 AND r.status='running' AND q.status IN ('dispatching','submitted') AND proxy_active=0 AND proxy_calls<? AND started>? ORDER BY started LIMIT 1",(u['id'],request.headers.get('x-workbench-thread',''),accounts.limits()['proxy_calls'],time.time()-accounts.limits()['run_seconds'])).fetchone()
            if not r:raise HTTPException(429,'没有可用的试用运行额度')
            qid=r['queue_id'];deadline=r['started']+accounts.limits()['run_seconds']
            db.execute('UPDATE trial_runs SET proxy_active=1,proxy_calls=proxy_calls+1 WHERE queue_id=?',(qid,))
        client=httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(120,connect=15));upstream=None
        try:
            url=os.environ.get('CW_TRIAL_MODEL_BASE_URL','').rstrip('/')
            if not url.startswith('https://'):raise HTTPException(503,'试用模型尚未配置')
            store.execute('UPDATE trial_runs SET model_uncertain=1 WHERE queue_id=?',(qid,))
            try:
                async with asyncio.timeout(max(1,deadline-time.time())):
                    upstream=await client.send(client.build_request('POST',url+'/chat/completions',json=body,headers={'Authorization':'Bearer '+os.environ.get('CW_TRIAL_MODEL_KEY','')}),stream=True)
            except (httpx.ConnectError,httpx.ConnectTimeout):
                store.execute('UPDATE trial_runs SET model_uncertain=0 WHERE queue_id=?',(qid,))
                raise HTTPException(502,'暂时无法连接试用模型，本次未提交模型') from None
            if upstream.status_code>=400:
                store.execute('UPDATE trial_runs SET model_uncertain=0 WHERE queue_id=?',(qid,))
                raise HTTPException(502,'平台试用模型暂不可用，请稍后重试')
            store.execute('UPDATE trial_runs SET model_accepted=1,model_uncertain=0 WHERE queue_id=?',(qid,))
        except BaseException:
            if upstream:await upstream.aclose()
            await client.aclose();store.execute('UPDATE trial_runs SET proxy_active=0 WHERE queue_id=?',(qid,));raise
        async def content():
            size=0
            try:
                async with asyncio.timeout(max(1,deadline-time.time())):
                    async for chunk in upstream.aiter_bytes():
                        status=store.one('SELECT r.status,u.active,u.expires_at FROM trial_runs r JOIN users u ON u.id=r.user_id WHERE queue_id=?',(qid,))
                        if not status or not status['active'] or status['status']!='running' or (status['expires_at'] and status['expires_at']<=time.time()):break
                        size+=len(chunk)
                        if size>4_000_000:break
                        yield chunk
            finally:
                await upstream.aclose();await client.aclose()
                store.execute('UPDATE trial_runs SET proxy_active=0 WHERE queue_id=?',(qid,))
        return StreamingResponse(content(),media_type='text/event-stream' if body.get('stream') else 'application/json',headers={'Cache-Control':'no-store'})
