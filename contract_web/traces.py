"""Searchable execution summaries backed by native messages, fetched on demand."""
import asyncio
import hashlib
from .thread_management import scope_sql
import json
import re
import time

from fastapi import HTTPException, Request
from .settings import encoded, admin
from .runtime import RuntimeError, public_error

SECRET_KEY = re.compile(r'api.?key|authorization|password|secret|credential|cookie|save.?token|access.?token|refresh.?token|publish.?token', re.I)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: '[已隐藏]' if SECRET_KEY.search(k) else redact(v, secrets) for k,v in value.items() if k not in {'reasoning', 'reasoningText', 'reasoning_content'}}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            value = value.replace(secret, '[已隐藏]')
    value = re.sub(r'(?i)(Bearer\s+)[^\s"\'<>]+', r'\1[已隐藏]', value)
    value = re.sub(r'(?i)((?:api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token|\.publish-token)\s*[=:]\s*["\']?)[^\s"\'<>;,]+',r'\1[已隐藏]',value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[已隐藏]', value)
    return value


class Traces:
    def __init__(self, settings, runtime, models=None):
        self.settings, self.store, self.runtime = settings, settings.store, runtime
        self.models = models
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS trace_runs (
              id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, user_id TEXT NOT NULL, message_id TEXT NOT NULL,
              execution_id TEXT, created REAL NOT NULL, summary TEXT NOT NULL, UNIQUE(thread_id,message_id));''')

    def credentials(self, org):
        # Native auth storage is intentionally absent from GET /config. Include
        # rotated keys so old tool output cannot expose credentials either.
        if not self.models:return []
        encrypted = {p['secret'] for version in self.store.all('SELECT content FROM model_versions WHERE org_id=?',(org,))
                     for p in json.loads(version['content']) if p.get('secret')}
        return [self.models.decrypt(value) for value in encrypted]

    def owner(self, viewer, uid):
        if uid != viewer['id']:
            raise HTTPException(404, '记录不存在')
        owner = self.store.one('SELECT id,username,org_id,role,model FROM users WHERE id=? AND org_id=?', (uid, viewer['org_id']))
        if not owner:
            raise HTTPException(404, '成员不存在')
        return owner

    def sync(self, u, t, messages, status):
        credentials = self.credentials(self.models.scope(u))
        credentials.append(self.runtime(u, t["id"]).config.get('password'))
        token = self.store.user_root(u['id'])/'threads'/t['id']/'.publish-token'
        if token.exists():credentials.append(token.read_text())
        memory_token = token.with_name('.memory-capability')
        if memory_token.exists():credentials.append(json.loads(memory_token.read_text()).get('token'))
        executions = self.store.all('SELECT * FROM execution_configs WHERE thread_id=? ORDER BY created', (t['id'],))
        configs = [(e, json.loads(e['config'])) for e in executions]
        existing = {row['message_id']: row for row in self.store.all('SELECT message_id,execution_id,summary FROM trace_runs WHERE thread_id=?', (t['id'],))}
        updates, execution_updates = [], []
        starts = [i for i,m in enumerate(messages) if m['info']['role']=='user' and any(p.get('type') in {'text','file'} and not p.get('synthetic') for p in m.get('parts',[]))]
        for n,start in enumerate(starts):
            end = starts[n+1] if n+1 < len(starts) else len(messages)
            group = messages[start:end];first = group[0]['info'];mid = first['id']
            created = first.get('time', {}).get('created', 0)/1000
            before = messages[start-1]['info']['id'] if start else None
            matched = next(((e,c) for e,c in reversed(configs) if e['message_id']==mid or (
                e['message_id'] is None and 'after_message_id' in c and c['after_message_id']==before)), None)
            if not matched and created:
                matched = next(((e,c) for e,c in reversed(configs) if e['created'] <= created <= e['created']+30 and e['message_id'] in {None,mid}), None)
            execution_id = matched[0]['id'] if matched else None
            assistants = [m for m in group if m['info']['role']=='assistant']
            errors = [public_error(m['info']['error']) for m in assistants if m['info'].get('error')]
            tool_errors = sum(p.get('state',{}).get('status')=='error' for m in group for p in m.get('parts',[]) if p.get('type')=='tool')
            running = n==len(starts)-1 and status.get('type')!='idle'
            last = assistants[-1]['info'] if assistants else {}
            state = 'running' if running else 'failed' if errors else 'failed' if last.get('finish') in {'length','content_filter','content-filter'} else 'completed' if last.get('finish') in {'stop','end_turn'} else 'interrupted'
            finished = max((m['info'].get('time',{}).get('completed',0) or 0 for m in assistants),default=0)/1000 or None
            usage = [m['info']['tokens'] for m in assistants if isinstance(m['info'].get('tokens'),dict)]
            tokens = sum(v.get('total') or sum(v.get(k,0) for k in ('input','output'))+sum(v.get('cache',{}).values()) for v in usage) if usage else None
            costs = [m['info'].get('cost') for m in assistants if m['info'].get('cost') is not None]
            cost = sum(costs) if costs and sum(costs)>0 else None
            model = last.get('providerID','')+'/'+last.get('modelID','') if last.get('modelID') else (matched[1].get('model',{}).get('id') if matched else None)
            created = created or (matched[0]['created'] if matched else t['created'])
            summary = {'status':state,'model':model,'duration':max(0,(time.time() if running else finished)-created) if (running or finished) else None,
                       'tokens':tokens,'cost':cost,'tool_errors':tool_errors,'error':redact(errors[-1],credentials) if errors else None,
                       'turn':n+1,'prompt':redact(' '.join(p.get('text','') if p['type']=='text' else p.get('filename','附件') for p in group[0].get('parts',[]) if p.get('type') in {'text','file'} and not p.get('synthetic')),credentials)[:160],
                       'tool_count':sum(p.get('type')=='tool' for m in group for p in m.get('parts',[])),
                       'configuration_status':'已记录' if matched else '历史版本未记录'}
            rid = hashlib.sha256((t['id']+':'+mid).encode()).hexdigest()[:24]
            serialized = encoded(summary)
            prior = existing.get(mid)
            if not prior or prior['execution_id'] != execution_id or prior['summary'] != serialized:
                updates.append((rid,t['id'],u['id'],mid,execution_id,created,serialized))
            if matched and (matched[0]['message_id'] != mid or matched[0]['status'] != state):
                execution_updates.append((mid,state,execution_id))
        if updates or execution_updates:
            with self.store.connect() as db:
                db.executemany('INSERT INTO trace_runs VALUES(?,?,?,?,?,?,?) ON CONFLICT(thread_id,message_id) DO UPDATE SET execution_id=excluded.execution_id,summary=excluded.summary', updates)
                db.executemany('UPDATE execution_configs SET message_id=?,status=? WHERE id=?', execution_updates)

    async def refresh(self, u):
        rows = self.store.all('SELECT t.* FROM threads t JOIN workspaces w ON w.id=t.workspace_id WHERE w.user_id=? AND t.deleted_at IS NULL ORDER BY t.created DESC LIMIT 100',(u['id'],))
        sem=asyncio.Semaphore(3)
        async def one(t):
            async with sem:
                try:
                    rt=self.runtime(u,t['id'])
                    messages,status=await asyncio.gather(rt.messages(t),rt.status(t))
                    await asyncio.to_thread(self.sync,u,t,messages,status)
                    return None
                except RuntimeError as e:
                    return str(e)
        failures=[r for r in await asyncio.gather(*(one(t) for t in rows)) if r]
        return {'refreshed':len(rows)-len(failures),'unavailable':len(failures)}

    async def detail(self, viewer, rid):
        row=self.store.one('SELECT * FROM trace_runs WHERE id=?',(rid,))
        if not row:
            raise HTTPException(404,'执行记录不存在')
        u=self.owner(viewer,row['user_id'])
        if u['id'] != viewer['id']:
            self.settings.audit(viewer,'trace.detail',rid)
        t=self.store.one('SELECT * FROM threads WHERE id=?',(row['thread_id'],));rt=self.runtime(u,t["id"])
        messages=await rt.messages(t)
        start=next((i for i,m in enumerate(messages) if m['info']['id']==row['message_id']),None)
        if start is None:
            raise HTTPException(410,'原生消息已不可用，检索摘要仍保留')
        end=next((i for i in range(start+1,len(messages)) if messages[i]['info']['role']=='user' and any(p.get('type') in {'text','file'} and not p.get('synthetic') for p in messages[i].get('parts',[]))),len(messages))
        credentials=[rt.config.get('password'), *self.credentials(self.models.scope(u))]
        token=self.store.user_root(u['id'])/'threads'/t['id']/'.publish-token'
        if token.exists():credentials.append(token.read_text())
        memory_token = token.with_name('.memory-capability')
        if memory_token.exists():credentials.append(json.loads(memory_token.read_text()).get('token'))
        # Collect only configured credentials for exact replacement in text fields.
        try:
            config=await rt.call('GET','/config',tid=t['id'])
            for p in config.get('provider',{}).values():
                credentials.extend(v for k,v in p.get('options',{}).items() if SECRET_KEY.search(k) and isinstance(v,str))
        except RuntimeError:
            pass
        timeline=[]
        for message in messages[start:end]:
            info=message['info']
            if info.get('summary'):continue
            parts=[]
            for p in message.get('parts',[]):
                if p.get('synthetic') or p.get('type') not in {'text','tool','file'}:continue
                if p['type']=='text':parts.append({'type':'text','text':p.get('text','')})
                elif p['type']=='file':parts.append({'type':'file','filename':p.get('filename','附件')})
                else:
                    state=p.get('state',{})
                    parts.append({'type':'tool','tool':p.get('tool'),'state':{k:state[k] for k in ('status','input','output','error','time','title') if k in state}})
            if not parts and not info.get('error'):continue
            timeline.append({'info':{k:public_error(info[k]) if k=='error' else info[k] for k in ('id','role','time','modelID','providerID','tokens','cost','error','finish') if k in info},'parts':parts})
        execution=self.store.one('SELECT config FROM execution_configs WHERE id=?',(row['execution_id'],))
        artifacts=self.store.all('SELECT id,title,kind,created FROM artifacts WHERE thread_id=? ORDER BY created',(t['id'],))
        artifacts=[a for a in artifacts if a['created']>=row['created'] and (end==len(messages) or a['created']<messages[end]['info'].get('time',{}).get('created',0)/1000)]
        # Admin inspection does not turn ordinary artifact URLs into cross-user downloads.
        for a in artifacts:a['downloadable']=u['id']==viewer['id']
        return redact({'id':rid,'summary':json.loads(row['summary']),'messages':timeline,
                       'runtime':self.e2b.diagnostics(t['workspace_id']) if hasattr(self,'e2b') and rt.config.get('e2b') else None,
                       'configuration':json.loads(execution['config']) if execution else None,'artifacts':artifacts},credentials)


def register_traces(app,traces,user):
    store=traces.store

    def search_query(u,user_id,q,status,scope):
        args=[u['org_id']];where='u.org_id=? AND '+scope_sql(scope)
        owner=traces.owner(u,user_id or u['id']);where+=' AND r.user_id=?';args.append(owner['id'])
        if q:
            where+=" AND (w.title LIKE ? OR t.title LIKE ? OR u.username LIKE ? OR w.id LIKE ? OR t.id LIKE ? OR json_extract(r.summary,'$.prompt') LIKE ?)";args+=['%'+q[:200]+'%']*6
        if status=='errors':
            where+=" AND (json_extract(r.summary,'$.status')='failed' OR json_extract(r.summary,'$.tool_errors')>0)"
        elif status:
            if status not in {'running','failed','completed','interrupted'}:raise HTTPException(422,'状态无效')
            where+=" AND json_extract(r.summary,'$.status')=?";args.append(status)
        return ' FROM trace_runs r JOIN users u ON u.id=r.user_id JOIN threads t ON t.id=r.thread_id JOIN workspaces w ON w.id=t.workspace_id WHERE '+where,args

    def workspace_owner(viewer,wid):
        w=store.one('SELECT * FROM workspaces WHERE id=?',(wid,))
        if not w:raise HTTPException(404,'合同不存在')
        traces.owner(viewer,w['user_id'])
        return w

    @app.post('/api/traces/refresh')
    async def refresh(request:Request):
        viewer=user(request);body=await request.json();owner=traces.owner(viewer,body.get('user_id') or viewer['id'])
        return await traces.refresh(owner)

    @app.get('/api/traces')
    async def listing(request:Request,user_id:str|None=None,q:str='',status:str='',scope:str='active',offset:int=0,limit:int=30):
        u=user(request);query,args=search_query(u,user_id,q,status,scope)
        rows=store.all('SELECT r.*,u.username,t.title,t.archived_at,t.deleted_at,w.title AS workspace_title,w.id AS workspace_id'+query+' ORDER BY r.created DESC LIMIT ? OFFSET ?',(*args,min(100,max(1,limit)),max(0,offset)))
        for row in rows:row['summary']=json.loads(row['summary'])
        return {'runs':redact(rows,traces.credentials(traces.models.scope(u))),'total':store.one('SELECT COUNT(*) AS n'+query,args)['n']}

    @app.get('/api/traces/contracts')
    async def contracts(request:Request,user_id:str|None=None,q:str='',status:str='',scope:str='active',offset:int=0,limit:int=20):
        u=user(request);query,args=search_query(u,user_id,q,status,scope)
        rows=store.all('SELECT w.id,w.title,u.username,COUNT(DISTINCT t.id) AS thread_count,COUNT(*) AS run_count,MAX(r.created) AS updated'+query+' GROUP BY w.id ORDER BY updated DESC,w.id LIMIT ? OFFSET ?',(*args,min(100,max(1,limit)),max(0,offset)))
        return {'contracts':redact(rows,traces.credentials(traces.models.scope(u))),'total':store.one('SELECT COUNT(DISTINCT w.id) AS n'+query,args)['n']}

    @app.get('/api/traces/contracts/{wid}/threads')
    async def threads(wid:str,request:Request,user_id:str|None=None,q:str='',status:str='',scope:str='active'):
        u=user(request);workspace_owner(u,wid);query,args=search_query(u,user_id,q,status,scope)
        rows=store.all('SELECT t.id,t.title,t.archived_at,t.deleted_at,COUNT(*) AS run_count,MAX(r.created) AS updated'+query+' AND w.id=? GROUP BY t.id ORDER BY t.position,t.created,t.id',(*args,wid))
        return {'threads':redact(rows,traces.credentials(traces.models.scope(u)))}

    @app.get('/api/traces/threads/{tid}/runs')
    async def turns(tid:str,request:Request,offset:int=0,limit:int=50):
        u=user(request);t=store.one('SELECT * FROM threads WHERE id=?',(tid,))
        if not t:raise HTTPException(404,'会话不存在')
        workspace_owner(u,t['workspace_id'])
        # Once a matching session is opened, keep all its turns for context.
        rows=store.all("SELECT * FROM trace_runs WHERE thread_id=? ORDER BY COALESCE(json_extract(summary,'$.turn'),created),message_id LIMIT ? OFFSET ?",(tid,min(100,max(1,limit)),max(0,offset)))
        for row in rows:row['summary']=json.loads(row['summary'])
        return {'runs':redact(rows,traces.credentials(traces.models.scope(u))),'total':store.one('SELECT COUNT(*) AS n FROM trace_runs WHERE thread_id=?',(tid,))['n']}

    @app.get('/api/traces/{rid}')
    async def detail(rid:str,request:Request):
        return await traces.detail(user(request),rid)

    @app.get('/api/admin/audit')
    async def audit(request:Request):
        u=user(request);admin(u)
        return store.all('SELECT a.*,u.username FROM audit_log a JOIN users u ON u.id=a.actor_id WHERE a.actor_id=? ORDER BY a.id DESC LIMIT 100',(u['id'],))

    @app.get('/api/admin/trace-members')
    async def trace_members(request:Request):
        u=user(request);admin(u)
        return store.all('SELECT id,username FROM users WHERE id=?',(u['id'],))
