"""Personal identities, public examples and durable trial accounting."""
import asyncio
import hashlib
import json
import secrets
import shutil
import time
from pathlib import Path

from fastapi import HTTPException
from .settings import encoded
from .store import digest

PUBLIC_RISK='public-risk-examples'
LIMITS={'demo_hours':24,'demo_threads':3,'demo_requests':10,'demo_uploads':2,'upload_mb':10,
        'personal_requests':20,'user_concurrency':2,'global_concurrency':2,'global_daily':100,
        'personal_daily':20,'proxy_calls':80}
RULES=[
 {'id':'EX-PAY','name':'付款安排','category':'付款','enabled':True,'baseline':'示例标准：预付款为合同价的20%，里程碑款50%，验收款30%，付款期限为收到合规发票后30日。','definition':'检查付款触发条件是否客观明确，是否附带无法控制的第三方回款条件，尾款比例和期限是否可接受。以上比例为虚构示例，不代表任何公司的真实制度。'},
 {'id':'EX-ACCEPT','name':'验收标准与期限','category':'验收','enabled':True,'baseline':'示例标准：交付后15个工作日内书面验收，异议应具体列明不符合项，并约定整改与复验流程。','definition':'检查标准、验收主体、期限、异议处理与逾期后果是否明确。期限为演示数据。'},
 {'id':'EX-LIABILITY','name':'违约责任','category':'责任','enabled':True,'baseline':'示例标准：迟延违约金每日按迟延部分价款0.03%计算，累计上限为该部分价款5%；责任上限与例外需明确。','definition':'检查责任是否失衡、违约金是否重复累计、责任上限是否缺失。比例仅为虚构演示基线。'},
 {'id':'EX-TERMINATE','name':'解除与结算','category':'解除','enabled':True,'baseline':'示例标准：一般违约先给予15日补救期，解除时按已验收成果和合理已发生成本结算。','definition':'检查单方任意解除、无补救期限、解除后拒绝支付已完成工作或资料交接不清的风险。期限为虚构演示数据。'}]

