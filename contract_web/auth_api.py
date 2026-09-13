"""Supabase identity exchange and browser-bound PKCE; no client role claims."""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException,Request
from fastapi.responses import JSONResponse,RedirectResponse
from .settings import admin,encoded
from .store import digest

COOKIE='contract_session'
FLOW_COOKIE='workbench_auth_flow'
DEMO_COOKIE='workbench_demo'
ORCA='https://www.orcarouter.ai'
REF='ref_d0785b3ec87207162565'

def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')

def register_auth(app,accounts,models,manager,user):
    store=accounts.store;lock=asyncio.Lock()
    def origin(request):
        default=os.environ.get('CW_PUBLIC_ORIGIN',str(request.base_url)).rstrip('/')
        allowed={default}|{v.strip().rstrip('/') for v in os.environ.get('CW_ADDITIONAL_ORIGINS','').split(',') if v.strip()}
        candidate=request.headers.get('origin',str(request.base_url)).rstrip('/')
        return candidate if candidate in allowed else default
    def config():
        url=os.environ.get('CW_SUPABASE_URL','').rstrip('/');key=os.environ.get('CW_SUPABASE_PUBLISHABLE_KEY','')
        if not url.startswith('https://') or not key:raise HTTPException(503,'注册登录尚未配置，请联系管理员')
        return url,key
    def current(request):return store.authenticate(request.cookies.get(COOKIE,''))
    def cookie(response,name,value,age=86400):
        response.set_cookie(name,value,httponly=True,secure=os.environ.get('CW_SECURE_COOKIE')=='1',samesite='lax' if name==FLOW_COOKIE else 'strict',max_age=age)
        return response
    def issue(u,seconds=86400):return cookie(JSONResponse({'ok':True,'user':accounts.public(u)}),COOKIE,accounts.login(u,seconds),seconds)
    def client_id(request):
        # Railway's edge overwrites X-Real-IP; do not trust arbitrary forwarding chains.
        host=request.headers.get('x-real-ip') if os.environ.get('RAILWAY_ENVIRONMENT_ID') else None
        return digest(host or (request.client.host if request.client else 'unknown'))
    async def supabase(path,body=None,token=None):
        url,key=config();headers={'apikey':key}
        if token:headers['Authorization']='Bearer '+token
        async with httpx.AsyncClient(trust_env=False,timeout=20) as client:
            r=await client.request('POST' if body is not None else 'GET',url+'/auth/v1/'+path,headers=headers,json=body)
        if r.status_code>=400:
            try:code=r.json().get('code','')
            except ValueError:code=''
            message={'invalid_credentials':'邮箱或密码不正确','email_exists':'该邮箱已注册，请使用登录','user_already_exists':'该邮箱已注册，请使用登录','weak_password':'密码未满足安全要求，请使用更长且不常见的密码','over_request_rate_limit':'尝试较频繁，请稍后重试'}.get(code,'认证未完成，请检查登录信息后重试')
            raise HTTPException(400,message)
        return r.json()
    def flow(request,kind,link=False):
        u=current(request)
        if link and (not u or u['role']!='admin'):raise HTTPException(403,'请先登录管理员账号')
        state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
        store.execute('INSERT INTO auth_flows VALUES(?,?,?,?,?,?)',(digest(state),digest(browser),u['id'] if u else None,kind+(':link' if link else ''),verifier,time.time()+600))
        return state,browser,verifier
    def consume(request,state):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM auth_flows WHERE state=? AND browser=? AND expires>?',(digest(state),digest(request.cookies.get(FLOW_COOKIE,'')),time.time())).fetchone()
            if not row:raise HTTPException(400,'登录请求已失效，请重新开始')
            db.execute('DELETE FROM auth_flows WHERE state=?',(row['state'],));return dict(row)
    async def complete(identity,f):
        verified=await supabase('user',token=identity['access_token'])
        u=store.one('SELECT * FROM users WHERE id=?',(f['user_id'],)) if f['user_id'] else None
        async with lock:bound=accounts.bind(verified,u,f['kind'].endswith(':link'))
        ensure_trial(bound)
        response=issue(bound,min(86400,max(60,int(identity.get('expires_in',3600)))));response.delete_cookie(FLOW_COOKIE);return response

    def ensure_trial(u):
        if u['role']=='admin' or not os.environ.get('CW_TRIAL_MODEL_KEY'):return
        old=store.one("SELECT * FROM providers WHERE org_id=? AND id='trial'",(models.scope(u),))
        if old and store.one('SELECT 1 FROM trial_tokens WHERE user_id=? AND expires>?',(u['id'],time.time())):return
        token=secrets.token_urlsafe(40);expiry=time.time()+86400*365
        model=os.environ.get('CW_TRIAL_MODEL','glm-5.3');base=os.environ.get('CW_PUBLIC_ORIGIN','').rstrip('/')
        if not base:raise HTTPException(503,'平台试用地址尚未配置')
        store.execute('INSERT INTO trial_tokens VALUES(?,?,?)',(digest(token),u['id'],expiry))
        result=models.save(u,{'id':'trial','label':'平台试用模型','base_url':base+'/trial-model/v1','key':token,'enabled':True,'models':[{'id':model,'label':'平台试用模型','context':128000,'output':8192,'enabled':True,'native':json.loads(os.environ.get('CW_TRIAL_MODEL_NATIVE','{}'))}],'revision':old['revision'] if old else 0})
        store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?',(models.scope(u),result['revision']))
    app.state.ensure_trial=ensure_trial

    @app.get('/api/auth/config')
    async def auth_config():
        return {'enabled':bool(os.environ.get('CW_SUPABASE_URL') and os.environ.get('CW_SUPABASE_PUBLISHABLE_KEY')),'demo_enabled':bool(os.environ.get('CW_TRIAL_MODEL_KEY')),'captcha_site_key':os.environ.get('CW_TURNSTILE_SITE_KEY'),'providers':['github','google','email']}

    @app.post('/api/auth/start')
    async def start(request:Request):
        body=await request.json();provider=body.get('provider')
        if provider not in {'github','google'}:raise HTTPException(422,'不支持此登录方式')
        accounts.rate('oauth:'+client_id(request),20,3600)
        url,key=config();state,browser,verifier=flow(request,provider,bool(body.get('link')))
        auth=url+'/auth/v1/authorize?'+urlencode({'provider':provider,'redirect_to':origin(request)+'/auth/callback?flow='+state,'code_challenge':b64(hashlib.sha256(verifier.encode()).digest()),'code_challenge_method':'s256'})
        return cookie(JSONResponse({'auth_url':auth}),FLOW_COOKIE,browser,600)

    @app.post('/api/auth/exchange')
    async def exchange(request:Request):
        body=await request.json();f=consume(request,str(body.get('flow','')))
        if f['kind'].split(':')[0] not in {'github','google'}:raise HTTPException(400,'登录方式不匹配')
        result=await supabase('token?grant_type=pkce',{'auth_code':str(body.get('code','')),'code_verifier':f['verifier']})
        return await complete(result,f)

    @app.post('/api/auth/email')
    async def email(request:Request):
        body=await request.json();email=str(body.get('email','')).strip();password=body.get('password');action=body.get('action','login')
        if '@' not in email or len(email)>254:raise HTTPException(422,'请输入有效邮箱')
        if action not in {'login','signup'}:raise HTTPException(422,'登录方式无效')
        if not isinstance(password,str) or not (8 if action=='signup' else 1)<=len(password)<=1024:raise HTTPException(422,'注册密码至少8位，最长1024位')
        accounts.rate('password:'+client_id(request),20,3600);accounts.rate('password-address:'+digest(email.lower()),10,3600)
        u=current(request);link=bool(body.get('link'))
        if link and (not u or u['role']!='admin'):raise HTTPException(403,'请先登录管理员账号')
        result=await supabase('signup' if action=='signup' else 'token?grant_type=password',{'email':email,'password':password})
        if not result.get('access_token'):raise HTTPException(409,'邮箱确认仍然启用，请联系管理员关闭后再登录')
        return await complete(result,{'user_id':u['id'] if u else None,'kind':'password:link' if link else 'password'})

    @app.post('/api/demo/start')
    async def demo(request:Request):
        existing=current(request)
        if existing:return JSONResponse({'ok':True,'user':accounts.public(accounts.fresh(existing))})
        claimed=store.one("SELECT u.* FROM demo_claims d JOIN users u ON u.id=d.user_id WHERE d.token=? AND d.expires>? AND u.active=1 AND u.account_kind='demo' AND u.expires_at>?",(digest(request.cookies.get(DEMO_COOKIE,'')),time.time(),time.time()))
        if claimed:return issue(claimed)
        if not os.environ.get('CW_TRIAL_MODEL_KEY'):raise HTTPException(503,'免登录试用尚未开放，请登录后使用')
        key='demo:'+client_id(request);row=store.one('SELECT count,expires FROM auth_rates WHERE bucket=?',(key,))
        if row and row['expires']>time.time() and row['count']>=3:
            body=await request.json();secret=os.environ.get('CW_TURNSTILE_SECRET_KEY')
            if not secret:raise HTTPException(429,'领取较频繁，请注册后使用')
            async with httpx.AsyncClient(trust_env=False,timeout=15) as client:
                r=await client.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',data={'secret':secret,'response':str(body.get('captcha_token',''))})
            if not r.json().get('success'):raise HTTPException(403,'请完成人机验证后重试')
        accounts.rate(key,10,86400)
        u=accounts.create('demo');ensure_trial(u)
        claim=secrets.token_urlsafe(32);store.execute('INSERT INTO demo_claims VALUES(?,?,?)',(digest(claim),u['id'],u['expires_at']))
        return cookie(issue(u),DEMO_COOKIE,claim,max(1,int(u['expires_at']-time.time())))

    @app.get('/api/usage')
    async def usage(request:Request):return accounts.usage(user(request))

    @app.get('/api/admin/users')
    async def users(request:Request):
        admin(user(request));return [accounts.public(u)|{'active':bool(u['active'])} for u in store.all('SELECT * FROM users ORDER BY rowid DESC')]

    @app.patch('/api/admin/users/{uid}')
    async def manage(uid:str,request:Request):
        actor=user(request);admin(actor);body=await request.json();target=store.one('SELECT * FROM users WHERE id=?',(uid,))
        if not target:raise HTTPException(404,'用户不存在')
        if 'active' in body and not isinstance(body['active'],bool):raise HTTPException(422,'启用状态无效')
        if set(body)-{'active','add_requests'}:raise HTTPException(422,'管理字段无效')
        if uid==actor['id'] and body.get('active') is False:raise HTTPException(422,'不能停用自己')
        amount=body.get('add_requests',0)
        if isinstance(amount,bool) or not isinstance(amount,int) or not 0<=amount<=10000:raise HTTPException(422,'增加额度须为0–10000的整数')
        with store.connect() as db:
            db.execute('UPDATE users SET active=?,trial_total=trial_total+? WHERE id=?',(int(bool(body.get('active',target['active']))),amount,uid))
            if body.get('active') is False:
                db.execute('DELETE FROM logins WHERE user_id=?',(uid,));db.execute('DELETE FROM trial_tokens WHERE user_id=?',(uid,))
        accounts.settings.audit(actor,'user.update',uid);return accounts.public(target)

    @app.get('/api/admin/trial-limits')
    async def limits(request:Request):admin(user(request));return accounts.limits()

    @app.put('/api/admin/trial-limits')
    async def save_limits(request:Request):
        admin(user(request));body=await request.json();values=accounts.limits()
        if set(body)-set(values) or any(isinstance(v,bool) or not isinstance(v,int) or not 1<=v<=10000 for v in body.values()):raise HTTPException(422,'额度设置无效')
        store.execute('INSERT OR REPLACE INTO platform_settings VALUES(1,?)',(encoded(values|body),));return accounts.limits()

    @app.get('/orca/connect-url')
    async def orca_start(request:Request):
        u=user(request)
        if u['account_kind']=='demo':raise HTTPException(403,'demo 无法配置模型，请注册后连接自己的 OrcaRouter')
        # GET widget endpoint has an explicit same-origin check, too.
        if request.headers.get('sec-fetch-site') not in (None,'same-origin','none'):raise HTTPException(403,'请求来源不匹配')
        accounts.rate('orca:'+u['id'],20,3600)
        state,browser,verifier=flow(request,'orca')
        auth=ORCA+'/auth?'+urlencode({'callback_url':origin(request)+'/orca/callback','code_challenge':b64(hashlib.sha256(verifier.encode()).digest()),'code_challenge_method':'S256','state':state,'app_name':'合同助手','scope':'api','ref':REF})
        return cookie(JSONResponse({'auth_url':auth}),FLOW_COOKIE,browser,600)

    @app.get('/orca/callback')
    async def orca_callback(request:Request,state:str='',code:str=''):
        f=consume(request,state)
        if f['kind']!='orca' or not f['user_id']:raise HTTPException(400,'连接请求无效')
        # Browser cookie need not cross the OAuth redirect, but the flow is bound to its authenticated initiator.
        u=store.one('SELECT * FROM users WHERE id=? AND active=1',(f['user_id'],))
        if not u or u['account_kind']=='demo':raise HTTPException(403,'请注册并登录后连接')
        async with httpx.AsyncClient(trust_env=False,timeout=30) as client:
            r=await client.post(ORCA+'/api/v1/auth/keys',json={'code':code,'code_verifier':f['verifier'],'code_challenge_method':'S256'})
        if r.status_code>=400:raise HTTPException(400,'OrcaRouter 授权失败，请重试')
        data=r.json();key=data.get('key')
        if not isinstance(key,str) or not key:raise HTTPException(502,'OrcaRouter 未返回有效密钥')
        old=store.one('SELECT revision FROM providers WHERE org_id=? AND id=?',(models.scope(u),'orcarouter'))
        result=models.save(u,{'id':'orcarouter','label':'OrcaRouter','base_url':'https://api.orcarouter.ai/v1','key':key,'enabled':True,'revision':old['revision'] if old else 0,'models':[{'id':'orcarouter/auto','label':'OrcaRouter Auto','context':128000,'output':8192,'enabled':True}]})
        manager.operation(u,'models.apply',str(result['revision']),lambda:accounts.operation(u,lambda:manager.apply_personal(u,result['revision'])))
        response=RedirectResponse('/model?connected=orcarouter',303);response.delete_cookie(FLOW_COOKIE);return response
