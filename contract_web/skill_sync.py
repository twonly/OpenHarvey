"""Apply shared Skill files to idle E2B environments, independently of sends."""
import asyncio
import hashlib
import json
import time
import yaml
from .settings import encoded
from .runtime import Runtime, RuntimeError
from .traces import redact

ROOT='/opt/contract-runtime/user-skills'
PATHS=['/opt/contract-runtime/skills',ROOT]

class SkillSync:
    def __init__(self,e2b):
        self.e=e2b;self.store=e2b.store;self.wakeup=asyncio.Event()
        self.store.execute('CREATE TABLE IF NOT EXISTS skill_deployments (workspace_id TEXT PRIMARY KEY, revision TEXT, items TEXT, paths TEXT, error TEXT, updated REAL)')

    def desired(self,u):
        items=[s for s in self.e.settings.items(u,'skill') if s['enabled']]
        files={}
        for item in items:
            if item['scope']=='builtin':continue
            base=ROOT+'/'+item['name']
            c=item['content']
            files[base+'/SKILL.md']='---\n'+yaml.safe_dump({'name':item['name'],'description':c['description']},allow_unicode=True)+'---\n\n'+c['body']+'\n'
            files.update({base+'/'+name:value for name,value in c.get('files',{}).items()})
        builtin_names={s['name'] for s in items if s['scope']=='builtin'}
        for p in self.e.settings.builtin.rglob('*'):
            if p.relative_to(self.e.settings.builtin).parts[0] not in builtin_names:continue
            if p.is_file() and '__pycache__' not in p.parts:
                files['/opt/contract-runtime/skills/'+str(p.relative_to(self.e.settings.builtin))]=p.read_bytes()
        signature=encoded(sorted((p,hashlib.sha256(v.encode() if isinstance(v,str) else v).hexdigest()) for p,v in files.items()))
        revision=hashlib.sha256((signature+encoded([(s['id'],s['revision'],s['hash']) for s in items])).encode()).hexdigest()
        return revision,items,files

    def row(self,wid):return self.store.one('SELECT * FROM skill_deployments WHERE workspace_id=?',(wid,))

    def busy(self,wid,exclude_tid=None):
        for t in self.store.all('SELECT id FROM threads WHERE workspace_id=?',(wid,)):
            if t['id']==exclude_tid:continue
            snap=self.e.history(t['id'])[1]
            if snap.get('status',{}).get('type','idle')!='idle' or snap.get('questions') or snap.get('permissions'):return True
            q=self.store.one("SELECT status,stage FROM queued_messages WHERE thread_id=? AND status IN ('dispatching','submitted')",(t['id'],))
            if q and not (exclude_tid and q['status']=='dispatching' and q['stage']=='checking'):return True
        return False

    async def apply(self,u,w,sbx,exclude_tid=None,force=False):
        # Caller owns the environment lock; background caller also owns mutation gate.
        revision,items,files=self.desired(u);prior=self.row(w['id'])
        if prior and prior['revision']==revision and not prior['error'] and not force:return
        if self.busy(w['id'],exclude_tid):return
        try:
            await sbx.files.write_files([{'path':p,'data':v} for p,v in files.items()])
            for p in json.loads(prior['paths'] or '[]') if prior else []:
                if p not in files:await sbx.files.remove(p)
            # Migrate directory configuration away from per-dialogue version copies.
            for t in self.store.all('SELECT * FROM threads WHERE workspace_id=?',(w['id'],)):
                wd=self.store.user_root(u['id'])/'threads'/t['id'];wd.mkdir(parents=True,exist_ok=True)
                p=wd/'opencode.json';config=json.loads(p.read_text()) if p.exists() else {}
                from .feishu_direct import enabled as direct_enabled
                config['skills']={'paths':PATHS+(['/opt/feishu/skills'] if direct_enabled() else [])};p.write_text(encoded(config))
                remote=self.e.runtime(u,w).directory(t['id'])+'/opencode.json'
                await sbx.files.write(remote,encoded(config))
                if not t['session_id'].startswith('pending_'):
                    await Runtime.call(self.e.runtime(u,w),'POST','/instance/dispose',tid=t['id'])
            self.store.execute('INSERT OR REPLACE INTO skill_deployments VALUES(?,?,?,?,NULL,?)',(w['id'],revision,encoded(items),encoded(list(files)),time.time()))
            self.e.record(w['id'],'skills.applied',{'revision':revision,'skills':[s['name'] for s in items]})
        except Exception as exc:
            error=redact(str(exc),self.e.secrets(u,w['id']))[:800]
            if prior:self.store.execute('UPDATE skill_deployments SET error=? WHERE workspace_id=?',(error,w['id']))
            else:self.store.execute('INSERT INTO skill_deployments VALUES(?,NULL,?,?,?,?)',(w['id'],'[]','[]',error,time.time()))
            self.e.record(w['id'],'skills.failed',{'error':error})
            raise

    def versions(self,u,wid):
        row=self.row(wid)
        items=json.loads(row['items']) if row and row['revision'] else []
        if row and row['error']:raise RuntimeError('Skill 环境更新失败，请在设置页重试')
        return [{k:s[k] for k in ('id','revision','hash','name')} for s in items]

    def status(self,u):
        revision,_,_=self.desired(u);rows=[]
        for w in self.store.all("SELECT * FROM workspaces WHERE user_id=? AND backend='e2b' AND deleted_at IS NULL",(u['id'],)):
            row=self.row(w['id']);b=self.e.binding(w['id']);running=w['id'] in self.e.handles
            state='failed' if row and row['error'] else 'applied' if row and row['revision']==revision and b and b['sandbox_id'] else 'waiting' if running and self.busy(w['id']) else 'syncing' if running else 'on_start'
            rows.append({'workspace_id':w['id'],'title':w['title'],'status':state,'revision':row['revision'] if row else None,'target_revision':revision,'error':row['error'] if row else None})
        return rows

    async def run(self):
        while True:
            self.wakeup.clear()
            for wid in list(self.e.handles):
                try:
                    u=self.e.owner(wid);w=self.store.one('SELECT * FROM workspaces WHERE id=?',(wid,))
                    prior=self.row(wid);revision,_,_=self.desired(u)
                    if prior and (prior['revision']==revision or prior['error']):continue
                    if self.busy(wid):continue
                    async with self.e.manager.lock('queue-'+wid),self.e.manager.lock('e2b-'+wid):
                        sbx=self.e.handles.get(wid)
                        if sbx:await self.apply(u,w,sbx)
                except asyncio.CancelledError:raise
                except Exception:pass # Persisted error is displayed; retry is explicit.
            try:await asyncio.wait_for(self.wakeup.wait(),5)
            except asyncio.TimeoutError:pass

    def retry(self,u):
        self.store.execute('UPDATE skill_deployments SET error=NULL,revision=NULL WHERE workspace_id IN (SELECT id FROM workspaces WHERE user_id=?)',(u['id'],))
        self.wakeup.set()
