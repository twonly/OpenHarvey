import asyncio
import json
import sqlite3
import time

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from .settings import admin
from .store import password_hash


def register_admin(app,settings,models,manager,user):
    store=settings.store

    def member(u,uid):
        admin(u)
        row=store.one('SELECT * FROM users WHERE id=? AND org_id=?',(uid,u['org_id']))
        if not row:raise HTTPException(404,'成员不存在')
        return row

    def public_member(row):
        return {k:row[k] for k in ('id','username','active','role')}|{'revision':row['member_revision'],'runtime':manager.instance(row['id'])}

    def model_writer(request):
        u=user(request)
        if u.get('account_kind')=='demo':raise HTTPException(403,'demo 用户无法配置模型，请注册后使用自己的 API Key')
        return u

    @app.get('/api/providers')
    async def providers(request:Request):
        u=user(request);scope=models.scope(u);latest=models.latest(scope)
        return {'providers':models.public(scope),'revision':latest['revision'] if latest else 0,
                'runtime':manager.instance(u['id'])}

    @app.post('/api/providers')
    async def save_provider(request:Request):
        u=model_writer(request);body=await request.json()
        if body.get('id')=='trial':raise HTTPException(403,'平台试用模型为只读配置')
        saved=models.save(u,body)
        return {**saved,**manager.operation(u,'models.apply',str(saved['revision']),lambda:app.state.accounts.operation(u,lambda:manager.apply_personal(u,saved['revision'])))}

    @app.delete('/api/providers/{pid}')
    async def delete_provider(pid:str,revision:int,request:Request):
        u=model_writer(request)
        if pid=='trial':raise HTTPException(403,'平台试用模型为只读配置')
        saved=models.delete(u,pid,revision)
        return {**saved,**manager.operation(u,'models.apply',str(saved['revision']),lambda:app.state.accounts.operation(u,lambda:manager.apply_personal(u,saved['revision'])))}

    @app.post('/api/providers/test')
    async def test_provider(request:Request):
        u=model_writer(request);body=await request.json()
        if body.get('id')=='trial':raise HTTPException(403,'平台试用模型不提供密钥或独立连接测试')
        value=models.validate(body)
        _,key=models.connection(models.scope(u),body)
        rows=[{**value,'enabled':True,'models':[{**m,'enabled':True} for m in value['models']],'secret':models.encrypt(key)}]
        settings.audit(u,'provider.test',value['id'])
        return manager.operation(u,'provider.test',value['id'],lambda:app.state.accounts.operation(u,lambda:manager.probe(rows,body.get('test_model'))))

    @app.post('/api/providers/models')
    async def discover_models(request:Request):
        u=model_writer(request);body=await request.json()
        if body.get('id')=='trial':raise HTTPException(403,'平台试用模型不提供密钥或独立连接测试')
        app.state.accounts.rate('model-discovery:'+u['id'],20,3600)
        result=await models.discover(models.scope(u),body,public_only=u['role']!='admin')
        settings.audit(u,'provider.models',str(body.get('id','')))
        return result

    @app.post('/api/providers/apply')
    async def apply(request:Request):
        u=model_writer(request);version=models.latest(models.scope(u))
        if not version:raise HTTPException(422,'请先保存模型配置')
        return manager.operation(u,'models.apply',str(version['revision']),lambda:app.state.accounts.operation(u,lambda:manager.apply_personal(u,version['revision'])))

    @app.get('/api/operations/{oid}')
    async def operation(oid:str,request:Request):
        u=user(request)
        row=store.one('SELECT * FROM operations WHERE id=? AND actor_id=?',(oid,u['id']))
        if not row:raise HTTPException(404,'操作不存在')
        row['result']=json.loads(row['result'])
        return row
