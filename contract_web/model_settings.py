"""Small provider registry. Secrets are encrypted outside every Agent directory."""
import asyncio
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from .settings import encoded


class Models:
    def __init__(self, settings):
        self.settings,self.store=settings,settings.store
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS providers (
              org_id TEXT NOT NULL,id TEXT NOT NULL,label TEXT NOT NULL,base_url TEXT NOT NULL,
              models TEXT NOT NULL,secret TEXT,enabled INTEGER NOT NULL,revision INTEGER NOT NULL,
              PRIMARY KEY(org_id,id));
            CREATE TABLE IF NOT EXISTS model_versions (
              org_id TEXT NOT NULL,revision INTEGER NOT NULL,content TEXT NOT NULL,created REAL NOT NULL,
              PRIMARY KEY(org_id,revision));
            CREATE TABLE IF NOT EXISTS runtime_instances (
              user_id TEXT PRIMARY KEY,backend TEXT NOT NULL DEFAULT 'local',pid INTEGER,
              status TEXT NOT NULL DEFAULT 'provisioning',desired_revision INTEGER NOT NULL DEFAULT 0,
              applied_revision INTEGER NOT NULL DEFAULT 0,error TEXT,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
              id TEXT PRIMARY KEY,org_id TEXT NOT NULL,actor_id TEXT NOT NULL,kind TEXT NOT NULL,target TEXT NOT NULL,
              status TEXT NOT NULL,result TEXT NOT NULL DEFAULT '{}',created REAL NOT NULL,updated REAL NOT NULL);
            ''')
        with self.store.connect() as db:
            if 'member_revision' not in {r[1] for r in db.execute('PRAGMA table_info(users)')}:
                db.execute('ALTER TABLE users ADD COLUMN member_revision INTEGER NOT NULL DEFAULT 1')
            if 'validated' not in {r[1] for r in db.execute('PRAGMA table_info(model_versions)')}:
                db.execute('ALTER TABLE model_versions ADD COLUMN validated INTEGER NOT NULL DEFAULT 0')
        keypath=Path(os.environ.get('CW_SECRET_KEY_FILE',self.store.root/'secrets'/'master.key')).resolve()
        if keypath.is_relative_to(self.store.root/'users'):
            raise ValueError('密钥加密主密钥必须位于 Agent 目录之外')
        keypath.parent.mkdir(parents=True,exist_ok=True)
        try:
            fd=os.open(keypath,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
        self.cipher=Fernet(keypath.read_bytes())
        self.migrate_personal()
        with self.store.connect() as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(providers)')}
            if 'protocol' not in columns:db.execute("ALTER TABLE providers ADD COLUMN protocol TEXT NOT NULL DEFAULT 'openai'")
            if 'extra_body' not in columns:db.execute("ALTER TABLE providers ADD COLUMN extra_body TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def scope(u):
        # Existing SQL column is retained for backwards-compatible migrations;
        # new registries are always keyed by the authenticated account.
        return 'user:' + u['id']

    def migrate_personal(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM settings_migrations WHERE name='personal-models'").fetchone():
                return
            for u in db.execute("SELECT id,org_id FROM users WHERE username='admin'").fetchall():
                scope = self.scope(u)
                db.execute('INSERT OR IGNORE INTO providers(org_id,id,label,base_url,models,secret,enabled,revision) SELECT ?,id,label,base_url,models,secret,enabled,revision FROM providers WHERE org_id=?', (scope,u['org_id']))
                for v in db.execute('SELECT * FROM model_versions WHERE org_id=?',(u['org_id'],)).fetchall():
                    rows=json.loads(v['content'])
                    for row in rows:row['org_id']=scope
                    db.execute('INSERT OR IGNORE INTO model_versions(org_id,revision,content,created,validated) VALUES(?,?,?,?,?)',(scope,v['revision'],encoded(rows),v['created'],v['validated']))
            db.execute("INSERT INTO settings_migrations VALUES('personal-models')")

    def encrypt(self,key):return self.cipher.encrypt(key.encode()).decode() if key else None
    def decrypt(self,key):return self.cipher.decrypt(key.encode()).decode() if key else None

    def rows(self,org):
        return [{**r,'models':json.loads(r['models']),'extra_body':json.loads(r['extra_body'])} for r in self.store.all('SELECT * FROM providers WHERE org_id=? ORDER BY id',(org,))]

    def public(self,org):
        return [{k:v for k,v in r.items() if k!='secret'}|{'key_configured':bool(r['secret'])} for r in self.rows(org)]

    def latest(self,org):
        return self.store.one('SELECT * FROM model_versions WHERE org_id=? ORDER BY revision DESC LIMIT 1',(org,))

    def snapshot(self,org,revision=None):
        row=self.store.one('SELECT * FROM model_versions WHERE org_id=? AND revision=?',(org,revision)) if revision else self.latest(org)
        return json.loads(row['content']) if row else []

    def connection(self, org, body):
        """Resolve a draft connection without requiring a model or saving it."""
        pid=str(body.get('id','')).strip()
        base=str(body.get('base_url','')).strip().rstrip('/')
        url=urlsplit(base)
        if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('请填写完整服务地址，地址不能包含凭据、查询参数或片段')
        key=body.get('key')
        if key is not None and (not isinstance(key,str) or len(key)>10000):raise ValueError('密钥格式无效')
        existing=self.store.one('SELECT secret FROM providers WHERE org_id=? AND id=?',(org,pid))
        key=key.strip() if key and key.strip() else None if body.get('clear_key') else self.decrypt(existing['secret']) if existing else None
        return base,key

    @staticmethod
    def protocol(body):
        value=body.get('protocol','openai')
        if not isinstance(value,str) or value not in {'openai','anthropic'}:raise ValueError('接口协议无效')
        return value

    @staticmethod
    def extra_body(body):
        value=body.get('extra_body',{})
        if not isinstance(value,dict):raise ValueError('额外请求参数必须是 JSON 对象')
        try:text=json.dumps(value,allow_nan=False)
        except (ValueError,TypeError):raise ValueError('额外请求参数必须是合法 JSON 对象') from None
        if len(text)>32000:raise ValueError('额外请求参数最多 32000 字符')
        if set(value)&{'model','messages','stream','tools','tool_choice','system'}:
            raise ValueError('额外请求参数不能覆盖 model、messages、stream、tools、tool_choice 或 system')
        return value

    @staticmethod
    def native_base(base,protocol):
        # Anthropic's SDK appends /messages; official host needs the /v1 prefix.
        return base+'/v1' if protocol=='anthropic' and urlsplit(base).path in {'','/'} else base

    async def discover(self, org, body, public_only=False):
        base,key=self.connection(org,body)
        protocol=self.protocol(body);base=self.native_base(base,protocol)
        from .traces import redact
        try:
            async with asyncio.timeout(15), httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
                target=httpx.URL(base+'/models');headers=({'x-api-key':key or '', 'anthropic-version':'2023-06-01'} if protocol=='anthropic' else {'Authorization':'Bearer '+key} if key else {});extensions={}
                if public_only:
                    addresses=await asyncio.get_running_loop().getaddrinfo(target.host,target.port or (443 if target.scheme=='https' else 80),type=socket.SOCK_STREAM)
                    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                        raise HTTPException(422,'云端模型服务必须使用公开网络地址')
                    # Pin the checked IP, retaining HTTP Host and TLS certificate validation.
                    # A provider-controlled DNS change cannot redirect this request into Railway.
                    headers['Host']=target.netloc.decode();extensions['sni_hostname']=target.host
                    target=target.copy_with(host=addresses[0][4][0])
                async with client.stream('GET',target,headers=headers,extensions=extensions) as response:
                    content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>2_000_000:raise HTTPException(502,'模型列表过大，请手动填写模型 ID')
            if response.status_code in {401,403}:raise HTTPException(422,'认证失败，请检查 API 密钥及模型列表访问权限')
            if response.status_code in {404,405}:raise HTTPException(422,'此服务未提供模型列表接口，请手动填写模型 ID；仍可测试连接')
            if response.status_code!=200:
                raise HTTPException(502,f'获取模型列表失败（HTTP {response.status_code}），请检查服务地址或稍后重试')
            try:data=json.loads(content)
            except (ValueError,UnicodeDecodeError):raise HTTPException(502,'此地址未返回有效模型列表，请检查服务地址或手动填写模型 ID') from None
            values=data if isinstance(data,list) else data.get('data',data.get('models',[])) if isinstance(data,dict) else []
            if not isinstance(values,list):values=[]
            ids=[v if isinstance(v,str) else v.get('id',v.get('model','')) if isinstance(v,dict) else '' for v in values]
            ids=sorted({v.strip() for v in ids if isinstance(v,str) and v.strip() and len(v)<=180 and not any(c.isspace() for c in v) and redact(v,[key])==v})
            if not ids:raise HTTPException(422,'此服务未返回可用模型列表，请手动填写模型 ID；仍可测试连接')
            return {'models':ids}
        except (TimeoutError,httpx.TimeoutException):raise HTTPException(504,'获取模型列表超时（15 秒），请检查服务地址与网络后重试') from None
        except httpx.HTTPError:raise HTTPException(502,'无法连接模型列表接口，请检查服务地址与网络') from None
        except socket.gaierror:raise HTTPException(422,'无法解析模型服务地址，请检查后重试') from None

    def validate(self,body):
        pid=str(body.get('id','')).strip()
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',pid) or len(pid)>48:raise ValueError('供应商标识须为小写字母、数字和短横线，最多 48 位')
        label=str(body.get('label','')).strip();base=str(body.get('base_url','')).strip().rstrip('/')
        url=urlsplit(base)
        if not label or len(label)>100 or url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('请填写供应商名称和完整服务地址，地址不能包含凭据、查询参数或片段')
        models=body.get('models')
        if not isinstance(models,list) or not 1<=len(models)<=40:raise ValueError('每个供应商需要 1–40 个模型')
        cleaned=[];seen=set()
        for m in models:
            if not isinstance(m,dict) or not isinstance(m.get('native',{}),dict):raise ValueError('模型配置格式无效')
            mid=str(m.get('id','')).strip();name=str(m.get('label','')).strip()
            if not mid or len(mid)>180 or any(c.isspace() for c in mid) or mid in seen or not name or len(name)>100:raise ValueError('模型 ID、名称无效或重复')
            seen.add(mid)
            context,output=m.get('context',128000),m.get('output',8192)
            if not isinstance(context,int) or not isinstance(output,int) or not 1<=output<=context<=10000000:raise ValueError('模型上限需要满足 1 ≤ 输出上限 ≤ 上下文上限 ≤ 10000000')
            native={k:v for k,v in m.get('native',{}).items() if k in {'reasoning','tool_call','interleaved'}}
            if mid.startswith('glm-'):
                native={'reasoning':True,'tool_call':True,'interleaved':{'field':'reasoning_content'},**native}
            cleaned.append({'id':mid,'label':name,'context':context,'output':output,'enabled':bool(m.get('enabled',True)),'native':native})
        key=body.get('key')
        if key is not None and (not isinstance(key,str) or len(key)>10000):raise ValueError('密钥格式无效')
        return {'id':pid,'label':label,'base_url':base,'models':cleaned,'protocol':self.protocol(body),'extra_body':self.extra_body(body),'enabled':bool(body.get('enabled',True))}

    def save(self,u,body):
        value=self.validate(body);
        if body.get('clear_key'):value['enabled']=False
        org=self.scope(u);pid=value['id']
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM providers WHERE org_id=? AND id=?',(org,pid)).fetchone()
            if (old['revision'] if old else 0)!=body.get('revision',0):raise HTTPException(409,'供应商配置已更新，请重新打开后保存')
            key=self.encrypt(body['key'].strip()) if body.get('key') else (None if body.get('clear_key') else old['secret'] if old else None)
            revision=(old['revision'] if old else 0)+1
            db.execute('INSERT INTO providers(org_id,id,label,base_url,models,secret,enabled,revision,protocol,extra_body) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(org_id,id) DO UPDATE SET label=excluded.label,base_url=excluded.base_url,models=excluded.models,secret=excluded.secret,enabled=excluded.enabled,revision=excluded.revision,protocol=excluded.protocol,extra_body=excluded.extra_body',
                       (org,pid,value['label'],value['base_url'],encoded(value['models']),key,int(value['enabled']),revision,value['protocol'],encoded(value['extra_body'])))
            rows=[dict(r) for r in db.execute('SELECT * FROM providers WHERE org_id=? ORDER BY id',(org,))]
            for r in rows:
                r['models']=json.loads(r['models']);r['extra_body']=json.loads(r['extra_body'])
            version=(db.execute('SELECT MAX(revision) FROM model_versions WHERE org_id=?',(org,)).fetchone()[0] or 0)+1
            db.execute('INSERT INTO model_versions(org_id,revision,content,created) VALUES(?,?,?,?)',(org,version,encoded(rows),time.time()))
            db.execute('UPDATE runtime_instances SET desired_revision=?,error=NULL WHERE user_id=?',(version,u['id']))
        self.settings.audit(u,'provider.save',pid)
        return {'provider':next(p for p in self.public(org) if p['id']==pid),'revision':version}

    def delete(self,u,pid,revision):
        org=self.scope(u)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT revision FROM providers WHERE org_id=? AND id=?',(org,pid)).fetchone()
            if not old:raise HTTPException(404,'供应商不存在')
            if old['revision']!=revision:raise HTTPException(409,'供应商配置已更新，请重新打开后删除')
            db.execute('DELETE FROM providers WHERE org_id=? AND id=?',(org,pid))
            rows=[dict(r) for r in db.execute('SELECT * FROM providers WHERE org_id=? ORDER BY id',(org,))]
            for r in rows:
                r['models']=json.loads(r['models']);r['extra_body']=json.loads(r['extra_body'])
            version=(db.execute('SELECT MAX(revision) FROM model_versions WHERE org_id=?',(org,)).fetchone()[0] or 0)+1
            db.execute('INSERT INTO model_versions(org_id,revision,content,created) VALUES(?,?,?,?)',(org,version,encoded(rows),time.time()))
            db.execute('UPDATE runtime_instances SET desired_revision=?,error=NULL WHERE user_id=?',(version,u['id']))
        self.settings.audit(u,'provider.delete',pid)
        return {'revision':version}

    def native(self,rows):
        providers={};auth={}
        for row in rows:
            if not row['enabled']:continue
            models={m['id']:{**m.get('native',{}),'name':m['label'],'limit':{'context':m['context'],'output':m['output']}} for m in row['models'] if m['enabled']}
            if not models:continue
            protocol=row.get('protocol','openai')
            providers[row['id']]={'name':row['label'],'npm':'@ai-sdk/anthropic' if protocol=='anthropic' else '@ai-sdk/openai-compatible',
                'options':{'baseURL':self.native_base(row['base_url'],protocol)},'models':models}
            # Preserve the existing DeepSeek adapter for saved DeepSeek IDs.
            if row['id']=='deepseek' and protocol=='openai':providers[row['id']].pop('npm')
            if row.get('extra_body'):providers[row['id']]['options']['workbenchExtraBody']=row['extra_body']
            auth[row['id']]=self.decrypt(row.get('secret'))
        first=next((pid+'/'+mid for pid,p in providers.items() for mid in p['models']),None)
        config={'provider':providers,'enabled_providers':list(providers)}
        if first:config.update(model=first,small_model=first)
        return config,auth

    def allowed(self,org):
        if not self.latest(org):return None
        return {p['id']+'/'+m['id'] for p in self.rows(org) if p['enabled'] for m in p['models'] if m['enabled']}

    async def import_existing(self,u,rt):
        if self.latest(self.scope(u)):return
        native=await rt.call('GET','/config')
        # Migration keeps connected provider IDs and model selections, while
        # replacing duplicated environment configuration on the next idle apply.
        for pid,p in native.get('provider',{}).items():
            if not p.get('models'):continue
            body={'id':pid,'label':p.get('name') or pid,'base_url':p.get('options',{}).get('baseURL',''),'models':[
                {'id':mid,'label':m.get('name') or mid,'native':{k:v for k,v in m.items() if k in {'reasoning','tool_call','interleaved'}},'context':m.get('limit',{}).get('context',128000),'output':m.get('limit',{}).get('output',8192)} for mid,m in p['models'].items()],
                'protocol':'anthropic' if p.get('npm')=='@ai-sdk/anthropic' else 'openai','extra_body':p.get('options',{}).get('workbenchExtraBody',{}),'key':p.get('options',{}).get('apiKey'),'revision':0}
            if body['base_url']:
                self.save({**u,'role':'admin'},body)
        self.store.execute('UPDATE model_versions SET validated=1 WHERE org_id=?',(self.scope(u),))
