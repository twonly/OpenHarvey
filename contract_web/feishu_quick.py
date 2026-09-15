"""Official CLI browser setup. Only progress and verification URLs reach the UI."""
import asyncio
import json
import os
import signal
import time
from urllib.parse import urlsplit

from fastapi import HTTPException


def cli_environment(store, uid):
    root = store.root / 'connectors' / uid
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    row = store.one('SELECT brand FROM feishu_connections WHERE user_id=?', (uid,)) if hasattr(store, 'one') else None
    brand = row['brand'] if row else 'feishu'
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'TMPDIR', 'SSL_CERT_FILE', 'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY') if k in os.environ}
    env.update(LARKSUITE_CLI_CONFIG_DIR=str(root), LARKSUITE_CLI_DATA_DIR=str(root), LARKSUITE_CLI_LOG_DIR=str(root/'logs'),
               LARKSUITE_CLI_BRAND=brand, LARKSUITE_CLI_DEFAULT_AS='user', LARKSUITE_CLI_STRICT_MODE='user',
               LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    return root, env


def verification_url(line):
    try:
        obj = json.loads(line)
        value = obj.get('verification_uri_complete') or obj.get('verification_url') or '' if isinstance(obj, dict) else ''
    except ValueError:
        value = line.strip()
    p = urlsplit(value)
    return value if p.scheme == 'https' and p.hostname and any(p.hostname == domain or p.hostname.endswith('.'+domain) for domain in ('feishu.cn','larksuite.com')) and not p.username and not p.password else None


class QuickSetup:
    def __init__(self, connector):
        self.connector = connector
        self.jobs = {}

    def public(self, uid):
        j = self.jobs.get(uid, {})
        return {k: j[k] for k in ('step', 'url', 'qr', 'message') if k in j}

    def active(self, uid):
        j = self.jobs.get(uid)
        return bool(j and j.get('task') and not j['task'].done())

    async def stop(self, uid):
        j = self.jobs.get(uid)
        if self.active(uid):
            j['task'].cancel()
            await asyncio.gather(j['task'], return_exceptions=True)
        self.jobs.pop(uid, None)

    async def close(self):
        for uid in list(self.jobs):
            await self.stop(uid)

    async def command(self, uid, args, *, progress=False, timeout=50):
        from .feishu import cli_path
        binary = cli_path()
        if not binary:
            raise HTTPException(503, '本地未安装飞书 CLI')
        root, env = cli_environment(self.connector.store, uid)
        proc = await asyncio.create_subprocess_exec(binary, *args, cwd=root, env=env, stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def consume(stream):
            chunks = []
            async for raw in stream:
                line = raw.decode('utf-8', 'replace')
                chunks.append(line)
                url = verification_url(line) if progress else None
                if url:
                    j = self.jobs[uid]
                    j.update(url=url, qr=False)
                    # Official QR encoder; the URL is forwarded verbatim.
                    await self.command(uid, ['auth', 'qrcode', url, '--output', 'verification.png'])
                    j['qr'] = True
            return ''.join(chunks)
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await asyncio.gather(consume(proc.stdout), consume(proc.stderr))
                await proc.wait()
            if proc.returncode:
                raise HTTPException(502, '飞书流程未完成：可能已取消、已超时，或企业需要管理员批准。请重试；已有企业应用可使用高级设置。')
            try:
                return json.loads(stdout)
            except ValueError:
                return {}  # Login emits multiple progress events; verify separately.
        finally:
            # npm's CLI launcher has a child binary; terminate the whole job so
            # a cancelled browser flow cannot leave a device poller running.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if proc.returncode is None:
                await proc.wait()

    async def verify(self, uid):
        f = self.connector
        r = f.row(uid)
        if not r or r['mode'] != 'cli':
            raise HTTPException(409, '当前连接不是 CLI 配置')
        result = await self.command(uid, ['auth', 'status', '--json', '--verify'])
        person = result.get('identities', {}).get('user', {})
        if result.get('appId') != r['app_id'] or result.get('identity') != 'user' or result.get('verified') is not True or not person.get('openId'):
            raise HTTPException(401, '飞书用户授权尚未生效，请重新连接')
        identity = {'name': person.get('userName', '飞书用户'), 'open_id': person['openId']}
        scope = person.get('scope', '')
        if isinstance(scope, list):
            scope = ' '.join(scope)
        with f.store.connect() as db:
            changed = db.execute("UPDATE feishu_connections SET status='connected',identity=?,tokens=?,tested_at=?,updated=? WHERE user_id=? AND revision=? AND mode='cli'",
                (json.dumps(identity, ensure_ascii=False), f.models.encrypt(json.dumps({'managed_by': 'cli', 'scope': scope})), time.time(), time.time(), uid, r['revision'])).rowcount
        if not changed:
            raise HTTPException(409, '连接已变化，请重试')
        return {**f.public(uid), 'verified': True}

    def start(self, uid, brand=None):
        row = self.connector.row(uid)
        brand = brand or (row['brand'] if row else 'feishu')
        if brand not in {'feishu', 'lark'}: raise HTTPException(422, '请选择飞书或 Lark')
        if row and row['brand'] != brand: raise HTTPException(409, '已有连接须继续使用原来的飞书或 Lark 平台')
        if self.active(uid):
            return self.public(uid)
        if not row:
            self.connector.store.execute("INSERT INTO feishu_connections(user_id,app_id,secret,mode,brand,updated) VALUES(?,'','','cli',?,?)", (uid,brand,time.time()))
        j = {'step': 'starting', 'message': '正在准备飞书官方配置页面…'}
        self.jobs[uid] = j
        j['task'] = asyncio.create_task(self.run(uid))
        return self.public(uid)

    async def run(self, uid):
        from .feishu import requested_scopes
        f, j = self.connector, self.jobs[uid]
        try:
            root, _ = cli_environment(f.store, uid)
            if not (root/'config.json').is_file():
                j.update(step='application', message='打开飞书官方页面完成应用创建，完成后会自动进入账号授权。')
                await self.command(uid, ['config', 'init', '--new', '--brand', f.row(uid)['brand']], progress=True, timeout=900)
            result = await self.command(uid, ['config', 'show'])
            app_id = result.get('appId', '')
            if not app_id.startswith('cli_'):
                raise HTTPException(502, 'CLI 尚未保存有效的应用配置')
            async with f.lock(uid):
                f.store.execute("INSERT INTO feishu_connections(user_id,app_id,secret,mode,updated) VALUES(?,?,'','cli',?) ON CONFLICT(user_id) DO UPDATE SET app_id=excluded.app_id,secret='',mode='cli',tokens=NULL,identity=NULL,status='configured',tested_at=NULL,revision=revision+1,updated=excluded.updated", (uid, app_id, time.time()))
                f.store.execute('DELETE FROM feishu_oauth WHERE user_id=?', (uid,))
            j.update(step='authorization', url='', qr=False, message='应用已配置。请打开新的飞书授权页面，查看并同意工作台申请的权限。')
            await self.command(uid, ['auth', 'login', '--scope', ' '.join(requested_scopes()), '--json'], progress=True, timeout=900)
            await self.verify(uid)
            j.update(step='done', url='', qr=False, message='飞书连接成功，凭证已由官方 CLI 保存。可以试读文档。')
        except asyncio.CancelledError:
            raise
        except (HTTPException, TimeoutError, OSError, ValueError) as exc:
            j.update(step='failed', url='', qr=False, message=exc.detail if isinstance(exc, HTTPException) else '配置流程超时或本地 CLI 不可用，请重试。')
