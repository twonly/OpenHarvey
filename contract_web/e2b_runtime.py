"""Concrete E2B/OpenCode integration. SQLite is the binding and history authority.

No provider abstraction: only this module calls the E2B SDK. Reads of history
never provision or resume a VM; execution explicitly calls prepare().
"""
import asyncio
import hashlib
import json
import os
import secrets
import shlex
import time
import threading
from collections import defaultdict
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from .runtime import Runtime, RuntimeError
from .cli import ROOT, runtime_config
from .settings import encoded
from .traces import redact

TTL = 300


class E2B:
    def __init__(self, store, settings, models, manager, sandbox_class=None):
        self.store, self.settings, self.models, self.manager = store, settings, models, manager
        self.sandbox_class = sandbox_class
        self.handles, self.tasks, self.streams = {}, [], {}
        self.last_create = 0
        self.event_revisions = {}
        self.history_locks = defaultdict(threading.Lock)
        self.stream_ready = {}
        self.renewed = {}
        self.unhealthy = set()
        self.file_indexes = {}
        self.file_stats = {}
        self.permission_cache = {}
        self.path_cache = {}
        self.pending_checkpoints = set()
        self.artifacts = self.traces = None
        self.template = os.environ.get('E2B_TEMPLATE', 'contract-opencode-1-16-2')
        self.enabled = os.environ.get('CW_SANDBOX_BACKEND', 'e2b') == 'e2b'
        with store.connect() as db:
            if 'backend' not in {r[1] for r in db.execute('PRAGMA table_info(workspaces)')}:
                db.execute("ALTER TABLE workspaces ADD COLUMN backend TEXT NOT NULL DEFAULT 'local'")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS e2b_bindings (
                  workspace_id TEXT PRIMARY KEY, sandbox_id TEXT, generation INTEGER NOT NULL DEFAULT 0,
                  template TEXT, status TEXT NOT NULL DEFAULT 'new', credentials TEXT,
                  revision INTEGER NOT NULL DEFAULT 0, last_activity REAL NOT NULL DEFAULT 0,
                  started REAL NOT NULL DEFAULT 0, synced REAL, error TEXT);
                CREATE TABLE IF NOT EXISTS e2b_files (
                  workspace_id TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL,
                  PRIMARY KEY(workspace_id,path));
                CREATE TABLE IF NOT EXISTS e2b_history (
                  thread_id TEXT PRIMARY KEY, messages TEXT NOT NULL DEFAULT '[]', snapshot TEXT NOT NULL DEFAULT '{}', synced REAL);
                CREATE TABLE IF NOT EXISTS e2b_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, thread_id TEXT,
                  execution_id TEXT, kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS e2b_receipts (
                  request_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, execution_id TEXT NOT NULL,
                  hash TEXT NOT NULL, receipt TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
            ''')
        from .skill_sync import SkillSync
        self.skill_sync=SkillSync(self)
        p=store.root/'secrets'/'deployment-id'
        if not p.exists(): p.write_text(secrets.token_hex(16)); p.chmod(0o600)
        self.deployment=p.read_text().strip()

    @property
    def sdk(self):
        if self.sandbox_class: return self.sandbox_class
        if not os.environ.get('E2B_API_KEY'): raise RuntimeError('尚未配置 E2B_API_KEY；材料已保存在本地')
        from e2b import AsyncSandbox
        return AsyncSandbox

    def binding(self, wid):
        return self.store.one('SELECT * FROM e2b_bindings WHERE workspace_id=?',(wid,))

    def state(self, wid, **fields):
        self.store.execute('INSERT OR IGNORE INTO e2b_bindings(workspace_id) VALUES(?)',(wid,))
        if fields:
            allowed={'sandbox_id','generation','template','status','credentials','revision','last_activity','started','synced','error'}
            if set(fields)-allowed: raise ValueError('无效 E2B 状态字段')
            self.store.execute('UPDATE e2b_bindings SET '+','.join(k+'=?' for k in fields)+' WHERE workspace_id=?',(*fields.values(),wid))
        return self.binding(wid)

    def owner(self,wid):
        row=self.store.one('SELECT u.* FROM users u JOIN workspaces w ON w.user_id=u.id WHERE w.id=?',(wid,))
        if not row: raise RuntimeError('合同空间不存在')
        return row

    def secrets(self, u, wid):
        values=[os.environ.get('E2B_API_KEY')]
        for v in self.store.all('SELECT content FROM model_versions WHERE org_id=?',(self.models.scope(u),)):
            values.extend(self.models.decrypt(p['secret']) for p in json.loads(v['content']) if p.get('secret'))
        b=self.binding(wid)
        if b and b['credentials']: values.extend(json.loads(self.models.decrypt(b['credentials'])).values())
        return values

    def record(self,wid,kind,data=None,tid=None):
        u=self.owner(wid)
        started=self.store.one("SELECT MAX(created) AS created FROM e2b_events WHERE thread_id=? AND kind='execution.start'",(tid,)) if tid else None
        execution=self.store.one('SELECT id FROM execution_configs WHERE thread_id=? AND created>=? ORDER BY created DESC LIMIT 1',
                                 (tid,(started or {}).get('created') or 0)) if tid and kind!='execution.start' else None
        clean=redact(data or {},self.secrets(u,wid))
        self.store.execute('INSERT INTO e2b_events(workspace_id,thread_id,execution_id,kind,data,created) VALUES(?,?,?,?,?,?)',
            (wid,tid,execution['id'] if execution else None,kind,encoded(clean),time.time()))

    def config(self,u,w):
        b=self.binding(w['id']) if w else None
        credentials=json.loads(self.models.decrypt(b['credentials'])) if b and b['credentials'] else {}
        return {'url':credentials.get('url','https://unprovisioned.invalid'), 'password':credentials.get('password',''),
                'headers':{'e2b-traffic-access-token':credentials.get('traffic','')},
                'work_root':'/workspace/threads','source_root':'/workspace/input','skill_root':'/opt/contract-runtime',
                'local':False,'e2b':True,'submit_script':'/opt/contract-runtime/scripts/submit.py'}

    def runtime(self,u,w=None): return E2BRuntime(self,u,w)

    def catalog(self,u):
        latest=self.store.one('SELECT * FROM model_versions WHERE org_id=? AND validated=1 ORDER BY revision DESC LIMIT 1',(self.models.scope(u),))
        rows=self.models.snapshot(self.models.scope(u),latest['revision']) if latest else []
        native,auth=self.models.native(rows)
        return latest, native, auth

    def archive(self,u,wid):
        p=self.store.user_root(u['id'])/'runtime-archives'/wid
        p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
        return p

    async def pace_creation(self):
        # Hobby: at most one creation per second, including model probes.
        await asyncio.sleep(max(0,1-(time.monotonic()-self.last_create)))
        self.last_create=time.monotonic()

    async def probe(self,rows,model_id=None):
        """Test the model from E2B, with no contracts or persistent binding."""
        native,auth=self.models.native(rows)
        candidates=[(pid,mid) for pid,p in native['provider'].items() for mid in p['models'] if not model_id or pid+'/'+mid==model_id]
        if not candidates:raise RuntimeError('没有可测试的启用模型')
        sbx=None
        try:
            async with self.manager.lock('e2b-create'):
                await self.pace_creation()
                sbx=await self.sdk.create(self.template,timeout=300,metadata={'deployment':self.deployment,'purpose':'model-probe'},
                    network={'allow_public_traffic':False},lifecycle={'on_timeout':'kill','auto_resume':False})
            if not sbx.traffic_access_token:raise RuntimeError('E2B 未返回端口访问凭据')
            secret=secrets.token_urlsafe(32)
            rt=Runtime({'url':'https://'+sbx.get_host(4096),'password':secret,
                'headers':{'e2b-traffic-access-token':sbx.traffic_access_token}})
            config={**native,'share':'disabled','autoupdate':False,'snapshot':False,'permission':{'*':'deny'},
                    'agent':{'probe':{'mode':'primary','prompt':'Reply OK. Do not use tools.'}}}
            await sbx.files.write('/tmp/probe/config.json',encoded(config))
            env={'OPENCODE_CONFIG':'/tmp/probe/config.json','OPENCODE_SERVER_PASSWORD':secret,
                 'XDG_CONFIG_HOME':'/tmp/probe/config','XDG_DATA_HOME':'/tmp/probe/data',
                 'OPENCODE_DISABLE_CLAUDE_CODE':'true','OPENCODE_DISABLE_EXTERNAL_SKILLS':'true'}
            await sbx.commands.run('opencode serve --pure --hostname 0.0.0.0 --port 4096',envs=env,background=True,timeout=0)
            for _ in range(60):
                if await self.healthy(rt):break
                await asyncio.sleep(.5)
            else:raise RuntimeError('E2B 模型测试服务启动超时')
            for pid,key in auth.items():
                if key:await rt.call('PUT','/auth/'+pid,body={'type':'api','key':key})
            await rt.call('POST','/global/dispose')
            results=[]
            for pid,mid in candidates:
                await sbx.set_timeout(180)
                started=time.monotonic();session=await rt.call('POST','/session',body={'title':'连接测试'})
                await rt.call('POST',f'/session/{session["id"]}/prompt_async',body={'agent':'probe','model':{'providerID':pid,'modelID':mid},'parts':[{'type':'text','text':'Reply OK.'}]})
                for _ in range(180):
                    await asyncio.sleep(.5)
                    messages=await rt.call('GET',f'/session/{session["id"]}/message')
                    answers=[m for m in messages if m['info']['role']=='assistant']
                    if answers and answers[-1]['info'].get('error'):
                        raise RuntimeError(redact(encoded(answers[-1]['info']['error']),auth.values()))
                    if answers and answers[-1]['info'].get('time',{}).get('completed'):
                        if not any(p.get('type')=='text' and p.get('text','').strip() for m in answers for p in m.get('parts',[])):
                            raise RuntimeError('E2B 模型测试未返回文本')
                        results.append({'model':pid+'/'+mid,'ok':True,'latency_ms':round((time.monotonic()-started)*1000)})
                        break
                else:raise RuntimeError('E2B 模型连接测试超时')
            return {'models':results,'message':'E2B 内原生 OpenCode 实际调用成功'}
        except Exception as exc:
            raise RuntimeError(redact(str(exc),[os.environ.get('E2B_API_KEY'),*auth.values()])) from None
        finally:
            if sbx:await sbx.kill()

    def progress(self,t,stage):
        self.record(t["workspace_id"],"preparation.stage",{"stage":stage},t["id"])
        self.store.execute("UPDATE queued_messages SET stage=? WHERE thread_id=? AND status='dispatching'",(stage,t['id']))

    def other_active(self,wid,tid):
        for t in self.store.all('SELECT id FROM threads WHERE workspace_id=? AND id!=?',(wid,tid)):
            if self.snapshot(t['id']).get('status',{}).get('type','idle')!='idle':return True
            if self.store.one("SELECT 1 FROM queued_messages WHERE thread_id=? AND status='submitted'",(t['id'],)):return True
        return False

    async def prepare(self,u,t,recovering=False):
        wid=t['workspace_id']
        if self.store.one('SELECT security_blocked FROM workspaces WHERE id=?',(wid,))['security_blocked']:raise RuntimeError('旧空间的共享配置已撤销，无法恢复旧沙箱，请新建空间继续')
        # Local lease and applied provider revision are sufficient for a warm VM.
        # Never wait behind background checkpoint/log extraction on this path.
        prior=self.binding(wid)
        latest=self.store.one('SELECT revision FROM model_versions WHERE org_id=? AND validated=1 ORDER BY revision DESC LIMIT 1',(self.models.scope(u),))
        warm=(wid in self.handles and prior and prior['status']=='ready' and wid not in self.unhealthy
              and time.monotonic()-self.renewed.get(wid,0)<TTL-30
              and prior['template']==self.template and latest and prior['revision']==latest['revision']
              and (not prior['started'] or time.time()-prior['started']<600 or self.other_active(wid,t['id'])))
        if warm and not recovering:
            rt=self.runtime(u,{'id':wid})
            new_session=t['session_id'].startswith('pending_')
            if new_session:
                await self.sync_files(u,t)
                await self.ensure_session(rt,t)
            self.state(wid,last_activity=time.time())
            self.record(wid,'preparation.warm',{'session_created':new_session},t['id'])
            return rt
        async with self.manager.lock('e2b-'+wid):
            latest,native,auth=self.catalog(u)
            prior=self.binding(wid)
            other_active=self.other_active(wid,t['id'])
            if (recovering or other_active) and prior and prior['revision']:
                latest={'revision':prior['revision']}
                native,auth=self.models.native(self.models.snapshot(self.models.scope(u),prior['revision']))
            if not latest or not native.get('provider'): raise RuntimeError('请先配置并验证至少一个模型')
            b=self.state(wid)
            if b['status']=='recovery_failed':raise RuntimeError('原生恢复备份不可用；已同步历史可查看，请新建合同空间或恢复本地备份')
            sbx=self.handles.get(wid); created=False
            started=time.monotonic()
            if sbx is not None:
                info=await sbx.get_info()
                if str(info.state).lower().split('.')[-1]=='paused':
                    self.handles.pop(wid,None);self.state(wid,status='paused');sbx=None
            if sbx is not None and not recovering and not other_active and b['template']!=self.template:
                await self.destroy(u,{'id':wid,'deleted_at':None})
                sbx=None;b=self.binding(wid)
            if sbx is not None and not recovering and not other_active and b['started'] and time.time()-b['started']>600:
                # Hobby has a one-hour continuous limit. Reserve 45 minutes for
                # the next execution by resetting at a safe idle boundary.
                await self.pause(u,{'id':wid,'deleted_at':None})
                sbx=None;b=self.binding(wid)
            if sbx is None:
                async with self.manager.lock('e2b-create'):
                    # Control-plane inventory includes sandboxes not yet adopted by this process.
                    from e2b import SandboxQuery, SandboxState
                    pages=self.sdk.list(query=SandboxQuery(metadata={'deployment':self.deployment},state=[SandboxState.RUNNING,SandboxState.PAUSED]))
                    inventory=await pages.next_items()
                    while pages.has_next: inventory += await pages.next_items()
                    owned=[s for s in inventory if (s.metadata or {}).get('workspace_id')==wid]
                    candidate=next((s for s in owned if s.sandbox_id==b['sandbox_id']),None)
                    if not candidate and owned and not b['sandbox_id']:
                        candidate=sorted(owned,key=lambda s:s.sandbox_id)[0]
                    if candidate:
                        self.progress(t,'resuming')
                        sbx=await self.sdk.connect(candidate.sandbox_id,timeout=TTL)
                        if str(candidate.state).lower().split('.')[-1]=='paused':self.state(wid,started=time.time())
                        self.record(wid,'sandbox.connect',{'duration_ms':round((time.monotonic()-started)*1000)})
                    else:
                        if b['sandbox_id']:
                            self.record(wid,'sandbox.lost',{'sandbox_id':b['sandbox_id'],'recovery':'latest checkpoint'})
                        if sum(str(s.state).lower().split('.')[-1]=='running' for s in inventory)>=16:
                            raise RuntimeError('E2B 活动环境已达 16 个，请等待其他任务完成')
                        credentials=json.loads(self.models.decrypt(b['credentials'])) if b['credentials'] else {'password':secrets.token_urlsafe(32)}
                        # Persist password before create, so a crash between create and bind is recoverable.
                        self.state(wid,credentials=self.models.encrypt(encoded(credentials)),status='creating')
                        self.progress(t,'creating')
                        await self.pace_creation()
                        sbx=await self.sdk.create(self.template,timeout=TTL,
                            metadata={'deployment':self.deployment,'workspace_id':wid,'user_id':u['id']},
                            network={'allow_public_traffic':False}, lifecycle={'on_timeout':'pause','auto_resume':False})
                        created=True
                        self.file_indexes.pop(wid,None)
                        self.file_stats={k:v for k,v in self.file_stats.items() if k[0]!=wid}
                        self.permission_cache={k:v for k,v in self.permission_cache.items() if k[0]!=wid}
                        self.path_cache={k:v for k,v in self.path_cache.items() if k[0]!=wid}
                        self.state(wid,generation=b['generation']+1,started=time.time(),template=self.template)
                        self.store.execute('DELETE FROM e2b_files WHERE workspace_id=?',(wid,))
                        self.record(wid,'sandbox.create',{'duration_ms':round((time.monotonic()-started)*1000)})
                    credentials=json.loads(self.models.decrypt(self.binding(wid)['credentials']))
                    traffic=sbx.traffic_access_token
                    if not traffic: raise RuntimeError('E2B 未返回受保护端口的访问凭据')
                    credentials.update(url='https://'+sbx.get_host(4096),traffic=traffic)
                    self.state(wid,sandbox_id=sbx.sandbox_id,credentials=self.models.encrypt(encoded(credentials)),status='starting',last_activity=time.time())
                    self.handles[wid]=sbx
            await sbx.set_timeout(TTL)
            self.renewed[wid]=time.monotonic()
            w=self.store.one('SELECT * FROM workspaces WHERE id=?',(wid,));rt=self.runtime(u,w)
            if created:
                try:await self.restore(u,w,sbx)
                except Exception:
                    await sbx.pause();self.handles.pop(wid,None)
                    self.state(wid,status='recovery_failed');raise
            booted=created or not await self.healthy(rt) or b['revision']!=latest['revision']
            if booted:
                if other_active:raise RuntimeError('运行服务暂不可用；其他对话尚未结束，请稍后重试')
                self.progress(t,'starting')
                await self.boot(u,w,sbx,native,auth)
            self.state(wid,status='syncing')
            self.progress(t,'syncing')
            await self.skill_sync.apply(u,w,sbx,exclude_tid=t['id'],force=booted)
            await self.sync_files(u,t,sbx)
            await self.ensure_session(rt,t)
            self.unhealthy.discard(wid)
            self.state(wid,status='ready',revision=latest['revision'],last_activity=time.time(),error=None)
            return rt

    async def ensure_session(self,rt,t):
        if t['session_id'].startswith('pending_'):
            session=await Runtime.call(rt,'POST','/session',tid=t['id'],body={'agent':'contract'})
            self.store.execute('UPDATE threads SET session_id=? WHERE id=?',(session['id'],t['id']))
            t['session_id']=session['id']

    async def healthy(self,rt):
        try: return bool((await asyncio.wait_for(Runtime.call(rt,'GET','/global/health'),3)).get('healthy'))
        except (RuntimeError,asyncio.TimeoutError): return False

    async def boot(self,u,w,sbx,native,auth):
        wid=w['id'];begin=time.monotonic()
        self.permission_cache={k:v for k,v in self.permission_cache.items() if k[0]!=wid}
        self.path_cache={k:v for k,v in self.path_cache.items() if k[0]!=wid}
        await sbx.commands.run('mkdir -p /workspace/threads /workspace/input /workspace/output /workspace/published /workspace/exchange /opt/contract-runtime /var/lib/contract-opencode /var/log/contract-opencode && chown -R user:user /workspace /opt/contract-runtime /var/lib/contract-opencode /var/log/contract-opencode',user='root')
        version=await sbx.commands.run('opencode --version')
        if version.stdout.strip()!='1.16.2': raise RuntimeError('E2B 模板须固定使用 OpenCode 1.16.2，请先构建配套模板')
        uploads=[]
        for p in (ROOT/'runtime').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.name!='publish.py' and p.relative_to(ROOT/'runtime').parts[0] not in {'library','skills','public-examples'}:
                data=p.read_bytes()
                if p.suffix in {'.md','.json'}: data=data.replace(b'publish.py',b'submit.py')
                uploads.append({'path':'/opt/contract-runtime/'+str(p.relative_to(ROOT/'runtime')),'data':data})
        config={**runtime_config(Path('/opt/contract-runtime')),**native}
        config=json.loads(encoded(config).replace('publish.py','submit.py'))
        from .skill_sync import PATHS
        config['skills']={'paths':PATHS}
        uploads.append({'path':'/var/lib/contract-opencode/opencode.json','data':encoded(config)})
        await sbx.files.write_files(uploads)
        self.record(wid,'opencode.files.ready',{'elapsed_ms':round((time.monotonic()-begin)*1000)})
        rt=self.runtime(u,w)
        env={'XDG_DATA_HOME':'/var/lib/contract-opencode/data','XDG_CONFIG_HOME':'/var/lib/contract-opencode/config',
             'XDG_STATE_HOME':'/var/lib/contract-opencode/state','XDG_CACHE_HOME':'/var/lib/contract-opencode/cache',
             'OPENCODE_CONFIG':'/var/lib/contract-opencode/opencode.json','OPENCODE_SERVER_PASSWORD':rt.config['password'],
             'OPENCODE_DISABLE_CLAUDE_CODE':'true','OPENCODE_DISABLE_EXTERNAL_SKILLS':'true','OPENCODE_ENABLE_QUESTION_TOOL':'true',
             'OPENCODE_ENABLE_EXA':'true','OPENCODE_WEBSEARCH_PROVIDER':'exa'}
        # Dedicated PID file, never broad pkill. Only used at idle turn boundaries.
        await sbx.commands.run("if test -f /var/lib/contract-opencode/service.pid; then kill $(cat /var/lib/contract-opencode/service.pid) 2>/dev/null || true; fi")
        await sbx.commands.run("echo $$ > /var/lib/contract-opencode/service.pid; exec opencode --print-logs serve --pure --hostname 0.0.0.0 --port 4096 >> /var/log/contract-opencode/service.log 2>&1",envs=env,cwd='/workspace/threads',background=True,timeout=0)
        self.record(wid,'opencode.process.started',{'elapsed_ms':round((time.monotonic()-begin)*1000)})
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if await self.healthy(rt):break
            await asyncio.sleep(.5)
        else: raise RuntimeError('E2B OpenCode 启动健康检查超时')
        self.record(wid,'opencode.health.ready',{'elapsed_ms':round((time.monotonic()-begin)*1000)})
        prior=self.binding(wid)
        previous=self.models.native(self.models.snapshot(self.models.scope(u),prior['revision']))[1] if prior['revision'] else {}
        for pid in set(previous)-set(auth):await Runtime.call(rt,'DELETE','/auth/'+pid)
        for pid,key in auth.items():
            if key: await Runtime.call(rt,'PUT','/auth/'+pid,body={'type':'api','key':key})
        await Runtime.call(rt,'POST','/global/dispose')
        self.record(wid,'opencode.ready',{'duration_ms':round((time.monotonic()-begin)*1000)})

    async def sync_files(self,u,t,sbx=None):
        begin=time.monotonic()
        wid=t['workspace_id'];sbx=sbx or self.handles[wid];rt=self.runtime(u,{'id':wid})
        # Old templates and restored VMs must never expose the former bundled library.
        removal='/opt/contract-runtime/library'
        if u.get('role')!='admin':removal+=' /opt/contract-runtime/skills/contract-change-risk'
        await sbx.commands.run('rm -rf '+removal)
        docs=self.store.all('SELECT id,source_hash FROM documents WHERE workspace_id=? ORDER BY id',(wid,))
        artifacts=self.store.all('SELECT id,content_hash FROM artifacts WHERE workspace_id=? ORDER BY id',(wid,))
        signature=encoded([docs,artifacts])
        prior=self.file_indexes.get(wid)
        if not prior or prior[0]!=signature:
            shared=[]
            for d in docs:
                for p in (self.store.user_root(u['id'])/'sources'/d['id']).rglob('*'):
                    if p.is_file():shared.append((p,str(PurePosixPath(rt.source_path(d['id'])).parent/p.name)))
            for a in artifacts:
                for p in (self.store.user_root(u['id'])/'published'/a['id']).glob('*'):
                    if p.is_file():shared.append((p,'/workspace/published/'+a['id']+'/'+p.name))
        else:shared=prior[1]
        wd=self.store.user_root(u['id'])/'threads'/t['id'];wd.mkdir(parents=True,exist_ok=True)
        # Native provider headers bind relay calls to this dialogue's active quota lease.
        if self.store.one("SELECT 1 FROM providers WHERE org_id=? AND id='trial'",(self.models.scope(u),)):
            path=wd/'opencode.json';config=json.loads(path.read_text()) if path.exists() else {}
            headers={'X-Workbench-Thread':t['id']}
            provider=config.setdefault('provider',{}).setdefault('trial',{}).setdefault('options',{})
            if provider.get('headers')!=headers:
                provider['headers']=headers;path.write_text(encoded(config))
        # Fixed application-owned files only: no recursive scan of agent output.
        pairs=shared+[(wd/name,rt.directory(t['id'])+'/'+name) for name in
                      ('context.json','risk-library.json','opencode.json','.skill-versions.json') if (wd/name).is_file()]
        changed=[];stats={}
        for local,remote in pairs:
            stat=local.stat();stamp=(stat.st_mtime_ns,stat.st_size,stat.st_ino)
            cache_key=(wid,remote)
            if self.file_stats.get(cache_key)==stamp:continue
            data=local.read_bytes();h=hashlib.sha256(data).hexdigest()
            stats[cache_key]=stamp
            old=self.store.one('SELECT hash FROM e2b_files WHERE workspace_id=? AND path=?',(wid,remote))
            if not old or old['hash']!=h:changed.append((remote,data,h))
        try:
            if changed:
                await sbx.files.write_files([{'path':remote,'data':data} for remote,data,h in changed])
                with self.store.connect() as db:
                    db.executemany('INSERT OR REPLACE INTO e2b_files VALUES(?,?,?)',[(wid,remote,h) for remote,data,h in changed])
            if not prior or prior[0]!=signature:
                desired={remote for _,remote in shared if remote.startswith('/workspace/input/')}
                for old in self.store.all("SELECT path FROM e2b_files WHERE workspace_id=? AND path LIKE '/workspace/input/%'",(wid,)):
                    if old['path'] not in desired:
                        await sbx.files.remove(old['path'])
                        self.store.execute('DELETE FROM e2b_files WHERE workspace_id=? AND path=?',(wid,old['path']))
            self.file_indexes[wid]=(signature,shared)
            self.file_stats.update(stats)
        except Exception:
            self.unhealthy.add(wid)
            self.state(wid,error='文件同步未完成，将在下次准备时重新检查')
            raise
        self.record(wid,'files.sync',{'files':len(changed),'bytes':sum(len(data) for _,data,_ in changed),
                                    'duration_ms':round((time.monotonic()-begin)*1000)},t['id'])

    def history(self,tid):
        row=self.store.one('SELECT * FROM e2b_history WHERE thread_id=?',(tid,))
        return (json.loads(row['messages']),json.loads(row['snapshot'])) if row else ([],{})

    def snapshot(self,tid):
        row=self.store.one('SELECT snapshot FROM e2b_history WHERE thread_id=?',(tid,))
        return json.loads(row['snapshot']) if row else {}

    async def collect_thread(self,u,t):
        rt=Runtime(self.config(u,{'id':t['workspace_id']}))
        if t['session_id'].startswith('pending_'): return
        revision=self.event_revisions.get(t['id'],0)
        messages=await rt.messages(t)
        paths=[('status','/session/status'),('questions','/question'),('permissions','/permission'),('todos',f'/session/{t["session_id"]}/todo'),('info',f'/session/{t["session_id"]}')]
        values=await asyncio.gather(*(Runtime.call(rt,'GET',path,tid=t['id']) for _,path in paths))
        snapshot=dict(zip((key for key,_ in paths),values))
        await asyncio.to_thread(self.save_snapshot,u,t,messages,snapshot,revision)

    def save_snapshot(self,u,t,messages,snapshot,revision):
        # Stream writes and HTTP snapshots must commit in revision order, including
        # when a cancelled async caller still has a persistence worker finishing.
        with self.history_locks[t['id']]:
            self._save_snapshot(u,t,messages,snapshot,revision)

    def _save_snapshot(self,u,t,messages,snapshot,revision):
        if revision!=self.event_revisions.get(t['id'],0):return
        snapshot['status']=snapshot['status'].get(t['session_id'],{'type':'idle'})
        for field in ('questions','permissions'):
            snapshot[field]=[item for item in snapshot[field] if item.get('sessionID')==t['session_id']]
        clean=redact([{**m,'parts':[p for p in m.get('parts',[]) if p.get('type')!='reasoning']} for m in messages],self.secrets(u,t['workspace_id']))
        self.store.execute('INSERT INTO e2b_history VALUES(?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET messages=excluded.messages,snapshot=excluded.snapshot,synced=excluded.synced',
            (t['id'],encoded(clean),encoded(redact(snapshot,self.secrets(u,t['workspace_id']))),time.time()))
        if self.traces:self.traces.sync(u,t,clean,snapshot['status'])
        self.state(t['workspace_id'],synced=time.time())

    def watch(self,u,t):
        task=self.streams.get(t['id'])
        if not task or task.done():
            self.stream_ready[t['id']]=asyncio.Event()
            self.streams[t['id']]=asyncio.create_task(self.stream(u,dict(t)))
        return self.stream_ready[t['id']]

    def ingest_event(self,u,t,event):
        """Persist native SSE updates directly; never await history HTTP per token."""
        with self.history_locks[t['id']]:
            self._ingest_event(u,t,event)

    def _ingest_event(self,u,t,event):
        p=event.get('properties',{});kind=event.get('type')
        owner=p.get('sessionID') or p.get('info',{}).get('sessionID') or p.get('part',{}).get('sessionID')
        if owner!=t['session_id']:return
        messages,snap=self.history(t['id'])
        if kind=='message.updated':
            info=p['info'];found=next((m for m in messages if m['info']['id']==info['id']),None)
            if found:found['info']=info
            else:messages.append({'info':info,'parts':[]})
        elif kind=='message.part.updated':
            part=p['part']
            if part.get('type')=='reasoning':return
            found=next((m for m in messages if m['info']['id']==part['messageID']),None)
            if found is None:return # A full snapshot will recover missed message headers.
            found['parts']=[part if old['id']==part['id'] else old for old in found['parts']] if any(old['id']==part['id'] for old in found['parts']) else [*found['parts'],part]
        elif kind=='message.part.delta':
            part=next((part for m in messages if m['info']['id']==p['messageID'] for part in m['parts'] if part['id']==p['partID']),None)
            if not part or part.get('type')!='text' or p.get('field')!='text':return
            part['text']=part.get('text','')+p['delta']
        elif kind=='session.status':snap['status']=p['status']
        elif kind=='todo.updated':snap['todos']=p['todos']
        elif kind in {'question.asked','permission.asked'}:
            field='questions' if kind.startswith('question.') else 'permissions'
            snap[field]=[q for q in snap.get(field,[]) if q['id']!=p['id']]+[p]
        elif kind in {'question.replied','question.rejected','permission.replied'}:
            field='questions' if kind.startswith('question.') else 'permissions'
            snap[field]=[q for q in snap.get(field,[]) if q['id']!=p['requestID']]
        else:return
        self.event_revisions[t['id']]=self.event_revisions.get(t['id'],0)+1
        secret_values=self.secrets(u,t['workspace_id'])
        clean=redact(messages,secret_values);snapshot=redact(snap,secret_values)
        self.store.execute('INSERT INTO e2b_history VALUES(?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET messages=excluded.messages,snapshot=excluded.snapshot,synced=excluded.synced',
                           (t['id'],encoded(clean),encoded(snapshot),time.time()))
        self.state(t['workspace_id'],synced=time.time())

    async def stream(self,u,t):
        last_error=None
        while t['workspace_id'] in self.handles:
            try:
                rt=Runtime(self.config(u,{'id':t['workspace_id']}))
                async for event in Runtime.events(rt,t):
                    if event.get('type')=='server.connected':self.stream_ready[t['id']].set()
                    await asyncio.to_thread(self.ingest_event,u,t,event)
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.stream_ready[t['id']].clear()
                if str(exc)!=last_error:
                    last_error=str(exc);self.record(t['workspace_id'],'stream.reconnect',{'error':str(exc)},t['id'])
                await asyncio.sleep(2)
            finally:self.stream_ready[t['id']].clear()

    async def collect_submissions(self,u,w,sbx):
        entries=await sbx.files.list('/workspace/exchange',depth=1)
        for entry in entries:
            if not entry.name.endswith('.request.json'):continue
            if getattr(entry,'size',0)>4_100_000:raise RuntimeError('保存申请过大')
            raw=await sbx.files.read(entry.path,format='bytes')
            if len(raw)>4_100_000:raise RuntimeError('保存申请过大')
            req=json.loads(raw);rid=req.get('request_id','')
            if not isinstance(rid,str) or not __import__('re').fullmatch('[a-f0-9]{64}',rid):raise RuntimeError('保存申请标识无效')
            t=self.store.one('SELECT * FROM threads WHERE id=? AND workspace_id=?',(req.get('thread_id'),w['id']))
            if not t:raise RuntimeError('保存申请不属于当前合同')
            e=self.store.one('SELECT * FROM execution_configs WHERE id=? AND thread_id=?',(req.get('execution_id'),t['id']))
            if not e:raise RuntimeError('保存申请没有对应执行记录')
            payload=req.get('report');h=hashlib.sha256(encoded(payload).encode()).hexdigest()
            old=self.store.one('SELECT * FROM e2b_receipts WHERE request_id=?',(rid,))
            if old:
                if old['workspace_id']!=w['id'] or old['hash']!=h or old['execution_id']!=e['id']:raise RuntimeError('保存请求标识冲突')
                receipt=json.loads(old['receipt'])
            else:
                try:
                    if t['archived_at'] or t['deleted_at'] or w['deleted_at'] or not u['active']:raise ValueError('当前对话不可保存')
                    latest=self.store.one('SELECT id FROM execution_configs WHERE thread_id=? ORDER BY created DESC LIMIT 1',(t['id'],))
                    if latest['id']!=e['id']:raise ValueError('保存申请已过期，请重新生成')
                    # Validation uses fresh native evidence, not the redacted UI
                    # mirror (redaction can alter quoted contract text).
                    native=await Runtime(self.config(u,w)).messages(t)
                    receipt=await self.artifacts.save(u,t,w,payload,self.runtime(u,w),native=native)
                except (ValueError,HTTPException) as exc:
                    receipt={'saved':False,'error':redact(str(getattr(exc,'detail',exc)),self.secrets(u,w['id']))}
                self.store.execute('INSERT INTO e2b_receipts(request_id,workspace_id,execution_id,hash,receipt) VALUES(?,?,?,?,?)',(rid,w['id'],e['id'],h,encoded(receipt)))
                self.record(w['id'],'artifact.saved' if receipt.get('saved') else 'artifact.failed',receipt,t['id'])
            await sbx.files.write('/workspace/exchange/'+rid+'.receipt.json',encoded(receipt))
            self.store.execute('UPDATE e2b_receipts SET delivered=1 WHERE request_id=?',(rid,))
            await sbx.files.remove(entry.path)

    async def checkpoint(self,u,w,sbx):
        # Helper uses SQLite backup API; never copy an open WAL database as a file.
        await sbx.commands.run('python3 /opt/contract-runtime/scripts/checkpoint.py backup',timeout=120)
        data=bytes(await sbx.files.read('/tmp/contract-checkpoint.tar.gz',format='bytes'))
        root=self.archive(u,w['id'])/'checkpoints';root.mkdir(exist_ok=True)
        p=root/(str(time.time_ns())+'.fernet');p.write_bytes(self.models.cipher.encrypt(data));p.chmod(0o600)
        for old in sorted(root.glob('*.fernet'))[:-3]:old.unlink()
        self.record(w['id'],'checkpoint.saved',{'bytes':len(data)})

    async def restore(self,u,w,sbx):
        root=self.archive(u,w['id'])/'checkpoints';files=sorted(root.glob('*.fernet'))
        if not files:
            old=self.store.one("SELECT 1 FROM e2b_history h JOIN threads t ON t.id=h.thread_id WHERE t.workspace_id=? AND h.messages!='[]'",(w['id'],))
            if old:raise RuntimeError('原生会话缺少恢复备份，历史仍可查看；请新建合同空间，不会伪造或重发历史')
            return
        data=self.models.cipher.decrypt(files[-1].read_bytes())
        await sbx.files.write('/tmp/contract-checkpoint.tar.gz',data)
        await sbx.files.write('/tmp/contract-checkpoint.py',(ROOT/'runtime/scripts/checkpoint.py').read_bytes())
        await sbx.commands.run('python3 /tmp/contract-checkpoint.py restore',user='root',timeout=120)
        self.record(w['id'],'checkpoint.restored',{'checkpoint':files[-1].name})

    async def pause(self,u,w):
        wid=w['id'];sbx=self.handles.get(wid)
        if not sbx:return
        self.state(wid,status='pausing')
        await sbx.set_timeout(TTL)
        await self.collect_submissions(u,w,sbx)
        await self.checkpoint(u,w,sbx)
        await sbx.pause()
        streams=[self.streams.pop(t['id']) for t in self.store.all('SELECT id FROM threads WHERE workspace_id=?',(wid,)) if t['id'] in self.streams]
        for task in streams:task.cancel()
        await asyncio.gather(*streams,return_exceptions=True)
        self.handles.pop(wid,None);self.state(wid,status='paused');self.record(wid,'sandbox.pause')

    async def destroy(self,u,w):
        wid=w['id'];b=self.binding(wid)
        if not b or not b['sandbox_id']:return
        if wid not in self.handles and b['status'] not in {'lost','killed','recovery_failed'}:
            # Explicit destruction first flushes a paused VM's last state.
            sbx=await self.sdk.connect(b['sandbox_id'],timeout=TTL)
            credentials=json.loads(self.models.decrypt(b['credentials']))
            credentials.update(url='https://'+sbx.get_host(4096),traffic=sbx.traffic_access_token)
            self.state(wid,credentials=self.models.encrypt(encoded(credentials)))
            self.handles[wid]=sbx
            for t in self.store.all('SELECT * FROM threads WHERE workspace_id=?',(wid,)):
                await self.collect_thread(u,t)
        if wid in self.handles:await self.pause(u,w)
        await self.sdk.kill(b['sandbox_id'])
        self.handles.pop(wid,None);self.state(wid,status='killed',sandbox_id=None)
        self.record(wid,'sandbox.kill')

    async def maintenance(self):
        last_logs={};last_checkpoint={};last_renew={}
        while True:
            for wid,sbx in list(self.handles.items()):
                try:
                    u=self.owner(wid)
                    threads=self.store.all('SELECT * FROM threads WHERE workspace_id=?',(wid,))
                    await asyncio.gather(*(self.collect_thread(u,t) for t in threads if not t['session_id'].startswith('pending_')))
                    async with self.manager.lock('e2b-'+wid):
                        if self.handles.get(wid) is not sbx:continue
                        w=self.store.one('SELECT * FROM workspaces WHERE id=?',(wid,));b=self.binding(wid)
                        for t in threads:
                            if not t['session_id'].startswith('pending_'):self.watch(u,t)
                        await self.collect_submissions(u,w,sbx)
                        # Waiting in one dialogue must not stop renewal for another.
                        snapshots={t['id']:self.snapshot(t['id']) for t in threads}
                        for t in threads:
                            snap=snapshots[t['id']]
                            active_turn=self.store.one("SELECT created FROM execution_configs WHERE thread_id=? AND status IN ('starting','running') ORDER BY created DESC LIMIT 1",(t['id'],))
                            limit=2700 if u['role']=='admin' else self.settings.accounts.limits()['run_seconds']
                            if snap.get('status',{}).get('type','idle')!='idle' and active_turn and time.time()-active_turn['created']>limit:
                                await Runtime.call(self.runtime(u,w),'POST',f'/session/{t["session_id"]}/abort',tid=t['id'])
                                self.record(wid,'execution.timeout',{'limit_seconds':limit},t['id'])
                                snap['status']={'type':'idle'}
                        runnable=any(s.get('status',{}).get('type','idle')!='idle' and not (s.get('questions') or s.get('permissions')) for s in snapshots.values())
                        active=self.store.one("SELECT MIN(e.created) AS created FROM execution_configs e JOIN threads t ON t.id=e.thread_id WHERE t.workspace_id=? AND e.status IN ('starting','running')",(wid,))
                        dispatching=self.store.one("SELECT 1 FROM queued_messages q JOIN threads t ON t.id=q.thread_id WHERE t.workspace_id=? AND q.status='dispatching'",(wid,))
                        if (runnable or dispatching) and u['active']:
                            if time.time()-last_renew.get(wid,0)>60:
                                await sbx.set_timeout(TTL);last_renew[wid]=time.time();self.renewed[wid]=time.monotonic()
                            self.state(wid,last_activity=time.time())
                        elif time.time()-b['last_activity']>=TTL-15 and not self.store.one("SELECT 1 FROM queued_messages q JOIN threads t ON t.id=q.thread_id WHERE t.workspace_id=? AND q.status='dispatching'",(wid,)):
                            await self.pause(u,w);continue
                        elif active and active['created'] and time.time()-last_checkpoint.get(wid,0)>30:
                            await self.checkpoint(u,w,sbx);last_checkpoint[wid]=time.time()
                        if wid in self.pending_checkpoints:
                            await self.checkpoint(u,w,sbx)
                            self.pending_checkpoints.discard(wid)
                        # Incremental log extraction, with bounded chunks and persisted cursor.
                        logroot=self.archive(u,wid)/'logs'/str(b['generation']);logroot.mkdir(parents=True,exist_ok=True)
                        cursor=logroot/'offset';offset=int(cursor.read_text()) if cursor.exists() else 0
                        result=await sbx.commands.run('python3 /opt/contract-runtime/scripts/checkpoint.py log '+str(offset))
                        log=json.loads(result.stdout)
                        if log['text']:
                            with (logroot/'service.log').open('a') as f:f.write(redact(log['text'],self.secrets(u,wid)))
                            cursor.write_text(str(log['offset']))
                        if time.time()-last_logs.get(wid,0)>86400:
                            for p in (self.archive(u,wid)/'logs').rglob('*'):
                                if p.is_file() and p.stat().st_mtime<time.time()-30*86400:p.unlink()
                            last_logs[wid]=time.time()
                except asyncio.CancelledError:raise
                except Exception as exc:
                    try:
                        info=await sbx.get_info()
                        if str(info.state).lower().split('.')[-1]=='paused':
                            self.handles.pop(wid,None);self.state(wid,status='paused')
                    except Exception:pass
                    if isinstance(exc,RuntimeError):self.unhealthy.add(wid)
                    self.state(wid,error=redact(str(exc),self.secrets(self.owner(wid),wid)))
                    self.record(wid,'sync.failed',{'error':str(exc)})
            await asyncio.sleep(5)

    async def reconcile(self):
        from e2b import SandboxQuery, SandboxState
        pages=self.sdk.list(query=SandboxQuery(metadata={'deployment':self.deployment},state=[SandboxState.RUNNING,SandboxState.PAUSED]))
        items=await pages.next_items()
        while pages.has_next:items+=await pages.next_items()
        ids={s.sandbox_id for s in items}
        for item in items:
            wid=(item.metadata or {}).get('workspace_id')
            if not wid:continue
            w=self.store.one('SELECT * FROM workspaces WHERE id=?',(wid,));b=self.binding(wid)
            age=time.time()-item.started_at.timestamp()
            if not w or (b and b['sandbox_id'] and b['sandbox_id']!=item.sandbox_id):
                # Creation and reconciliation share a lock; allow ten minutes
                # before disposing an unbound duplicate from this deployment.
                if age>600:await self.sdk.kill(item.sandbox_id)
                continue
            if not b or not b['credentials']:continue
            state=str(item.state).lower().split('.')[-1]
            self.state(wid,sandbox_id=item.sandbox_id,status=b['status'] if b['status']=='recovery_failed' else 'paused' if state=='paused' else 'ready')
            if state=='running' and wid not in self.handles:
                sbx=await self.sdk.connect(item.sandbox_id,timeout=TTL)
                creds=json.loads(self.models.decrypt(b['credentials']))
                if sbx.traffic_access_token:creds['traffic']=sbx.traffic_access_token
                creds['url']='https://'+sbx.get_host(4096)
                self.state(wid,credentials=self.models.encrypt(encoded(creds)))
                self.handles[wid]=sbx
        for b in self.store.all('SELECT * FROM e2b_bindings WHERE sandbox_id IS NOT NULL'):
            if b['sandbox_id'] not in ids:
                self.handles.pop(b['workspace_id'],None)
                self.state(b['workspace_id'],status='lost')

    async def start(self):
        async def reconcile_loop():
            while True:
                if os.environ.get('E2B_API_KEY') or self.sandbox_class:
                    try:
                        async with self.manager.lock('e2b-create'):await self.reconcile()
                    except asyncio.CancelledError:raise
                    except Exception:pass # Local uploads/history remain available.
                await asyncio.sleep(600)
        self.tasks=[asyncio.create_task(self.maintenance()),asyncio.create_task(reconcile_loop()),asyncio.create_task(self.skill_sync.run())]

    async def close(self):
        tasks=self.tasks+list(self.streams.values())
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        # No kill on shutdown. The provider's timeout pauses a disconnected VM.

    def diagnostics(self,wid):
        b=self.binding(wid) or {'status':'new'}
        events=self.store.all('SELECT kind,thread_id,execution_id,data,created FROM e2b_events WHERE workspace_id=? ORDER BY id DESC LIMIT 100',(wid,))
        for e in events:e['data']=json.loads(e['data'])
        logs=[]
        u=self.owner(wid);root=self.archive(u,wid)/'logs'
        for p in sorted(root.glob('*/service.log'))[-3:]:
            with p.open('rb') as f:
                f.seek(max(0,p.stat().st_size-32000));tail=f.read().decode('utf-8',errors='replace')
            logs.append({'generation':p.parent.name,'text':redact(tail,self.secrets(u,wid))})
        return {'binding':{k:v for k,v in b.items() if k!='credentials'},'events':events,'logs':logs}


class E2BRuntime(Runtime):
    def __init__(self,e2b,u,w):
        self.e2b,self.u,self.w=e2b,u,w
        super().__init__(e2b.config(u,w))

    def source_path(self,docid):
        d=self.e2b.store.one('SELECT * FROM documents WHERE id=? AND user_id=?',(docid,self.u['id']))
        if not d or (self.w and d['workspace_id']!=self.w['id']):raise RuntimeError('材料不属于当前合同')
        return '/workspace/input/'+docid+'/'+d['source_hash']+'/contract.md'

    async def models(self):
        _,native,_=self.e2b.catalog(self.u)
        return {'default':native.get('model'),'models':[{'id':pid+'/'+mid,'providerID':pid,'modelID':mid,'label':m.get('name',mid)} for pid,p in native.get('provider',{}).items() for mid,m in p.get('models',{}).items()]}

    async def skills(self,tid):
        row=self.e2b.skill_sync.row(self.w['id']) if self.w else None
        items=json.loads(row['items']) if row and row['revision'] else self.e2b.settings.items(self.u,'skill')
        return [{'name':s['name'],'label':s['content'].get('label',s['name']),'description':s['content'].get('description','')} for s in items if s['enabled']]

    async def refresh_skills(self,tid,directory):return await self.skills(tid)

    async def call(self,method,path,*,tid=None,**kwargs):
        # GETs used by UI and traces are satisfied from the last persisted state.
        if path.startswith('/session/pending_') and method!='GET':return None
        if tid:
            if method=='GET':
                snap=self.e2b.snapshot(tid)
                if path=='/session/status':
                    t=self.e2b.store.one('SELECT session_id FROM threads WHERE id=?',(tid,))
                    return {t['session_id']:snap.get('status',{'type':'idle'})}
                if path in {'/question','/permission'}:return snap.get('questions' if path=='/question' else 'permissions',[])
                if path.endswith('/todo'):return snap.get('todos',[])
                if path.endswith('/message'):
                    messages=(await asyncio.to_thread(self.e2b.history,tid))[0]
                    limit=kwargs.get('params',{}).get('limit');return messages[-limit:] if limit else messages
                if path.startswith('/session/'):
                    return snap.get('info',{})
        if method=='POST' and (path.endswith('/reply') or path.endswith('/abort')) and self.w and self.w['id'] not in self.e2b.handles:
            t=self.e2b.store.one('SELECT * FROM threads WHERE id=?',(tid,))
            resumed=await self.e2b.prepare(self.u,t,recovering=True)
            self.config=resumed.config
        if method=='POST' and path=='/instance/dispose':
            if not self.config.get('staging_only') and self.w and self.w['id'] in self.e2b.handles:
                t=self.e2b.store.one('SELECT * FROM threads WHERE id=?',(tid,))
                if t:await self.e2b.sync_files(self.u,t)
                return await super().call(method,path,tid=tid,**kwargs)
            return None
        if method=='PATCH' and path.startswith('/session/') and (not self.w or self.w['id'] not in self.e2b.handles):return None
        if not self.w or self.w['id'] not in self.e2b.handles:
            raise RuntimeError('E2B 环境未运行；历史来自本地已同步记录')
        key=(self.w['id'],tid)
        if method=='GET' and path=='/path' and key in self.e2b.path_cache:return self.e2b.path_cache[key]
        permission=kwargs.get('body',{}).get('permission') if method=='PATCH' else None
        if permission is not None and self.e2b.permission_cache.get(key)==permission:return None
        try:result=await super().call(method,path,tid=tid,**kwargs)
        except RuntimeError:
            self.e2b.unhealthy.add(self.w['id'])
            self.e2b.state(self.w['id'],error='原生连接异常，下次准备时检查恢复')
            raise
        if method=='GET' and path=='/path':self.e2b.path_cache[key]=result
        if permission is not None:self.e2b.permission_cache[key]=permission
        if method=='POST' and (path.endswith('/reply') or path.endswith('/abort')):
            t=self.e2b.store.one('SELECT * FROM threads WHERE id=?',(tid,))
            if path.endswith('/reply'):
                kind,rid=path.strip('/').split('/')[:2]
                await asyncio.to_thread(self.e2b.ingest_event,self.u,t,{'type':kind+'.replied','properties':{'sessionID':t['session_id'],'requestID':rid}})
            else:
                await self.e2b.collect_thread(self.u,t)
            self.e2b.state(self.w['id'],last_activity=time.time())
        return result

    async def messages(self,t):return (await asyncio.to_thread(self.e2b.history,t['id']))[0]
    async def status(self,t):return self.e2b.snapshot(t['id']).get('status',{'type':'idle'})
    async def permissions(self,tid,documents,mode='auto'):
        if mode=='full':return [{'permission':'*','pattern':'*','action':'allow'}]
        if not self.w or self.w['id'] not in self.e2b.handles:return []
        rules=await super().permissions(tid,documents,mode)
        for rule in rules:rule['pattern']=rule['pattern'].replace('publish.py','submit.py')
        rules += [{**rule,'pattern':rule['pattern'].replace('python3 ','python ',1)}
                  for rule in rules if rule['permission']=='bash' and rule['pattern'].startswith('python3 ')]
        for perm in ['read','external_directory']:
            rules.append({'permission':perm,'pattern':'/workspace/published/*' if perm=='external_directory' else 'workspace/published/*','action':'allow'})
        return rules

    async def events(self,t):
        seen={};pending={'question':set(),'permission':set()};synced=object()
        while True:
            current=self.e2b.store.one('SELECT * FROM threads WHERE id=?',(t['id'],))
            if not current:return
            t.update(current)
            row=self.e2b.store.one('SELECT synced FROM e2b_history WHERE thread_id=?',(t['id'],))
            stamp=row['synced'] if row else None
            if synced==stamp:
                yield {'type':'workbench.heartbeat'}
                await asyncio.sleep(.25)
                continue
            synced=stamp
            messages,snap=await asyncio.to_thread(self.e2b.history,t['id'])
            for m in messages:
                info=m['info'];key=info['id'];stamp=encoded(info)
                if seen.get(key)!=stamp:
                    seen[key]=stamp;yield {'type':'message.updated','properties':{'info':info}}
                for part in m.get('parts',[]):
                    key=part.get('id');stamp=encoded(part)
                    if seen.get(key)!=stamp:
                        seen[key]=stamp;yield {'type':'message.part.updated','properties':{'part':part}}
            for kind,field in [('question.asked','questions'),('permission.asked','permissions')]:
                for q in snap.get(field,[]):
                    key=q['id'];stamp=encoded(q)
                    if seen.get(key)!=stamp:
                        seen[key]=stamp;yield {'type':kind,'properties':q}
            for kind,field in [('question','questions'),('permission','permissions')]:
                now={q['id'] for q in snap.get(field,[])}
                for rid in pending[kind]-now:
                    yield {'type':kind+'.replied','properties':{'sessionID':t['session_id'],'requestID':rid}}
                    seen.pop(rid,None)
                pending[kind]=now
            for kind,field,default in [('todo.updated','todos',[]),('session.status','status',{'type':'idle'})]:
                value=snap.get(field,default);stamp=encoded(value)
                if seen.get(kind)!=stamp:
                    seen[kind]=stamp
                    yield {'type':kind,'properties':{'sessionID':t['session_id'],field:value}}
            # Keep the transport alive without announcing an unchanged UI state.
            yield {'type':'workbench.heartbeat'}
            await asyncio.sleep(.25)