class Accounts:
    def __init__(self,store,settings):
        self.store,self.settings=store,settings;self.task=None
        with store.connect() as db:
            if 'security_blocked' not in {r[1] for r in db.execute('PRAGMA table_info(workspaces)')}:db.execute('ALTER TABLE workspaces ADD COLUMN security_blocked INTEGER NOT NULL DEFAULT 0')
            cols={r[1] for r in db.execute('PRAGMA table_info(users)')}
            for name,spec in {'account_kind':"TEXT NOT NULL DEFAULT 'personal'",'auth_subject':'TEXT','email':'TEXT','expires_at':'REAL','trial_total':'INTEGER NOT NULL DEFAULT 20','trial_used':'INTEGER NOT NULL DEFAULT 0','threads_created':'INTEGER NOT NULL DEFAULT 0','uploads_created':'INTEGER NOT NULL DEFAULT 0','cleaned_at':'REAL'}.items():
                if name not in cols:db.execute(f'ALTER TABLE users ADD COLUMN {name} {spec}')
            db.executescript('''CREATE UNIQUE INDEX IF NOT EXISTS auth_subject_unique ON users(auth_subject);
              CREATE TABLE IF NOT EXISTS platform_settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS trial_runs(queue_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,platform INTEGER NOT NULL,day TEXT NOT NULL,status TEXT NOT NULL,started REAL,proxy_calls INTEGER NOT NULL DEFAULT 0,proxy_active INTEGER NOT NULL DEFAULT 0,model_accepted INTEGER NOT NULL DEFAULT 0,model_uncertain INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS demo_claims(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS trial_tokens(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS auth_flows(state TEXT PRIMARY KEY,browser TEXT NOT NULL,user_id TEXT,kind TEXT NOT NULL,verifier TEXT NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS auth_rates(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS public_examples(id TEXT PRIMARY KEY,title TEXT NOT NULL,source_user TEXT NOT NULL,workspace_id TEXT NOT NULL,thread_id TEXT NOT NULL,created REAL NOT NULL);
            ''')
            if 'model_uncertain' not in {r[1] for r in db.execute('PRAGMA table_info(trial_runs)')}:db.execute('ALTER TABLE trial_runs ADD COLUMN model_uncertain INTEGER NOT NULL DEFAULT 0')
            if not db.execute("SELECT 1 FROM settings_migrations WHERE name='personal-accounts-v1'").fetchone():
                owner=db.execute("SELECT * FROM users WHERE username='admin'").fetchone()
                db.execute("UPDATE users SET role='member' WHERE username!='admin'")
                if owner:
                    db.execute("UPDATE users SET role='admin' WHERE id=?",(owner['id'],))
                    db.execute("UPDATE config_items SET owner_id=? WHERE owner_id IS NULL",(owner['id'],))
                    for org in db.execute('SELECT settings FROM organizations').fetchall():
                        values=json.loads(org['settings']);prefs=json.loads(owner['preferences'])
                        for k in ('background','guidance'):
                            if values.get(k):prefs.setdefault(k,values[k])
                        db.execute('UPDATE users SET preferences=? WHERE id=?',(encoded(prefs),owner['id']))
                # Existing users keep their selected private library only if they own it.
                for u in db.execute('SELECT * FROM users').fetchall():
                    candidate=u['risk_scheme']
                    if not candidate:
                        org=db.execute('SELECT settings FROM organizations WHERE id=?',(u['org_id'],)).fetchone()
                        candidate=json.loads(org['settings']).get('risk_scheme') if org else None
                    permitted=db.execute('SELECT id FROM config_items WHERE id=? AND owner_id=?',(candidate,u['id'])).fetchone()
                    db.execute('UPDATE users SET risk_scheme=? WHERE id=?',(candidate if permitted else PUBLIC_RISK,u['id']))
                # Old non-admin VMs may contain a formerly shared company library or native cache.
                # Retain their source/history/artifacts, but never resume that execution state.
                if 'backend' in {r[1] for r in db.execute('PRAGMA table_info(workspaces)')}:db.execute("UPDATE workspaces SET security_blocked=1 WHERE backend='e2b' AND user_id IN (SELECT id FROM users WHERE username!='admin')")
                db.execute("INSERT INTO settings_migrations VALUES('personal-accounts-v1')")
            if not db.execute('SELECT 1 FROM config_items WHERE id=?',(PUBLIC_RISK,)).fetchone():
                value=encoded({'label':'公开风险点示例','description':'四个虚构通用基线，供体验审查流程。','rules':RULES})
                db.execute('INSERT INTO config_items VALUES(?,?,?,?,?,?,?,0,?)',(PUBLIC_RISK,'public',None,'risk',PUBLIC_RISK,1,1,time.time()))
                db.execute('INSERT INTO config_versions VALUES(?,?,?,?,?,?)',(PUBLIC_RISK,1,value,digest(value),time.time(),'system'))
        package=Path(__file__).resolve().parents[1]/'runtime/public-examples'
        if (package/'manifest.json').is_file() and not store.one("SELECT 1 FROM settings_migrations WHERE name='public-examples-v1'"):
            for item in json.loads((package/'manifest.json').read_text()):
                src=package/item['id']
                if hashlib.sha256((src/'example.json').read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Public example checksum mismatch')
                shutil.copytree(src,store.root/'public-examples'/item['id'],dirs_exist_ok=True)
                store.execute('INSERT OR IGNORE INTO public_examples VALUES(?,?,?,?,?,?)',(item['id'],item['title'],'public-fixture','public-fixture',item['thread_id'],time.time()))
            store.execute("INSERT INTO settings_migrations VALUES('public-examples-v1')")
        settings.accounts=self

    def limits(self):
        row=self.store.one('SELECT value FROM platform_settings WHERE id=1')
        values=LIMITS| (json.loads(row['value']) if row else {})
        values.pop('run_seconds',None) # Retired: native runs have no application wall-clock deadline.
        return values

    def fresh(self,u):return self.store.one('SELECT * FROM users WHERE id=?',(u['id'],))

    def require_active(self,u):
        row=self.fresh(u)
        if not row or not row['active'] or (row['expires_at'] and row['expires_at']<=time.time()):raise HTTPException(403,'账号已停用或试用已到期，请重新登录')
        return row

    def public(self,u):
        u=self.fresh(u)
        return {k:u[k] for k in ('id','username','role','account_kind','email','expires_at','auth_subject')}|{'trial':self.usage(u)}

    def usage(self,u):
        u=self.fresh(u);l=self.limits()
        return {'remaining':max(0,u['trial_total']-u['trial_used']),'total':u['trial_total'],'used':u['trial_used'],
                'expires_at':u['expires_at'],'threads_remaining':max(0,l['demo_threads']-u['threads_created']) if u['account_kind']=='demo' else None,
                'uploads_remaining':max(0,l['demo_uploads']-u['uploads_created']) if u['account_kind']=='demo' else None,'limits':l}

    def rate(self,bucket,limit,seconds):
        now=time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');db.execute('DELETE FROM auth_rates WHERE expires<?',(now,))
            row=db.execute('SELECT * FROM auth_rates WHERE bucket=?',(bucket,)).fetchone()
            if row and row['count']>=limit:raise HTTPException(429,'请求较频繁，请稍后重试')
            db.execute('INSERT INTO auth_rates VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1',(bucket,now+seconds))

    def create(self,kind='personal'):
        uid=self.store.add_user(('demo-' if kind=='demo' else 'user-')+secrets.token_hex(8),secrets.token_urlsafe(32))
        l=self.limits();expires=time.time()+l['demo_hours']*3600 if kind=='demo' else None
        self.store.execute('UPDATE users SET account_kind=?,expires_at=?,risk_scheme=?,trial_total=? WHERE id=?',(kind,expires,PUBLIC_RISK,l['demo_requests'] if kind=='demo' else l['personal_requests'],uid))
        return self.store.one('SELECT * FROM users WHERE id=?',(uid,))

    def login(self,u,seconds=None):
        from .session_policy import session_seconds
        seconds = session_seconds() if seconds is None else seconds
        if not u['active']:raise HTTPException(403,'账号已停用')
        token=secrets.token_urlsafe(32);expires=min(time.time()+seconds,u['expires_at'] or float('inf'))
        self.store.execute('INSERT INTO logins VALUES(?,?,?)',(digest(token),u['id'],expires));return token

    def bind(self,identity,current=None,link=False):
        subject=identity.get('id');email=identity.get('email')
        if not subject or not email or not identity.get('email_confirmed_at') or identity.get('is_anonymous'):
            raise HTTPException(403,'请先完成邮箱验证')
        current=self.fresh(current) if current else None
        if current and not current['active']:raise HTTPException(403,'账号已停用')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM users WHERE auth_subject=?',(subject,)).fetchone()
            if old:
                if link and (not current or old['id']!=current['id']):raise HTTPException(409,'此登录身份已绑定其他账号')
                if not old['active']:raise HTTPException(403,'账号已停用')
                return dict(old)
            if link:
                if not current or current['role']!='admin' or current['auth_subject']:raise HTTPException(403,'仅已登录且未绑定的管理员可绑定身份')
            elif current and current['account_kind']!='demo':
                current=None
            if current:
                if current['expires_at'] and current['expires_at']<=time.time():raise HTTPException(410,'试用已过期')
                db.execute("UPDATE users SET auth_subject=?,email=?,account_kind='personal',expires_at=NULL,trial_total=MAX(trial_total,?) WHERE id=?",(subject,email,self.limits()['personal_requests'],current['id']))
                db.execute('DELETE FROM logins WHERE user_id=?',(current['id'],))
                db.execute('DELETE FROM demo_claims WHERE user_id=?',(current['id'],))
                return dict(db.execute('SELECT * FROM users WHERE id=?',(current['id'],)).fetchone())
        # Creation is serialized by the async auth endpoint lock; unique subject is an additional guard.
        u=self.create();self.store.execute('UPDATE users SET auth_subject=?,email=? WHERE id=?',(subject,email,u['id']))
        return self.fresh(u)

    def reserve_resource(self,u,kind):
        u=self.fresh(u)
        if u['account_kind']!='demo':return
        col,limit=('threads_created',self.limits()['demo_threads']) if kind=='thread' else ('uploads_created',self.limits()['demo_uploads'])
        with self.store.connect() as db:
            if not db.execute(f'UPDATE users SET {col}={col}+1 WHERE id=? AND {col}<? AND active=1 AND expires_at>?',(u['id'],limit,time.time())).rowcount:
                remaining=self.usage(u)['remaining']
                label='新建对话' if kind=='thread' else '上传文件'
                raise HTTPException(403,f'demo 的{label}名额已用完；仍剩 {remaining} 次模型请求。可继续已有对话、阅读原件，或注册后创建更多内容。')

    def release_resource(self,u,kind):
        col='threads_created' if kind=='thread' else 'uploads_created'
        self.store.execute(f"UPDATE users SET {col}=MAX(0,{col}-1) WHERE id=? AND account_kind='demo'",(u['id'],))

    def platform_model(self,u,body):
        # Explicit user models remain on their existing private provider path.
        selected=body.get('model')
        if selected:return selected.startswith('trial/')
        return not self.store.one('SELECT 1 FROM model_versions WHERE org_id=? AND validated=1',('user:'+u['id'],))

    def reserve(self,db,u,qid,body):
        u=dict(db.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone())
        if u['role']=='admin':return
        if not u['active']:raise HTTPException(403,'账号已停用')
        if u['expires_at'] and u['expires_at']<=time.time():raise HTTPException(403,'试用已到期，请注册后继续使用')
        l=self.limits();platform=self.platform_model(u,body);day=time.strftime('%Y-%m-%d',time.gmtime())
        if platform and u['trial_used']>=u['trial_total']:raise HTTPException(403,'试用额度已用完，请注册或配置自己的模型，也可联系管理员增加额度')
        if db.execute("SELECT COUNT(*) FROM trial_runs WHERE user_id=? AND day=? AND status!='refunded'",(u['id'],day)).fetchone()[0]>=l['personal_daily']:
            raise HTTPException(429,'今日运行额度已用完，请明日再试')
        if platform and db.execute("SELECT COUNT(*) FROM trial_runs WHERE platform=1 AND day=? AND status!='refunded'",(day,)).fetchone()[0]>=l['global_daily']:
            raise HTTPException(429,'今日平台试用已满，请明日再试')
        db.execute('INSERT INTO trial_runs(queue_id,user_id,platform,day,status) VALUES(?,?,?,?,?)',(qid,u['id'],int(platform),day,'reserved'))
        if platform:db.execute('UPDATE users SET trial_used=trial_used+1 WHERE id=?',(u['id'],))

    def claim(self,db,qid):
        row=db.execute('SELECT * FROM trial_runs WHERE queue_id=?',(qid,)).fetchone()
        if not row:return True
        if row['status']!='reserved':return False
        l=self.limits()
        if db.execute("SELECT COUNT(*) FROM trial_runs WHERE status='running'").fetchone()[0]>=l['global_concurrency']:return False
        if db.execute("SELECT COUNT(*) FROM trial_runs WHERE status='running' AND user_id=?",(row['user_id'],)).fetchone()[0]>=l['user_concurrency']:return False
        db.execute("UPDATE trial_runs SET status='running',started=? WHERE queue_id=?",(time.time(),qid));return True

    def finish(self,qid,refund=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM trial_runs WHERE queue_id=?',(qid,)).fetchone()
            if not r or r['status'] in ('done','refunded'):return
            refund=refund and not r['model_accepted'] and not r['model_uncertain']
            if refund and r['platform']:db.execute('UPDATE users SET trial_used=MAX(0,trial_used-1) WHERE id=?',(r['user_id'],))
            db.execute('UPDATE trial_runs SET status=?,proxy_active=0 WHERE queue_id=?',('refunded' if refund else 'done',qid))

    async def operation(self,u,action):
        if u['role']=='admin':return await action()
        qid='operation-'+secrets.token_hex(16)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self.reserve(db,u,qid,{'model':'own/connection-test'})
            if not self.claim(db,qid):raise HTTPException(429,'当前运行已满，请待任务完成后重试模型连接')
        try:
            async with asyncio.timeout(60):return await action()
        finally:self.finish(qid)

    async def maintain(self,app):
        for w in self.store.all("SELECT w.* FROM workspaces w JOIN e2b_bindings b ON b.workspace_id=w.id WHERE w.security_blocked=1 AND b.sandbox_id IS NOT NULL"):
            b=app.state.e2b.binding(w['id'])
            try:await app.state.e2b.sdk.kill(b['sandbox_id'])
            except Exception as exc:
                from e2b.exceptions import SandboxNotFoundException
                if not isinstance(exc,SandboxNotFoundException):raise
            app.state.e2b.handles.pop(w['id'],None);app.state.e2b.state(w['id'],status='killed',sandbox_id=None,credentials=None)
            for t in self.store.all('SELECT id FROM threads WHERE workspace_id=?',(w['id'],)):
                stream=app.state.e2b.streams.pop(t['id'],None)
                if stream:stream.cancel();await asyncio.gather(stream,return_exceptions=True)
        # Connection probes have no outbox entry; release abandoned leases after a crash.
        for row in self.store.all("SELECT queue_id FROM trial_runs WHERE queue_id LIKE 'operation-%' AND status='running' AND started<?",(time.time()-60,)):
            self.finish(row['queue_id'])
        for row in self.store.all("SELECT r.queue_id,q.status,q.stage FROM trial_runs r JOIN queued_messages q ON q.id=r.queue_id WHERE r.status IN ('running','reserved') AND q.status IN ('completed','cancelled','withdrawn','failed')"):
            self.finish(row['queue_id'],row['status']=='withdrawn' or (row['status']=='failed' and row['stage']!='submitting'))
        for r in self.store.all("SELECT r.*,q.thread_id FROM trial_runs r JOIN queued_messages q ON q.id=r.queue_id WHERE r.status='running' AND r.user_id IN (SELECT id FROM users WHERE active=0)"):
            u=self.store.one('SELECT * FROM users WHERE id=?',(r['user_id'],));t=self.store.one('SELECT * FROM threads WHERE id=?',(r['thread_id'],))
            reason='账号已停用，任务已停止'
            app.state.queue.pause(t['id'],reason)
            try:
                async with asyncio.timeout(10):
                    await app.state.queue.runtime(u,t['id']).call('POST',f'/session/{t["session_id"]}/abort',tid=t['id'])
            except Exception:
                b=app.state.e2b.binding(t['workspace_id'])
                if b and b['sandbox_id']:
                    # Retire the VM on the next cleanup pass and prevent its renewal or reuse.
                    self.store.execute('UPDATE workspaces SET security_blocked=1 WHERE id=?',(t['workspace_id'],))
                    app.state.e2b.handles.pop(t['workspace_id'],None)
            finally:
                self.store.execute("UPDATE queued_messages SET status='cancelled',error=? WHERE id=?",(reason,r['queue_id']))
                self.finish(r['queue_id'])
        for u in self.store.all("SELECT * FROM users WHERE account_kind='demo' AND expires_at<? AND cleaned_at IS NULL",(time.time(),)):
            self.store.execute('UPDATE users SET active=0 WHERE id=?',(u['id'],));self.store.execute('DELETE FROM logins WHERE user_id=?',(u['id'],));self.store.execute('DELETE FROM trial_tokens WHERE user_id=?',(u['id'],))
            for w in self.store.all('SELECT * FROM workspaces WHERE user_id=?',(u['id'],)):
                b=app.state.e2b.binding(w['id'])
                if b and b['sandbox_id']:
                    try:await app.state.e2b.sdk.kill(b['sandbox_id'])
                    except Exception as exc:
                        from e2b.exceptions import SandboxNotFoundException
                        if not isinstance(exc,SandboxNotFoundException):raise
                    app.state.e2b.handles.pop(w['id'],None)
                    app.state.e2b.state(w['id'],status='killed',sandbox_id=None)
                for t in self.store.all('SELECT id FROM threads WHERE workspace_id=?',(w['id'],)):
                    stream=app.state.e2b.streams.pop(t['id'],None)
                    if stream:stream.cancel();await asyncio.gather(stream,return_exceptions=True)
                self.store.execute('UPDATE workspaces SET deleted_at=? WHERE id=?',(time.time(),w['id']))
                w['deleted_at']=time.time()
                await app.state.purge_workspace(u,w)
            self.store.execute("UPDATE queued_messages SET status='cancelled',body='{}' WHERE user_id=?",(u['id'],))
            for r in self.store.all("SELECT queue_id FROM trial_runs WHERE user_id=? AND status IN ('running','reserved')",(u['id'],)):self.finish(r['queue_id'],True)
            await asyncio.to_thread(shutil.rmtree,self.store.user_root(u['id']),True)
            with self.store.connect() as db:
                db.execute('DELETE FROM config_versions WHERE item_id IN (SELECT id FROM config_items WHERE owner_id=?)',(u['id'],))
                db.execute('DELETE FROM config_items WHERE owner_id=?',(u['id'],))
                db.execute('DELETE FROM model_versions WHERE org_id=?',('user:'+u['id'],))
                db.execute('DELETE FROM providers WHERE org_id=?',('user:'+u['id'],))
                db.execute("UPDATE users SET preferences='{}' WHERE id=?",(u['id'],))
            self.store.execute('UPDATE users SET cleaned_at=? WHERE id=?',(time.time(),u['id']))
        self.store.execute('DELETE FROM auth_flows WHERE expires<?',(time.time(),))
        self.store.execute('DELETE FROM demo_claims WHERE expires<?',(time.time(),))

    async def start(self,app):
        async def work():
            while True:
                try:await self.maintain(app)
                except asyncio.CancelledError:raise
                except Exception:
                    import logging;logging.getLogger(__name__).exception('Account maintenance failed')
                await asyncio.sleep(10)
        self.task=asyncio.create_task(work())

    async def close(self):
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
