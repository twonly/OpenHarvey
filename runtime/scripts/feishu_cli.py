#!/usr/bin/env python3
"""Credential-only launcher: business commands run in the official CLI."""
import json
import os
from pathlib import Path
import sys
import subprocess
import uuid
import time

CREDENTIAL = Path('/run/workbench-feishu/credential.json')
BINARY = '/opt/feishu/bin/lark-cli'

def environment(payload, base=None, now=None):
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or payload.get('expires_at', 0) <= now+10 or not payload.get('access_token') or not payload.get('app_id'):
        raise ValueError('飞书授权未就绪或已过期，请回到连接器设置重新连接。')
    if payload.get('brand','feishu') not in {'feishu','lark'}: raise ValueError('无效的飞书 / Lark 平台')
    env = {k:v for k,v in (os.environ if base is None else base).items() if not k.startswith('LARKSUITE_') and k not in {'OPENCLAW_HOME','HERMES_HOME'}}
    env.update(LARKSUITE_CLI_APP_ID=payload['app_id'],LARKSUITE_CLI_USER_ACCESS_TOKEN=payload['access_token'],
               LARKSUITE_CLI_BRAND=payload.get('brand','feishu'),LARKSUITE_CLI_DEFAULT_AS='user',LARKSUITE_CLI_STRICT_MODE='user',
               LARKSUITE_CLI_CONFIG_DIR='/run/workbench-feishu/config',LARKSUITE_CLI_DATA_DIR='/run/workbench-feishu/data',
               LARKSUITE_CLI_LOG_DIR='/run/workbench-feishu/logs',
               LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1',LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    return env

def make_receipt(args,data,code,duration,payload):
    # Metadata only: no user arguments, document bodies, auth payloads or raw errors.
    words=[]
    for arg in args[1:]:
        if arg.startswith('-'):break
        words.extend(arg.lstrip('+').split('-'))
    kind='write' if any(v in {'create','update','upsert','append','insert','write','patch','import','delete','copy','move'} for v in words) else 'read'
    ok=code==0 and isinstance(data,dict) and data.get('ok',True) is not False and data.get('code',0)==0 and not data.get('error')
    ids={}
    def visit(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='record_id_list' and isinstance(v,list):
                    ids.setdefault('record_id',[])
                    ids['record_id']=list(dict.fromkeys(ids['record_id']+[x for x in v if isinstance(x,str) and len(x)<200]))[:20]
                if k=='base_token':k='app_token'
                if k in {'document_id','app_token','table_id','record_id'} and isinstance(v,str) and len(v)<200:
                    ids.setdefault(k,[])
                    if v not in ids[k] and len(ids[k])<20:ids[k].append(v)
                elif isinstance(v,(dict,list)):visit(v)
        elif isinstance(value,list):
            for v in value[:100]:visit(v)
    visit(data)
    return {'id':uuid.uuid4().hex,'kind':kind,'outcome':'success' if ok else 'failed_or_uncertain',
            'duration_ms':duration,'created':time.time(),'ids':ids,'revision':payload['revision'],
            'sandbox_id':payload['sandbox_id'],'generation':payload['generation'],
            'exit_code':code,'code':data.get('code') if isinstance(data,dict) else None}

def main():
    # Help and embedded Skills remain available before the account is connected.
    args=sys.argv[1:]
    informational=not args or args[0] in {'skills','schema','help'} or '--help' in args or '--version' in args or '--dry-run' in args
    try:
        payload=json.loads(CREDENTIAL.read_text())
        env=environment(payload)
    except (OSError, ValueError, TypeError):
        if not informational:
            print(json.dumps({'ok':False,'error':{'type':'authentication','message':'飞书授权未就绪或已过期，请在工作台连接器设置中恢复授权。'}},ensure_ascii=False))
            return 1
        env={k:v for k,v in os.environ.items() if not k.startswith('LARKSUITE_')}
    if args[:2]==['auth','status']:
        print(json.dumps({'ok':True,'identity':'user','data':{'mode':'external_access_token','open_id':payload.get('open_id'),'expires_at':payload.get('expires_at'),'scope':payload.get('scope'),'verified':False},'message':'用户访问令牌已由工作台注入。本命令只显示注入状态；请直接执行业务命令验证实际访问权，无需登录。'},ensure_ascii=False))
        return 0
    if args and args[0] in {'auth','config'}:

        print(json.dumps({'ok':False,'error':{'type':'authentication','message':'请在工作台管理授权。'}},ensure_ascii=False))
        return 1
    started=time.monotonic()
    result=subprocess.run([BINARY,*args],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    # Never mirror the injected token into a tool response, including CLI failures.
    secret=env.get('LARKSUITE_CLI_USER_ACCESS_TOKEN','').encode()
    out=result.stdout.replace(secret,b'[REDACTED]') if secret else result.stdout
    err=result.stderr.replace(secret,b'[REDACTED]') if secret else result.stderr
    sys.stdout.buffer.write(out);sys.stderr.buffer.write(err)
    if not informational and args and args[0] in {'docs','drive','wiki','base','bitable'}:
        try:
            data=json.loads(out)
        except ValueError:data={}
        receipt=make_receipt(args,data,result.returncode,round((time.monotonic()-started)*1000),payload)
        folder=Path('/workspace/exchange/feishu')
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/(receipt['id']+'.json')
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt,ensure_ascii=False));temporary.replace(target)
    return result.returncode

if __name__ == '__main__':sys.exit(main())
