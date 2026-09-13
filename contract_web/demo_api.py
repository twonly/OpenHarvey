"""Public sample entry and explicitly published executions of the approved source."""
import asyncio
import hashlib
import json
import secrets
import shutil
import time
from weakref import WeakValueDictionary
from pathlib import Path
from fastapi import HTTPException,Request
from fastapi.responses import FileResponse
from .settings import admin
from .presentation import PublicView
from .documents import prepare
from .artifact_formats import files_for,FORMATS


def register_demo(app,user,create_thread,create_workspace):
    store=app.state.store;e2b=app.state.e2b;accounts=app.state.accounts
    sample=Path(__file__).resolve().parents[1]/'runtime/public-examples/sample-contract.txt'
    sample_hash=hashlib.sha256(sample.read_bytes()).hexdigest()
    sample_locks=WeakValueDictionary()
    def example(eid):
        row=store.one('SELECT * FROM public_examples WHERE id=?',(eid,))
        if not row:raise HTTPException(404,'示例不存在')
        return row
    def folder(eid):return store.root/'public-examples'/eid
    def frozen(eid):
        example(eid)
        path=folder(eid)/'example.json'
        if not path.is_file():raise HTTPException(404,'示例尚未发布')
        data=json.loads(path.read_text())
        if not data.get('documents') or any(d.get('source_hash')!=sample_hash for d in data['documents']):
            raise HTTPException(410,'该旧示例已下线，请打开新的虚构合同示例')
        return data
    def documents(row):
        docs=store.all('SELECT * FROM documents WHERE workspace_id=? AND user_id=?',(row['workspace_id'],row['source_user']))
        result=[]
        for d in docs:
            mapped=json.loads((store.user_root(row['source_user'])/'sources'/d['id']/'document.json').read_text())
            result.append({k:d[k] for k in ('id','filename','source_hash')}|{'locations':{s['id']:{'page':s.get('page'),'ordinal':i+1,'preview':s.get('text','')[:180]} for i,s in enumerate(mapped['segments'])}})
        return result
    @app.get('/api/demo/examples')
    async def examples():
        result=[]
        for row in store.all('SELECT id,title,created FROM public_examples ORDER BY created'):
            try:frozen(row['id'])
            except HTTPException:continue
            result.append(row)
        return result

    @app.post('/api/demo/workspace')
    async def open_sample(request:Request):
        u=user(request)
        # Reopening /demo must not duplicate spaces or spend upload/request quotas.
        lock=sample_locks.setdefault(u['id'],asyncio.Lock())
        async with lock:
            accounts.require_active(u)
            row=store.one('SELECT w.id FROM workspaces w JOIN documents d ON d.id=w.document_id WHERE w.user_id=? AND d.source_hash=? AND w.deleted_at IS NULL AND w.security_blocked=0 ORDER BY w.created LIMIT 1',(u['id'],sample_hash))
            if row:return {'workspace_id':row['id']}
            w=await create_workspace(u,sample)
            return {'workspace_id':w['id']}


    @app.get('/api/demo/examples/{eid}')
    async def read_example(eid:str):
        return frozen(eid)

    @app.get('/api/demo/examples/{eid}/source/{did}')
    async def source(eid:str,did:str):
        data=frozen(eid)
        if did not in {d['id'] for d in data['documents']}:raise HTTPException(404,'原文不存在')
        return json.loads((folder(eid)/'sources'/did/'document.json').read_text())

    @app.get('/api/demo/examples/{eid}/artifacts/{aid}')
    async def file(eid:str,aid:str,format:str='md'):
        data=frozen(eid)
        item=next((a for a in data['artifacts'] if a['id']==aid),None)
        if not item or format not in item['files']:raise HTTPException(404,'文件不存在')
        return FileResponse(folder(eid)/'artifacts'/aid/item['files'][format],filename=item['title']+'.'+format,media_type=FORMATS.get(format,'application/octet-stream'))

    @app.post('/api/demo/continue')
    async def continue_example(request:Request):
        u=user(request);body=await request.json();data=frozen(str(body.get('example_id','')))
        w=await create_workspace(u,sample)
        try:t=await create_thread(u,w)
        except Exception:
            store.execute('UPDATE workspaces SET deleted_at=? WHERE id=?',(time.time(),w['id']))
            await app.state.purge_workspace(u,{**w,'deleted_at':time.time()})
            raise
        prior=data['documents'][0]['id']
        text='\n'.join(m['role']+': '+m['text'] for m in data['messages'])
        text=text.replace('【D'+prior+':','【D'+w['document_id']+':')
        (store.user_root(u['id'])/'threads'/t['id']/'example-context.json').write_text(json.dumps({'title':data['title'],'text':text[-30000:]},ensure_ascii=False))
        return {'workspace_id':w['id'],'thread_id':t['id'],'prompt':'请阅读示例合同，继续帮我分析：'+data['title']}

    @app.post('/api/admin/demo/publish')
    async def publish(request:Request):
        u=user(request);admin(u);body=await request.json();tid=str(body.get('thread_id',''))
        t=store.one('SELECT t.*,w.user_id FROM threads t JOIN workspaces w ON w.id=t.workspace_id WHERE t.id=?',(tid,))
        if not t or t['user_id']!=u['id']:raise HTTPException(404,'对话不存在')
        docs=store.all('SELECT * FROM documents WHERE workspace_id=?',(t['workspace_id'],))
        if len(docs)!=1:raise HTTPException(422,'仅允许发布单份公开示例文件的运行结果')
        original=store.user_root(u['id'])/'sources'/docs[0]['id']/('source'+docs[0]['suffix'])
        if original.read_bytes()!=sample.read_bytes():raise HTTPException(422,'公开示例必须使用内置虚构合同示例')
        messages,status=e2b.history(tid)
        if status.get('status',{}).get('type','idle')!='idle' or not any(m['info'].get('role')=='assistant' and m['info'].get('time',{}).get('completed') for m in messages):raise HTTPException(409,'请先完成真实示例运行')
        if not store.one('SELECT 1 FROM artifacts WHERE thread_id=?',(tid,)):raise HTTPException(422,'示例需要真实保存的产出')
        if store.one("SELECT 1 FROM queued_messages WHERE thread_id=? AND status IN ('queued','dispatching','submitted')",(tid,)):raise HTTPException(409,'请等待队列处理完成')
        executions=store.all('SELECT config FROM execution_configs WHERE thread_id=?',(tid,))
        if not executions or any(json.loads(r['config'])['risk_scheme']['id']!='public-risk-examples' for r in executions):raise HTTPException(422,'仅允许发布使用公开风险方案的示例')
        old=store.one('SELECT id FROM public_examples WHERE thread_id=?',(tid,))
        if old:return {'id':old['id']}
        eid=secrets.token_hex(12);title=str(body.get('title') or t['title'])[:120]
        root=folder(eid);root.mkdir(parents=True)
        row={'source_user':u['id'],'workspace_id':t['workspace_id']};view=PublicView()
        data={'id':eid,'title':title,'documents':documents(row),'messages':[{'role':m['info']['role'],'text':view.text('\n'.join(p.get('text','') for p in m.get('parts',[]) if p.get('type')=='text'))} for m in messages if not m['info'].get('summary') and m['info'].get('role') in ('user','assistant')],'artifacts':[]}
        for d in docs:
            dest=root/'sources'/d['id'];dest.mkdir(parents=True)
            shutil.copyfile(store.user_root(u['id'])/'sources'/d['id']/'document.json',dest/'document.json')
        for a in store.all('SELECT id,title,kind FROM artifacts WHERE thread_id=?',(tid,)):
            source=store.user_root(u['id'])/'published'/a['id'];body=json.loads((source/'report.json').read_text());files=files_for(body)
            dest=root/'artifacts'/a['id'];dest.mkdir(parents=True)
            for filename in files.values():shutil.copyfile(source/filename,dest/filename)
            data['artifacts'].append(a|{'files':files})
        (root/'example.json').write_text(json.dumps(data,ensure_ascii=False))
        store.execute('INSERT INTO public_examples VALUES(?,?,?,?,?,?)',(eid,title,u['id'],t['workspace_id'],tid,time.time()))
        return {'id':eid}
