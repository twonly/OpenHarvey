#!/usr/bin/env python3
"""Submit to the local collector through E2B files; no inbound callback required."""
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path


def submit(filename, timeout=120):
    root=Path.cwd().resolve();source=(root/filename).resolve()
    if not source.is_relative_to(root):raise ValueError('报告必须位于当前对话目录')
    body=json.loads(source.read_bytes())
    if not isinstance(body,dict):raise ValueError('报告必须是 JSON 对象')
    if body.get('content_file'):
        p=(root/body.pop('content_file')).resolve()
        if not p.is_relative_to(root):raise ValueError('正文必须位于当前对话目录')
        body['content']=p.read_text()
    if body.get('kind')=='redline' and body.get('action','inspect') in {'inspect','find','diff'}:
        body['read_id']=uuid.uuid4().hex  # Reads must never replay a cached E2B snapshot.
    context=json.loads((root/'context.json').read_text())
    payload=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if len(payload.encode())>4_000_000:raise ValueError('报告超过 4 MB')
    if not context.get('execution_id'):raise ValueError('缺少当前执行记录')
    rid=hashlib.sha256((context['thread_id']+':'+context['execution_id']+':'+payload).encode()).hexdigest()
    exchange=Path(os.environ.get('CW_EXCHANGE_DIR','/workspace/exchange'));exchange.mkdir(parents=True,exist_ok=True)
    req={'request_id':rid,'thread_id':context['thread_id'],'execution_id':context['execution_id'],'report':body}
    temp=exchange/(rid+'.tmp');temp.write_text(json.dumps(req,ensure_ascii=False));temp.replace(exchange/(rid+'.request.json'))
    deadline=time.monotonic()+timeout;receipt=exchange/(rid+'.receipt.json')
    while time.monotonic()<deadline:
        if receipt.exists():
            try:return json.loads(receipt.read_text())
            except json.JSONDecodeError:pass # Reader can observe a file API write in progress.
        time.sleep(.5)
    return {'saved':False,'pending':True,'request_id':rid,'error':'保存尚未确认；本地服务恢复后将继续收集，请勿声明已保存'}


if __name__=='__main__':
    try:
        if len(sys.argv)!=2:raise ValueError('用法：python3 submit.py 报告.json')
        result=submit(sys.argv[1]);print(json.dumps(result,ensure_ascii=False));sys.exit(0 if (result.get('saved') or result.get('ok')) else 1)
    except Exception as exc:
        print(json.dumps({'saved':False,'error':str(exc)},ensure_ascii=False));sys.exit(1)
