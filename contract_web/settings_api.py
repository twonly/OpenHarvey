"""Settings endpoints share the workbench authentication boundary."""
import time

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .settings import admin
from .store import digest, password_hash, password_matches


def register_settings(app, settings, user, runtime):
    store = settings.store

    def skill_item(u, iid, revision=None, write=False):
        item = settings.item(u, iid, revision, write)
        if item['kind'] != 'skill':
            raise HTTPException(404, 'Skill 不存在')
        return item

    @app.get('/api/settings')
    async def get_settings(request: Request):
        return settings.preferences(user(request))

    @app.put('/api/settings')
    async def save_settings(request: Request):
        u, body = user(request), await request.json()
        model = body.get('values', {}).get('model')
        if model and model not in {m['id'] for m in (await runtime(u).models())['models']}:
            raise HTTPException(422, '模型未配置或不可用')
        return settings.save_preferences(u, body)

    @app.put('/api/admin/organization')
    async def save_org(request: Request):
        u = user(request); admin(u)
        return settings.save_organization(u, await request.json())

    @app.put('/api/settings/language')
    async def save_language(request: Request):
        u, body = user(request), await request.json()
        if not isinstance(body, dict) or set(body) != {'ui_language'}:
            raise ValueError('界面语言无效')
        return settings.save_ui_language(u, body['ui_language'])

    @app.put('/api/settings/password')
    async def change_password(request: Request):
        u, body = user(request), await request.json()
        if u.get('account_kind')=='demo' or u.get('auth_subject'):raise HTTPException(403,'此账号使用验证登录，无需设置本地密码')
        row = store.one('SELECT password FROM users WHERE id=?', (u['id'],))
        if not await run_in_threadpool(password_matches, str(body.get('current', '')), row['password']):
            raise HTTPException(422, '当前密码不正确')
        password = body.get('password')
        if not isinstance(password, str) or not 8 <= len(password) <= 200:
            raise ValueError('新密码需要 8–200 个字符')
        hashed = await run_in_threadpool(password_hash, password)
        with store.connect() as db:
            db.execute('UPDATE users SET password=? WHERE id=?', (hashed, u['id']))
            db.execute('DELETE FROM logins WHERE user_id=?', (u['id'],))
        settings.audit(u, 'password.change', u['id'])
        return {'ok': True, 'login_required': True}

    def skill_changed(result):
        sync=app.state.e2b.skill_sync
        sync.wakeup.set()
        return result

    @app.get('/api/skill-environments')
    async def skill_environments(request: Request):
        return app.state.e2b.skill_sync.status(user(request))

    @app.post('/api/skill-environments/retry')
    async def retry_skill_environments(request: Request):
        u=user(request);app.state.e2b.skill_sync.retry(u)
        return app.state.e2b.skill_sync.status(u)

    @app.get('/api/skills')
    async def skills(request: Request):
        return settings.items(user(request), 'skill')

    @app.post('/api/skills')
    async def create_skill(request: Request):
        return skill_changed(settings.save_item(user(request), 'skill', await request.json()))

    @app.get('/api/skills/{iid}')
    async def get_skill(iid: str, request: Request, revision: int | None = None):
        return skill_item(user(request), iid, revision)

    @app.put('/api/skills/{iid}')
    async def save_skill(iid: str, request: Request):
        u = user(request); skill_item(u, iid, write=True)
        return skill_changed(settings.save_item(u, 'skill', await request.json(), iid))

    @app.get('/api/skills/{iid}/versions')
    async def skill_versions(iid: str, request: Request):
        skill_item(user(request), iid)
        return store.all('SELECT revision,hash,created FROM config_versions WHERE item_id=? ORDER BY revision DESC', (iid,))

    @app.post('/api/skills/{iid}/copy')
    async def copy_skill(iid: str, request: Request):
        u = user(request)
        original = skill_item(u, iid)
        body = await request.json()
        content = {**original['content'], 'label': original['content']['label'] + ' · 副本'}
        return skill_changed(settings.save_item(u, 'skill', {'content': content, 'scope': body.get('scope', 'personal'), 'name': body.get('name')}))

    @app.delete('/api/skills/{iid}')
    async def delete_skill(iid: str, request: Request, revision: int):
        u = user(request); skill_item(u, iid, write=True)
        with store.connect() as db:
            if not db.execute('UPDATE config_items SET deleted=1,updated=? WHERE id=? AND revision=? AND deleted=0',
                              (time.time(), iid, revision)).rowcount:
                raise HTTPException(409, 'Skill 已更新，请重新打开后操作')
        settings.audit(u, 'skill.delete', iid)
        return skill_changed({'deleted': True})
