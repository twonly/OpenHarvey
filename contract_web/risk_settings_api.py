import json
import time
from fastapi import HTTPException, Request
from fastapi.responses import Response
from .settings import admin


def register_risk_settings(app, risks, user):
    settings, store = risks.settings, risks.store

    def scheme(u, iid, revision=None, write=False):
        item = settings.item(u, iid, revision, write)
        if item['kind'] != 'risk':
            raise HTTPException(404, '审查方案不存在')
        return item

    @app.get('/api/risk-schemes')
    async def schemes(request: Request):
        return settings.items(user(request), 'risk')

    @app.get('/api/risk-schemes/options')
    async def options(request: Request):
        u = user(request)
        selected = store.one('SELECT risk_scheme FROM users WHERE id=?', (u['id'],))['risk_scheme']
        default = settings.organization(u)['settings'].get('risk_scheme')
        return {'selected': selected or default, 'default': default, 'inherited': selected is None,
                'schemes': [{k: s[k] for k in ('id', 'revision', 'scope', 'enabled')} | {'label': s['content']['label']} for s in settings.items(u, 'risk')]}

    @app.put('/api/risk-schemes/selection')
    async def select_scheme(request: Request):
        u = user(request); body = await request.json()
        iid = body.get('id')
        risks.choose(u, iid or settings.organization(u)['settings'].get('risk_scheme'))
        store.execute('UPDATE users SET risk_scheme=? WHERE id=?', (iid, u['id']))
        return {'id': iid}

    @app.post('/api/risk-schemes')
    async def create(request: Request):
        return settings.save_item(user(request), 'risk', await request.json())

    @app.get('/api/risk-schemes/{iid}')
    async def detail(iid: str, request: Request, revision: int | None = None):
        return scheme(user(request), iid, revision)

    @app.put('/api/risk-schemes/{iid}')
    async def save(iid: str, request: Request):
        u = user(request); scheme(u, iid, write=True)
        body = await request.json()
        if not body.get('enabled', True) and settings.organization(u)['settings'].get('risk_scheme') == iid:
            raise HTTPException(422, '请先选择另一个默认方案，再停用此方案')
        return settings.save_item(u, 'risk', body, iid)

    @app.delete('/api/risk-schemes/{iid}')
    async def delete(iid: str, request: Request, revision: int):
        u = user(request); scheme(u, iid, write=True)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if iid=='public-risk-examples':raise HTTPException(422,'公开默认示例不能删除')
            # A tombstone keeps saved versions and execution snapshots intact.
            # Advancing the revision also rejects an edit started before deletion.
            if not db.execute('UPDATE config_items SET deleted=1,revision=revision+1,updated=? WHERE id=? AND revision=? AND deleted=0',
                              (time.time(), iid, revision)).rowcount:
                raise HTTPException(409, '审查方案已更新，请重新打开后删除')
            db.execute('UPDATE users SET risk_scheme=NULL WHERE risk_scheme=?', (iid,))
            db.execute('UPDATE threads SET risk_scheme=NULL WHERE risk_scheme=? AND workspace_id IN (SELECT w.id FROM workspaces w JOIN users u ON u.id=w.user_id WHERE u.id=?)', (iid, u['id']))
            db.execute('INSERT INTO audit_log(org_id,actor_id,action,target,created) VALUES(?,?,?,?,?)',
                       (u['org_id'], u['id'], 'risk.delete', iid, time.time()))
        return {'deleted': True}

    @app.post('/api/risk-schemes/{iid}/copy')
    async def copy(iid: str, request: Request):
        u = user(request); original = scheme(u, iid); body = await request.json()
        return settings.save_item(u, 'risk', {'content': {**original['content'], 'label': original['content']['label']+' · 副本'}, 'scope': body.get('scope', 'personal')})

    @app.get('/api/risk-schemes/{iid}/versions')
    async def versions(iid: str, request: Request):
        scheme(user(request), iid)
        return store.all('SELECT revision,hash,created FROM config_versions WHERE item_id=? ORDER BY revision DESC', (iid,))

    @app.post('/api/risk-schemes/{iid}/default')
    async def set_default(iid: str, request: Request):
        u = user(request); admin(u); item = scheme(u, iid)
        if not item['enabled']:raise HTTPException(422,'请先启用此方案')
        store.execute('UPDATE users SET risk_scheme=? WHERE id=?',(iid,u['id']))
        return {'id':iid}

    @app.get('/api/risk-schemes/{iid}/export')
    async def export(iid: str, request: Request):
        item = scheme(user(request), iid)
        value = json.dumps({'schema': 'contract-risk-scheme/v1', 'content': item['content']}, ensure_ascii=False, indent=2)
        return Response(value, media_type='application/json', headers={'Content-Disposition':'attachment; filename="risk-scheme.json"'})
