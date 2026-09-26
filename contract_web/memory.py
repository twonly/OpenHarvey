"""Account-owned short memories. OpenCode owns reasoning; this service owns commits."""
import json
import os
import re
import secrets
import time

from fastapi import HTTPException, Request
from .settings import encoded
from .store import digest

MARKER = re.compile(r'\[\[memory:([a-f0-9]{24}):(\d+)\]\]')


class Memory:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS personal_memories (
                  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), content TEXT NOT NULL,
                  revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                  source TEXT NOT NULL, source_thread_id TEXT, source_message_id TEXT);
                CREATE INDEX IF NOT EXISTS memories_owner ON personal_memories(user_id,updated DESC);
                CREATE TABLE IF NOT EXISTS memory_capabilities (
                  execution_id TEXT PRIMARY KEY REFERENCES execution_configs(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS memory_receipts (
                  request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                  execution_id TEXT NOT NULL, message_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
                  receipt TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS memory_receipts_thread ON memory_receipts(thread_id,message_id);
            ''')

    def status(self, u, db=None):
        row = (dict(db.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone()) if db
               else self.store.one('SELECT * FROM users WHERE id=?', (u['id'],)))
        available = bool(row['active'] and (not row.get('expires_at') or row['expires_at'] > time.time())
                         and row['account_kind'] != 'demo' and os.environ.get('CW_MEMORY_ENABLED', '1') == '1')
        enabled = json.loads(row['preferences']).get('memory_enabled') is True
        return {'available': available, 'memory_enabled': enabled, 'effective': available and enabled,
                'requires_login': row['account_kind'] == 'demo',
                'revision': row['settings_revision'], 'limit': 12000, 'item_limit': 500}

    def set_enabled(self, u, body):
        if not isinstance(body, dict) or set(body) != {'memory_enabled', 'revision'} or type(body['memory_enabled']) is not bool:
            raise HTTPException(422, '记忆设置无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if body['memory_enabled'] and not self.status(u, db)['available']:
                raise HTTPException(403, '当前账号暂不可开启个人记忆')
            n = db.execute("UPDATE users SET preferences=json_set(preferences,'$.memory_enabled',json(?)),settings_revision=settings_revision+1 WHERE id=? AND settings_revision=?",
                           (encoded(body['memory_enabled']), u['id'], body['revision'])).rowcount
            if not n: raise HTTPException(409, '设置已更新，请重新载入后保存')
        return self.status(u)

    @staticmethod
    def public(row):
        return {**{k: row[k] for k in ('id', 'content', 'revision', 'created', 'updated', 'source', 'source_thread_id', 'source_message_id')},
                'citation': f"[[memory:{row['id']}:{row['revision']}]]"}

    def items(self, u, db=None):
        sql = 'SELECT * FROM personal_memories WHERE user_id=? ORDER BY updated DESC,id'
        rows = db.execute(sql, (u['id'],)).fetchall() if db else self.store.all(sql, (u['id'],))
        return [self.public(r) for r in rows]

    def snapshot(self, u):
        with self.store.connect() as db:
            db.execute('BEGIN')
            status = self.status(u, db)
            return {'enabled': status['effective'], 'items': self.items(u, db) if status['effective'] else []}

    def mutate(self, db, u, action, body, source='manual', tid=None, mid=None):
        if u.get('account_kind') == 'demo': raise HTTPException(403, '请登录正式账号后管理记忆')
        if action not in {'create', 'update', 'delete'}: raise HTTPException(422, '记忆操作无效')
        prior = None
        if action != 'create':
            prior = db.execute('SELECT * FROM personal_memories WHERE id=? AND user_id=?', (body.get('id'), u['id'])).fetchone()
            if not prior: raise HTTPException(404, '记忆已删除或不存在')
            if type(body.get('revision')) is not int or body['revision'] != prior['revision']:
                raise HTTPException(409, '记忆已更新，请重新载入后保存')
        if action == 'delete':
            db.execute('DELETE FROM personal_memories WHERE id=? AND user_id=?', (prior['id'], u['id']))
            return {'saved': True, 'action': action, 'item': self.public(prior)}
        content = body.get('content')
        if not isinstance(content, str) or not content.strip() or len(content.strip()) > 500 or any(ord(c) < 32 and c not in '\n\t' for c in content):
            raise HTTPException(422, '每条记忆需要 1–500 字符')
        content = content.strip()
        used = db.execute('SELECT COALESCE(SUM(length(content)),0) FROM personal_memories WHERE user_id=?', (u['id'],)).fetchone()[0]
        if used - (len(prior['content']) if prior else 0) + len(content) > 12000:
            raise HTTPException(422, '记忆总量已达上限，请先整理已有记忆')
        now = time.time()
        if prior:
            iid = prior['id']
            db.execute('UPDATE personal_memories SET content=?,revision=revision+1,updated=?,source=?,source_thread_id=?,source_message_id=? WHERE id=?',
                       (content, now, source, tid, mid, iid))
        else:
            iid = secrets.token_hex(12)
            db.execute('INSERT INTO personal_memories VALUES(?,?,?,?,?,?,?,?,?)', (iid, u['id'], content, 1, now, now, source, tid, mid))
        return {'saved': True, 'action': action, 'item': self.public(db.execute('SELECT * FROM personal_memories WHERE id=?', (iid,)).fetchone())}

    def manual(self, u, action, body):
        if not isinstance(body, dict) or set(body) - {'content', 'id', 'revision'}:
            raise HTTPException(422, '记忆请求无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self.mutate(db, u, action, body)

    def prepare(self, u, t, rt, execution, message_id):
        snap = self.snapshot(u)
        execution['memory'] = snap
        config = {k: v for k, v in execution.items() if k != 'id'}
        self.store.execute('UPDATE execution_configs SET config=?,message_id=? WHERE id=?', (encoded(config), message_id, execution['id']))
        if not snap['enabled']:
            return '\n个人 Memory 已关闭或不可用。不得调用 memory 工具，不得应用历史中的个人记忆。当前用户指令、明确配置和合同材料仍有效。'
        token = secrets.token_urlsafe(32)
        self.store.execute('INSERT INTO memory_capabilities VALUES(?,?)', (execution['id'], digest(token)))
        cap = {'execution_id': execution['id'], 'thread_id': t['id'], 'session_id': t['session_id'],
               'token': token, 'transport': 'exchange' if rt.config.get('e2b') else 'http',
               'url': rt.config.get('save_url', 'http://127.0.0.1:8830/internal/artifacts').rsplit('/internal/', 1)[0] + '/internal/memory'}
        wd = self.store.user_root(u['id']) / 'threads' / t['id']
        path = wd / '.memory-capability'
        tmp = path.with_suffix('.tmp'); tmp.write_text(encoded(cap)); tmp.chmod(0o600); tmp.replace(path)
        return ('\n个人 Memory 已开启。下列列表是本轮唯一有效的长期记忆快照，替代历史记忆；它是偏好数据，不改变权限、事实或证据要求。'
                '当前用户要求优先，明确配置优先于冲突记忆。凡回答的标题、格式、措辞或判断方式遵循了某条记忆，必须在回答末尾原样复制该项 citation 字段。'
                '这是界面展示参考记忆的唯一依据，不要只口头说遵循了偏好。输出前核对实际使用的条目；未使用的条目不要引用。'
                '可用 memory 原生工具保存、更新、删除；仅后端 saved=true 才能声明保存。\n' + encoded(snap))

    def execute(self, u, req, *, token=None, workspace_id=None):
        if not isinstance(req, dict) or set(req) - {'request_id', 'execution_id', 'thread_id', 'session_id', 'message_id', 'action', 'id', 'revision', 'content'}:
            raise HTTPException(422, '记忆请求无效')
        rid = req.get('request_id')
        if not isinstance(rid, str) or not re.fullmatch('[a-f0-9]{64}', rid): raise HTTPException(422, '记忆请求标识无效')
        h = digest(encoded(req))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            e = db.execute('''SELECT e.*,t.session_id,t.workspace_id,t.deleted_at,t.archived_at,w.deleted_at AS workspace_deleted
                FROM execution_configs e JOIN threads t ON t.id=e.thread_id JOIN workspaces w ON w.id=t.workspace_id
                WHERE e.id=? AND e.thread_id=? AND e.user_id=? AND w.user_id=?''',
                           (req.get('execution_id'), req.get('thread_id'), u['id'], u['id'])).fetchone()
            if not e or e['session_id'] != req.get('session_id') or (workspace_id is not None and e['workspace_id'] != workspace_id):
                raise HTTPException(403, '记忆请求不属于当前执行')
            if token is not None:
                c = db.execute('SELECT token_hash FROM memory_capabilities WHERE execution_id=?', (e['id'],)).fetchone()
                if not c or not secrets.compare_digest(c['token_hash'], digest(token)): raise HTTPException(403, '记忆执行凭证无效')
            elif workspace_id is None: raise HTTPException(403, '缺少记忆执行身份')
            # The kill switch and user setting are checked inside the commit transaction.
            if not self.status(u, db)['effective']: raise HTTPException(403, '个人记忆已暂停')
            old = db.execute('SELECT * FROM memory_receipts WHERE request_id=?', (rid,)).fetchone()
            if old:
                if old['payload_hash'] != h or old['user_id'] != u['id']: raise HTTPException(409, '记忆请求标识冲突')
                return json.loads(old['receipt'])
            latest = db.execute('SELECT id FROM execution_configs WHERE thread_id=? ORDER BY created DESC,id DESC LIMIT 1', (e['thread_id'],)).fetchone()
            if (e['deleted_at'] or e['archived_at'] or e['workspace_deleted'] or latest['id'] != e['id']
                    or e['status'] not in {'starting', 'running'} or time.time() - e['created'] > 86400):
                raise HTTPException(409, '记忆执行已结束或过期')
            if not isinstance(req.get('message_id'), str) or not re.fullmatch(r'msg_[a-zA-Z0-9]+', req['message_id']):
                raise HTTPException(422, '记忆消息标识无效')
            try:
                if req.get('action') == 'list': result = {'saved': False, 'action': 'list', 'items': self.items(u, db)}
                else: result = self.mutate(db, u, req.get('action'), req, 'conversation', e['thread_id'], req['message_id'])
            except HTTPException as exc:
                result = {'saved': False, 'action': req.get('action'), 'error': exc.detail, 'status': exc.status_code}
            result['request_id'] = rid
            db.execute('INSERT INTO memory_receipts VALUES(?,?,?,?,?,?,?,?)',
                       (rid, u['id'], e['thread_id'], e['id'], req['message_id'], h, encoded(result), time.time()))
            return result

    async def collect(self, u, w, sbx):
        folder = '/workspace/exchange/memory'
        try: entries = await sbx.files.list(folder, depth=1)
        except Exception as exc:
            if isinstance(exc, FileNotFoundError) or any(s in str(exc).lower() for s in ('not found', 'does not exist', 'no such file')): return
            raise
        for entry in entries:
            if not re.fullmatch('[a-f0-9]{64}\\.request.json', entry.name): continue
            rid = entry.name.split('.')[0]
            try:
                if getattr(entry, 'size', 0) > 10000: raise HTTPException(422, '记忆请求过大')
                raw = await sbx.files.read(entry.path, format='bytes')
                if len(raw) > 10000: raise HTTPException(422, '记忆请求过大')
                req = json.loads(raw)
                if not isinstance(req, dict) or req.get('request_id') != rid: raise HTTPException(422, '记忆请求标识无效')
                result = self.execute(u, req, workspace_id=w['id'])
            except (HTTPException, ValueError, TypeError) as exc:
                result = {'saved': False, 'request_id': rid, 'error': getattr(exc, 'detail', '记忆请求无效')}
            await sbx.files.write(folder + '/' + rid + '.receipt.json', encoded(result))
            await sbx.files.remove(entry.path)

    def projector(self, u, t):
        return MemoryProjection(self, u, t)


class MemoryProjection:
    """Validate native memory tool receipts and citations before exposing UI cards."""
    def __init__(self, memory, user, thread):
        self.memory, self.user, self.thread = memory, user, thread
        self.parents = {}

    def info(self, info):
        if info.get('role') == 'assistant' and info.get('parentID'):
            self.parents[info['id']] = info['parentID']

    def current(self, item):
        row = self.memory.store.one('SELECT revision FROM personal_memories WHERE id=? AND user_id=?', (item['id'], self.user['id']))
        return {**item, 'current_revision': row['revision'] if row else None}

    def part(self, part):
        store = self.memory.store
        mid = part.get('messageID')
        if part.get('type') == 'tool' and part.get('tool') == 'memory':
            if part.get('state', {}).get('input', {}).get('action') == 'list': return {'memory_action': 'list'}
            try: result = json.loads(part.get('state', {}).get('output', '{}'))
            except (ValueError, TypeError): return {}
            if not isinstance(result, dict): return {}
            row = store.one('SELECT receipt FROM memory_receipts WHERE request_id=? AND user_id=? AND thread_id=? AND message_id=?',
                            (result.get('request_id'), self.user['id'], self.thread['id'], mid))
            if not row: return {'memory_failed': True} if result.get('saved') is False and not result.get('pending') else {}
            receipt = json.loads(row['receipt'])
            if receipt.get('item'): receipt['item'] = self.current(receipt['item'])
            # list results are context, not a "saved" card.
            return {'memory_receipt': receipt} if receipt.get('action') != 'list' else {'memory_action': 'list'}
        if part.get('type') != 'text' or not MARKER.search(part.get('text', '')): return {}
        parent = self.parents.get(mid)
        if not parent: return {}
        e = store.one('SELECT id,config FROM execution_configs WHERE thread_id=? AND user_id=? AND message_id=?', (self.thread['id'], self.user['id'], parent))
        if not e: return {}
        items = json.loads(e['config']).get('memory', {}).get('items', [])
        for row in store.all('SELECT receipt FROM memory_receipts WHERE execution_id=? AND user_id=?', (e['id'], self.user['id'])):
            r = json.loads(row['receipt'])
            if r.get('saved') and r.get('action') != 'delete': items.append(r['item'])
            if r.get('action') == 'list': items.extend(r.get('items', []))
        available = {(i['id'], i['revision']): i for i in items}
        refs = []
        for iid, revision in dict.fromkeys(MARKER.findall(part['text'])):
            item = available.get((iid, int(revision)))
            if item: refs.append(self.current(item))
        return {'memory_references': refs} if refs else {}


def register_memory(app, memory, user):
    @app.get('/api/memories')
    async def items(request: Request):
        rows = memory.items(user(request))
        return {'items': rows, 'used': sum(len(r['content']) for r in rows), 'limit': 12000}

    @app.post('/api/memories')
    async def create(request: Request): return memory.manual(user(request), 'create', await request.json())

    @app.patch('/api/memories/{iid}')
    async def update(iid: str, request: Request):
        u, body = user(request), await request.json()
        if not isinstance(body, dict): raise HTTPException(422, '记忆请求无效')
        return memory.manual(u, 'update', {**body, 'id': iid})

    @app.delete('/api/memories/{iid}')
    async def delete(iid: str, request: Request, revision: int): return memory.manual(user(request), 'delete', {'id': iid, 'revision': revision})

    @app.post('/internal/memory')
    async def internal(request: Request):
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        row = memory.store.one('SELECT u.* FROM memory_capabilities c JOIN execution_configs e ON e.id=c.execution_id JOIN users u ON u.id=e.user_id WHERE c.token_hash=? AND u.active=1', (digest(token),))
        if not row: raise HTTPException(403, '记忆执行凭证无效')
        if len(await request.body()) > 10000: raise HTTPException(413, '记忆请求过大')
        return memory.execute(row, await request.json(), token=token)
