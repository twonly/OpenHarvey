"""Per-user local process lifecycle. Driver boundary is reserved for cloud sandboxes."""
import asyncio
import fcntl
from contextlib import asynccontextmanager
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Protocol

import httpx

from .cli import runtime_config, ROOT
from .runtime import Runtime, RuntimeError
from .settings import encoded


class RuntimeDriver(Protocol):
    async def health(self,config): ...
    async def start(self,root,config,oc): ...
    async def stop(self,config): ...


class LocalProcessDriver:
    async def health(self,config):
        try:
            async with httpx.AsyncClient(base_url=config['url'],auth=('opencode',config['password']),trust_env=False,timeout=2) as c:
                r=await c.get('/global/health')
                return r.status_code==200 and r.json().get('healthy',False)
        except (httpx.HTTPError,ValueError):return False

    def pid(self,config):
        port=config['url'].rsplit(':',1)[-1]
        result=subprocess.run(['lsof','-nP','-tiTCP:'+port,'-sTCP:LISTEN'],capture_output=True,text=True)
        for value in result.stdout.split():
            if not value.isdigit():continue
            cmd=subprocess.run(['ps','-p',value,'-o','command='],capture_output=True,text=True).stdout
            if 'opencode' in cmd and ('--port '+port in cmd or '--port='+port in cmd):return int(value)
        return None

    async def start(self,root,config,oc):
        binary=shutil.which('opencode')
        if not binary:raise RuntimeError('找不到 opencode，请先安装 OpenCode 1.16.2')
        state=root/'opencode';state.mkdir(parents=True,exist_ok=True)
        path=state/'opencode.json';tmp=path.with_suffix('.tmp');tmp.write_text(encoded(oc));tmp.chmod(0o600);tmp.replace(path)
        env={k:v for k,v in os.environ.items() if not k.startswith(('CW_','E2B_','RAILWAY_','SUPABASE_','OPENCODE_','ANTHROPIC_','OPENAI_','DEEPSEEK_','GLM_','ZHIPU_'))}
        env.update({'XDG_CONFIG_HOME':str(state/'config'),'XDG_DATA_HOME':str(state/'data'),'XDG_STATE_HOME':str(state/'state'),'XDG_CACHE_HOME':str(state/'cache'),
                    'OPENCODE_CONFIG':str(path),'OPENCODE_SERVER_PASSWORD':config['password'],'OPENCODE_DISABLE_CLAUDE_CODE':'true','OPENCODE_ENABLE_QUESTION_TOOL':'true','OPENCODE_DISABLE_EXTERNAL_SKILLS':'true',
                    'OPENCODE_ENABLE_EXA':'true','OPENCODE_WEBSEARCH_PROVIDER':'exa','OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX':'384000'})
        with (state/'service.log').open('ab') as log:
            process=subprocess.Popen([binary,'serve','--pure','--hostname','127.0.0.1','--port',config['url'].rsplit(':',1)[-1]],cwd=root/'threads',env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError('OpenCode 启动失败，请检查运行环境日志')
            if await self.health(config):return process.pid
            await asyncio.sleep(.3)
        # Only stop the process started by this operation.
        process.terminate()
        raise RuntimeError('OpenCode 启动健康检查超时')

    async def stop(self,config):
        # An authenticated health check plus exact listener command prevents a
        # stale saved PID from terminating an unrelated process after PID reuse.
        pid=self.pid(config)
        if not pid:return
        if not await self.health(config):
            raise RuntimeError('无法验证运行进程身份，停止操作未执行；请检查该账号的原生服务')
        os.kill(pid,signal.SIGTERM)
        for _ in range(40):
            if self.pid(config)!=pid:return
            await asyncio.sleep(.1)
        if self.pid(config)==pid:os.kill(pid,signal.SIGKILL)


class RuntimeManager:
    def __init__(self,settings,models,driver=None):
        self.settings,self.models,self.store=settings,models,settings.store
        self.driver=driver or LocalProcessDriver();self.tasks=set();self.locks={};self.config_lock=asyncio.Lock();self.org_locks={};self.loop_task=None
        self.web_url=os.environ.get('CW_PUBLIC_ORIGIN','http://127.0.0.1:8830')

    @asynccontextmanager
    async def lock(self,uid):
        # Also serializes the brief overlap between old and new Web processes.
        # The lock lives outside Agent directories and is released on process exit.
        async with self.locks.setdefault(uid,asyncio.Lock()):
            folder=self.store.root/'runtime-locks';folder.mkdir(exist_ok=True)
            with (folder/(uid+'.lock')).open('a') as file:
                while True:
                    try:fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:await asyncio.sleep(.1)
                try:yield
                finally:fcntl.flock(file,fcntl.LOCK_UN)


    def instance(self,uid):return self.store.one('SELECT * FROM runtime_instances WHERE user_id=?',(uid,))

    def state(self,uid,**fields):
        row=self.instance(uid)
        if not row:
            self.store.execute('INSERT INTO runtime_instances(user_id,updated) VALUES(?,?)',(uid,time.time()))
        if fields:
            allowed={'pid','status','desired_revision','applied_revision','error'}
            if set(fields)-allowed:raise ValueError('运行状态字段无效')
            self.store.execute('UPDATE runtime_instances SET '+','.join(k+'=?' for k in fields)+',updated=? WHERE user_id=?',(*fields.values(),time.time(),uid))
        return self.instance(uid)

    async def config(self,u):
        async with self.lock('runtime-map'):
            path=self.store.root/'runtimes.json'
            configs=json.loads(path.read_text()) if path.exists() else {}
            if u['username'] in configs:return configs[u['username']]
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            root=self.store.user_root(u['id'])
            for directory in ('sources','threads','published'): (root/directory).mkdir(parents=True,exist_ok=True)
            config={'url':f'http://127.0.0.1:{port}','password':secrets.token_urlsafe(32),'work_root':str(root/'threads'),'source_root':str(root/'sources'),
                    'skill_root':str(ROOT/'runtime'),'save_url':self.web_url.rstrip('/')+'/internal/artifacts','local':True}
            configs[u['username']]=config
            tmp=path.with_suffix('.tmp');tmp.write_text(encoded(configs));tmp.chmod(0o600);tmp.replace(path)
            return config

    async def busy(self,u,config):
        if not await self.driver.health(config):return False
        rt=Runtime(config)
        if self.store.one("SELECT 1 FROM execution_configs WHERE user_id=? AND status='starting' AND created>?",(u['id'],time.time()-30)):return True
        # OpenCode instance state is scoped by directory. The root endpoint can
        # be idle while a thread is running or waiting for a native approval.
        threads=self.store.all('SELECT t.id FROM threads t JOIN workspaces w ON w.id=t.workspace_id WHERE w.user_id=?',(u['id'],))
        semaphore=asyncio.Semaphore(4)
        async def active(tid):
            async with semaphore:
                status,questions,permissions=await asyncio.gather(*(rt.call('GET',path,tid=tid) for path in ('/session/status','/question','/permission')))
                return bool(questions or permissions or any(s.get('type')!='idle' for s in status.values()))
        return any(await asyncio.gather(*(active(tid) for tid in [None,*[t['id'] for t in threads]])))

    async def auth(self,config,auth,previous=()):
        rt=Runtime(config)
        for pid in set(previous)-set(auth):await rt.call('DELETE','/auth/'+pid)
        for pid,key in auth.items():
            if key:await rt.call('PUT','/auth/'+pid,body={'type':'api','key':key})
            else:await rt.call('DELETE','/auth/'+pid)
        await rt.call('POST','/global/dispose')

    async def ensure(self,u,revision=None):
        if getattr(self,'e2b',None) and self.e2b.enabled and not self.store.one("SELECT 1 FROM workspaces WHERE user_id=? AND backend='local'",(u['id'],)):
            latest=self.models.latest(self.models.scope(u))
            return self.state(u['id'],status='ready',desired_revision=revision or (latest['revision'] if latest else 0),error=None)
        async with self.lock(u['id']):
            fresh=self.store.one('SELECT * FROM users WHERE id=?',(u['id'],))
            if not fresh['active']:return self.state(u['id'],status='disabled')
            config=await self.config(u)
            if not config.get('local'):raise RuntimeError('此账号使用外部运行环境，请由对应运行管理器开通')
            latest=self.store.one('SELECT * FROM model_versions WHERE org_id=? AND validated=1 ORDER BY revision DESC LIMIT 1',(self.models.scope(u),))
            desired=revision if revision is not None else latest['revision'] if latest else 0
            state=self.state(u['id'],desired_revision=desired)
            healthy=await self.driver.health(config)
            generated_matches = True
            if desired:
                try:
                    generated = self.models.native(self.models.snapshot(self.models.scope(u), desired))[0]
                    installed = json.loads((self.store.user_root(u['id'])/'opencode'/'opencode.json').read_text())
                    defaults = runtime_config(ROOT/'runtime')
                    generated_matches = (installed.get('provider') == generated.get('provider')
                        and installed.get('agent',{}).get('contract',{}).get('prompt') == defaults['agent']['contract']['prompt']
                        and installed.get('permission') == defaults['permission'])
                except (OSError, ValueError):generated_matches = False
            if healthy and state['applied_revision']==desired and state['status']=='ready' and generated_matches:return state
            if healthy and await self.busy(u,config):return self.state(u['id'],status='ready',desired_revision=desired)
            # If there is no managed model registry, preserve the existing runtime.
            if healthy and not desired:return self.state(u['id'],status='ready',pid=self.driver.pid(config) if hasattr(self.driver,'pid') else None)
            self.state(u['id'],status='provisioning',error=None)
            root=self.store.user_root(u['id']);ocpath=root/'opencode'/'opencode.json'
            previous=ocpath.read_bytes() if ocpath.exists() else None
            prior_rows=self.models.snapshot(self.models.scope(u),state['applied_revision']) if state['applied_revision'] else []
            rows=self.models.snapshot(self.models.scope(u),desired) if desired else []
            native,auth=self.models.native(rows)
            if not native.get('provider') and not desired:
                self.state(u['id'],status='failed',error='请先配置至少一个可用模型')
                raise RuntimeError('请先配置至少一个可用模型')
            old_model=fresh.get('model')
            if old_model and old_model in {pid+'/'+mid for pid,p in native['provider'].items() for mid in p['models']}:
                native['model']=old_model
            try:
                if healthy:await self.driver.stop(config)
                pid=await self.driver.start(root,config,{**runtime_config(ROOT/'runtime'),**native})
                await self.auth(config,auth,[r['id'] for r in prior_rows])
                catalog=await Runtime(config).models()
                expected={pid+'/'+mid for pid,p in native['provider'].items() for mid in p['models']}
                if expected!={m['id'] for m in catalog['models']}:raise RuntimeError('原生模型配置未完整加载')
                return self.state(u['id'],status='ready',pid=pid,applied_revision=desired,error=None)
            except Exception as exc:
                try:
                    await self.driver.stop(config)
                    if previous:
                        old=json.loads(previous);await self.driver.start(root,config,old)
                        if prior_rows:await self.auth(config,self.models.native(prior_rows)[1],auth)
                finally:
                    self.state(u['id'],status='ready' if previous and await self.driver.health(config) else 'failed',error=str(exc))
                raise

    async def stop(self,u):
        async with self.lock(u['id']):
            try:config=self.store.runtime(u['username'])
            except (FileNotFoundError,KeyError):config=None
            if config and config.get('local'):await self.driver.stop(config)
            return self.state(u['id'],status='disabled',pid=None)

    def operation(self,u,kind,target,action):
        oid=secrets.token_hex(12);now=time.time()
        self.store.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?)',(oid,u['org_id'],u['id'],kind,target,'running','{}',now,now))
        async def work():
            try:
                result=await action()
                self.store.execute("UPDATE operations SET status='completed',result=?,updated=? WHERE id=?",(encoded(result or {}),time.time(),oid))
            except asyncio.CancelledError:
                self.store.execute("UPDATE operations SET status='failed',result=?,updated=? WHERE id=?",(encoded({'message':'服务重启中，请重试此管理操作'}),time.time(),oid));raise
            except Exception as exc:
                from .traces import redact
                if kind in {'member.provision','member.restore'}:
                    self.state(target,status='failed',error=redact(str(exc)))
                self.store.execute("UPDATE operations SET status='failed',result=?,updated=? WHERE id=?",(encoded({'message':redact(str(exc))}),time.time(),oid))
        task=asyncio.create_task(work());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        return {'operation_id':oid,'status':'running'}

    async def probe(self,rows,model_id=None):
        """A disposable native instance, with no contracts and no business tools."""
        rows=[r for r in rows if r['id']!='trial']
        if not rows:return {'ok':True,'message':'平台试用模型由任务额度控制'}
        if getattr(self,'e2b',None) and self.e2b.enabled:return await self.e2b.probe(rows,model_id)
        native,auth=self.models.native(rows)
        candidates=[(pid,mid) for pid,p in native['provider'].items() for mid in p['models'] if not model_id or pid+'/'+mid==model_id]
        if not candidates:raise RuntimeError('配置错误：没有可测试的启用模型')
        root=Path(tempfile.mkdtemp(prefix='opencode-probe-'));(root/'threads').mkdir()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config={'url':f'http://127.0.0.1:{port}','password':secrets.token_urlsafe(32),'work_root':str(root/'threads'),'skill_root':str(ROOT/'runtime')}
        config_body={'share':'disabled','autoupdate':False,'snapshot':False,'permission':{'*':'deny'},'agent':{'probe':{'mode':'primary','prompt':'Reply OK to this connectivity test. Do not use tools.'}},'default_agent':'probe',**native}
        results=[]
        try:
            await self.driver.start(root,config,config_body);await self.auth(config,auth)
            rt=Runtime(config)
            for pid,mid in candidates:
                started=time.monotonic()
                session=await rt.call('POST','/session',body={'title':'连接测试'})
                await rt.call('POST',f'/session/{session["id"]}/prompt_async',body={'agent':'probe','model':{'providerID':pid,'modelID':mid},'parts':[{'type':'text','text':'Reply OK.'}]})
                answer=None
                for _ in range(180):
                    await asyncio.sleep(.5)
                    messages=await rt.call('GET',f'/session/{session["id"]}/message')
                    assistants=[m for m in messages if m['info']['role']=='assistant']
                    error=next((m['info']['error'] for m in assistants if m['info'].get('error')),None)
                    if error:
                        data=error.get('data',{});status=data.get('statusCode');message=data.get('message','模型未返回结果')
                        category='认证失败' if status in {401,403} else '模型调用失败'
                        from .traces import redact
                        raise RuntimeError(pid+'/'+mid+' · '+category+'：'+redact(str(message),auth.values())[:600])
                    if assistants and assistants[-1]['info'].get('time',{}).get('completed'):
                        answer=''.join(p.get('text','') for m in assistants for p in m.get('parts',[]) if p.get('type')=='text')
                        break
                if not answer:raise RuntimeError('模型调用失败：连接测试超时或没有返回文本')
                results.append({'model':pid+'/'+mid,'ok':True,'latency_ms':round((time.monotonic()-started)*1000)})
            return {'models':results,'message':'原生 OpenCode 实际调用成功'}
        finally:
            await self.driver.stop(config);shutil.rmtree(root,ignore_errors=True)

    async def apply_personal(self,u,revision):
        scope=self.models.scope(u)
        async with self.org_locks.setdefault(scope,asyncio.Lock()):
            rows=self.models.snapshot(scope,revision)
            if any(p['enabled'] and any(m['enabled'] for m in p['models']) for p in rows):
                try:await self.probe(rows)
                except Exception as exc:
                    from .traces import redact
                    self.store.execute('UPDATE runtime_instances SET error=? WHERE desired_revision=? AND user_id=?',(redact(str(exc)),revision,u['id']))
                    raise
            self.store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?',(scope,revision))
            self.store.execute('UPDATE runtime_instances SET error=NULL WHERE desired_revision=? AND user_id=?',(revision,u['id']))
            if self.models.latest(scope)['revision']!=revision:return {'superseded':True}
            state=await self.ensure(u,revision)
            if getattr(self,'e2b',None) and self.e2b.enabled and not self.store.one("SELECT 1 FROM workspaces WHERE user_id=? AND backend='local'",(u['id'],)):
                return {'applied':True,'message':'模型配置已通过 E2B 验证，将用于下一次任务。'}
            return {'applied':state['applied_revision']==revision,
                    'message':'模型配置已生效。' if state['applied_revision']==revision else '已保存，将在当前任务结束后生效。'}

    async def start(self):
        self.store.execute("UPDATE operations SET status='failed',result=? WHERE status='running'",(encoded({'message':'服务重启后中断，请重试管理操作'}),))
        users=self.store.all('SELECT * FROM users WHERE active=1 ORDER BY username')
        for u in users:
            try:
                config=self.store.runtime(u['username'])
                self.web_url=config.get('save_url',self.web_url+'/internal/artifacts').removesuffix('/internal/artifacts')
                if await self.driver.health(config):
                    await self.models.import_existing(u,Runtime(config))
                    state=self.instance(u['id'])
                    self.state(u['id'],status='ready',pid=self.driver.pid(config) if hasattr(self.driver,'pid') else None,
                               desired_revision=self.models.latest(self.models.scope(u))['revision'] if self.models.latest(self.models.scope(u)) else 0)
                    # Existing processes are adopted without interrupting them.
                    # Their launch environment is normalized on the next idle apply.
            except (FileNotFoundError,KeyError,RuntimeError,ValueError):pass
        async def maintain():
            while True:
                await asyncio.sleep(8)
                for u in self.store.all('SELECT * FROM users WHERE active=1'):
                    if getattr(self,'e2b',None) and self.e2b.enabled and not self.store.one("SELECT 1 FROM workspaces WHERE user_id=? AND backend='local'",(u['id'],)):continue
                    state=self.instance(u['id'])
                    if not state or state['error']:continue
                    try:
                        # Only apply a candidate already validated by the org operation.
                        candidate=self.models.latest(self.models.scope(u))
                        if state['desired_revision']!=state['applied_revision'] and (not candidate or not candidate['validated']):continue
                        await self.ensure(u,state['desired_revision'])
                    except Exception as exc:self.state(u['id'],status='failed',error=str(exc))
        self.loop_task=asyncio.create_task(maintain())

    async def close(self):
        if self.loop_task:self.loop_task.cancel()
        tasks=list(self.tasks)
        for task in tasks:task.cancel()
        await asyncio.gather(*(tasks+[self.loop_task] if self.loop_task else tasks),return_exceptions=True)
        # User processes survive Web restarts; business prompts are never replayed.
