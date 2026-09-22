"""Scoped product configuration. Execution stays in native OpenCode."""
import hashlib
import json
import re
import secrets
import time
from pathlib import Path, PurePosixPath

import yaml
from fastapi import HTTPException

DEFAULTS = {"model": None, "perspective": "乙方", "permission_mode": "auto", "verbosity": "normal", "assistant_name":"合同助手", "user_nickname":"", "onboarding_completed":False, "background":"", "guidance":""}
DEFAULTS['ui_language'] = 'zh-CN'
DEFAULTS['memory_enabled'] = False
DEFAULTS['trial_notice_dismissed'] = False


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def migrate(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS organizations (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 1);
        INSERT OR IGNORE INTO organizations(id,name) VALUES('default','我的组织');
        CREATE TABLE IF NOT EXISTS config_items (
          id TEXT PRIMARY KEY, org_id TEXT NOT NULL, owner_id TEXT, kind TEXT NOT NULL,
          name TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
          deleted INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS config_versions (
          item_id TEXT NOT NULL, revision INTEGER NOT NULL, content TEXT NOT NULL, hash TEXT NOT NULL,
          created REAL NOT NULL, author_id TEXT NOT NULL, PRIMARY KEY(item_id,revision));
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, actor_id TEXT NOT NULL,
          action TEXT NOT NULL, target TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS execution_configs (
          id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, user_id TEXT NOT NULL, created REAL NOT NULL,
          config TEXT NOT NULL, message_id TEXT, status TEXT NOT NULL DEFAULT 'starting');
    """)
    db.execute("CREATE TABLE IF NOT EXISTS settings_migrations (name TEXT PRIMARY KEY)")
    columns = {r[1] for r in db.execute('PRAGMA table_info(users)')}
    for name, spec in {"org_id": "TEXT NOT NULL DEFAULT 'default'", "role": "TEXT NOT NULL DEFAULT 'member'",
                       "preferences": "TEXT NOT NULL DEFAULT '{}'", "settings_revision": "INTEGER NOT NULL DEFAULT 1", "account_kind":"TEXT NOT NULL DEFAULT 'personal'", "auth_subject":"TEXT", "expires_at":"REAL"}.items():
        if name not in columns:
            db.execute(f'ALTER TABLE users ADD COLUMN {name} {spec}')
    if not db.execute("SELECT 1 FROM settings_migrations WHERE name='legacy-model-default'").fetchone():
        for row in db.execute("SELECT id,model,preferences FROM users WHERE model IS NOT NULL"):
            values=json.loads(row['preferences'])
            values.setdefault('model',row['model'])
            db.execute('UPDATE users SET preferences=? WHERE id=?',(encoded(values),row['id']))
        db.execute("INSERT INTO settings_migrations VALUES('legacy-model-default')")
    if 'permission_override' not in {r[1] for r in db.execute('PRAGMA table_info(threads)')}:
        db.execute('ALTER TABLE threads ADD COLUMN permission_override INTEGER NOT NULL DEFAULT 0')
        # Existing conversations keep their prior explicit permission policy.
        db.execute('UPDATE threads SET permission_override=1')


def admin(u):
    if u.get('role') != 'admin':
        raise HTTPException(403, '此操作需要管理员身份')


class Settings:
    def __init__(self, store, builtin):
        self.store, self.builtin = store, Path(builtin)

    def audit(self, u, action, target):
        self.store.execute('INSERT INTO audit_log(org_id,actor_id,action,target,created) VALUES(?,?,?,?,?)',
                           (u['org_id'], u['id'], action, target, time.time()))

    def organization(self, u):
        row=self.store.one('SELECT preferences,risk_scheme FROM users WHERE id=?',(u['id'],))
        own=json.loads(row['preferences'])
        return {'id':'personal','name':'我的设置','revision':1,'settings':{**own,'risk_scheme':row['risk_scheme'] or 'public-risk-examples'}}

    def preferences(self, u):
        row = self.store.one('SELECT preferences,settings_revision,model FROM users WHERE id=?', (u['id'],))
        own = json.loads(row['preferences'])
        org = self.organization(u)
        effective, sources = {}, {}
        for key, fallback in DEFAULTS.items():
            effective[key] = own.get(key, fallback)
            sources[key] = '我的设置' if key in own else '系统默认'
        return {'values': own, 'effective': effective, 'sources': sources, 'revision': row['settings_revision'], 'organization': org}

    def validate_preferences(self, values):
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError('设置字段无效')
        for key, value in values.items():
            if key == 'ui_language' and (not isinstance(value, str) or value not in {'zh-CN', 'en'}):
                raise ValueError('界面语言无效')
            if key in {'assistant_name','user_nickname'} and (not isinstance(value,str) or len(value)>32 or any(ord(c)<32 for c in value)):
                raise ValueError('称呼最多32字，不能包含换行或控制字符')
            if key=='assistant_name' and not value.strip():raise ValueError('请填写助手名称')
            if key in {'onboarding_completed','memory_enabled','trial_notice_dismissed'} and not isinstance(value,bool):raise ValueError('引导状态无效')
            if key in {'background','guidance'} and (not isinstance(value,str) or len(value)>12000):raise ValueError('补充信息最多12000字')
            if key == 'perspective' and (not isinstance(value, str) or not value.strip() or len(value) > 120):
                raise ValueError('请填写 1–120 字的我方立场')
            if key == 'permission_mode' and value not in {'auto', 'cautious', 'full'}:
                raise ValueError('执行方式无效')
            if key == 'verbosity' and value not in {'concise', 'normal', 'detailed'}:
                raise ValueError('回答详略无效')
            if key == 'model' and value is not None and (not isinstance(value, str) or len(value) > 200 or '/' not in value):
                raise ValueError('模型选择无效')
        return values

    def save_preferences(self, u, body):
        values = self.validate_preferences(body.get('values'))
        with self.store.connect() as db:
            prior = json.loads(db.execute('SELECT preferences FROM users WHERE id=?', (u['id'],)).fetchone()['preferences'])
            # Labs uses its own field-only endpoint; general reset never changes it.
            values = {**values, 'memory_enabled': prior.get('memory_enabled', False)}
            values['trial_notice_dismissed'] = prior.get('trial_notice_dismissed', False)
            if 'ui_language' not in values and 'ui_language' in prior:
                values = {**values, 'ui_language': prior['ui_language']}
            changed = db.execute('UPDATE users SET preferences=?,model=?,settings_revision=settings_revision+1 WHERE id=? AND settings_revision=?',
                                 (encoded(values), values.get('model'), u['id'], body.get('revision'))).rowcount
            if not changed:
                raise HTTPException(409, '设置已在其他页面更新，请重新打开后保存')
        return self.preferences(u)

    def save_organization(self, u, body):
        raise HTTPException(410,'组织设置已取消，请使用个人设置')

    def save_ui_language(self, u, value):
        self.validate_preferences({'ui_language': value})
        # A field-only update cannot overwrite concurrent model/name changes.
        self.store.execute("UPDATE users SET preferences=json_set(preferences,'$.ui_language',?),settings_revision=settings_revision+1 WHERE id=?",
                           (value, u['id']))
        return {'ui_language': value}

    def builtins(self, u=None):
        result = []
        for path in sorted(self.builtin.glob('*/SKILL.md')):
            if path.parent.name not in {'contract-summary','contract-review','contract-redline'} and not (u and u.get('role')=='admin'):continue
            parts = path.read_text().split('---', 2)
            if len(parts) != 3:
                continue
            meta = yaml.safe_load(parts[1])
            heading = re.search(r'^#\s+(.+)$', parts[2], re.M)
            refs = {str(p.relative_to(path.parent)): p.read_text() for p in path.parent.rglob('*')
                    if p.is_file() and p.suffix in {'.md', '.txt'} and p != path}
            content = {'label': heading[1] if heading else meta['name'], 'description': meta['description'], 'body': parts[2].strip(), 'files': refs}
            result.append({'id': 'builtin:' + meta['name'], 'kind': 'skill', 'name': meta['name'], 'scope': 'builtin',
                           'revision': 1, 'enabled': True, 'editable': False, 'content': content,
                           'hash': hashlib.sha256(encoded(content).encode()).hexdigest()})
        return result

    def item(self, u, iid, revision=None, write=False):
        if iid.startswith('builtin:'):
            row = next((s for s in self.builtins(u) if s['id'] == iid), None)
            if not row or write:
                raise HTTPException(403 if row else 404, '内置 Skill 只读' if row else '配置不存在')
            return row
        row = self.store.one('SELECT * FROM config_items WHERE id=? AND (owner_id=? OR (owner_id IS NULL AND org_id="public")) AND deleted=0',
                             (iid, u['id']))
        if not row:
            raise HTTPException(404, '配置不存在')
        editable = row['owner_id'] == u['id'] or (row['owner_id'] is None and u['role']=='admin')
        if write and not editable:
            raise HTTPException(403, '只有管理员可以修改组织配置')
        version = self.store.one('SELECT * FROM config_versions WHERE item_id=? AND revision=?', (iid, revision or row['revision']))
        if not version:
            raise HTTPException(404, '版本不存在')
        return {**row, 'revision': version['revision'], 'scope': 'personal' if row['owner_id'] else 'public',
                'editable': editable, 'content': json.loads(version['content']), 'hash': version['hash']}

    def items(self, u, kind):
        rows = self.store.all('SELECT id FROM config_items WHERE kind=? AND (owner_id=? OR (owner_id IS NULL AND org_id="public")) AND deleted=0 ORDER BY updated DESC',
                              (kind, u['id']))
        return (self.builtins(u) if kind == 'skill' else []) + [self.item(u, r['id']) for r in rows]

    def validate_skill(self, content):
        if not isinstance(content, dict) or set(content) - {'label', 'description', 'body', 'files'}:
            raise ValueError('Skill 格式无效')
        for key, limit in [('label', 100), ('description', 1024), ('body', 100000)]:
            if not isinstance(content.get(key), str) or not content[key].strip() or len(content[key]) > limit:
                raise ValueError(f'{key} 不能为空，且不能超过 {limit} 字')
        files = content.setdefault('files', {})
        if not isinstance(files, dict) or len(files) > 30:
            raise ValueError('参考文件最多 30 个')
        for name, value in files.items():
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or any(p.startswith('.') for p in path.parts)
                    or str(path) != name or '\\' in name or ':' in name or len(name) > 180
                    or path.suffix.lower() not in {'.md', '.txt'} or path.name.lower() == 'skill.md'
                    or not isinstance(value, str) or len(value.encode()) > 500000):
                raise ValueError('参考文件仅支持安全的 Markdown / TXT 路径，每个文件最多 500 KB')
        if len(encoded(content).encode()) > 2000000:
            raise ValueError('Skill 总大小不能超过 2 MB')
        return content

    def save_item(self, u, kind, body, iid=None):
        if kind not in {'skill', 'risk'}:
            raise ValueError('配置类型无效')
        from .risk_settings import validate_scheme
        content = self.validate_skill(body.get('content')) if kind == 'skill' else validate_scheme(body.get('content'))
        current = self.item(u, iid, write=True) if iid else None
        owner = current.get('owner_id') if current else (None if body.get('scope') == 'public' else u['id'])
        if owner is None:
            admin(u)
        iid = iid or secrets.token_hex(12)
        slug = body.get('name') or (kind + '-' + iid[:8])
        name = current['name'] if current else ('public' if owner is None else 'u-' + u['id'][:8]) + '-' + slug
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
            raise ValueError('调用名称须用小写字母、数字和短横线，连同命名空间最多 64 位')
        revision = (current['revision'] if current else 0) + 1
        value = encoded(content)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if current:
                if current['kind'] != kind or body.get('revision') != current['revision']:
                    raise HTTPException(409, '配置已更新，请重新打开后保存')
                count = db.execute('UPDATE config_items SET revision=?,enabled=?,updated=? WHERE id=? AND revision=?',
                                   (revision, int(bool(body.get('enabled', True))), time.time(), iid, current['revision'])).rowcount
                if not count:
                    raise HTTPException(409, '配置已更新，请重新打开后保存')
            else:
                if db.execute('SELECT 1 FROM config_items WHERE name=?', (name,)).fetchone():
                    raise HTTPException(409, '调用名称已被使用')
                db.execute('INSERT INTO config_items VALUES(?,?,?,?,?,?,?,0,?)',
                           (iid, 'public' if owner is None else 'personal', owner, kind, name, revision, int(bool(body.get('enabled', True))), time.time()))
            db.execute('INSERT INTO config_versions VALUES(?,?,?,?,?,?)',
                       (iid, revision, value, hashlib.sha256(value.encode()).hexdigest(), time.time(), u['id']))
        self.audit(u, kind + '.save', iid)
        return self.item(u, iid)

    async def prepare_skills(self, u, t, rt):
        """Called only while the thread is idle, under its send/refresh lock."""
        if rt.config.get('e2b'):
            if rt.config.get('staging_only'):return []
            return rt.e2b.skill_sync.versions(u,rt.w['id'])
        items = [s for s in self.items(u, 'skill') if s['enabled'] and s['scope'] != 'builtin']
        manifest = [{'id': s['id'], 'revision': s['revision'], 'hash': s['hash'], 'name': s['name']} for s in items]
        wd = self.store.user_root(u['id']) / 'threads' / t['id']
        saved = wd / '.skill-versions.json'
        previous = json.loads(saved.read_text()) if saved.exists() else []
        roots = [rt.config["skill_root"] + "/skills"]
        for item in items:
            # Each thread receives only its selected immutable versions. No links to
            # another member's directory, and no mutable reference file in a run.
            base = wd / '.skill-versions' / item['hash']
            dest = base / item['name']
            dest.mkdir(parents=True, exist_ok=True)
            if not (dest / 'SKILL.md').exists():
                data = item['content']
                for name, value in data.get('files', {}).items():
                    file = dest / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(value)
                (dest / 'SKILL.md').write_text('---\n' + yaml.safe_dump({'name': item['name'], 'description': data['description']}, allow_unicode=True) + '---\n\n# ' + data['label'] + '\n\n' + data['body'] + '\n')
            roots.append(rt.directory(t['id']) + '/.skill-versions/' + item['hash'])
        config_path = wd / "opencode.json"
        configured = json.loads(config_path.read_text()).get("skills", {}).get("paths") if config_path.exists() else None
        if manifest != previous or (configured is not None and configured != roots):
            # Project config is controlled by Web. Native discovery/skill invocation
            # remains responsible for loading the definitions.
            path = wd / 'opencode.json'
            config = json.loads(path.read_text()) if path.exists() else {}
            config['skills'] = {'paths': roots}
            temp = path.with_suffix('.tmp')
            temp.write_text(encoded(config)); temp.replace(path)
            await rt.call('POST', '/instance/dispose', tid=t['id'])
            saved.write_text(encoded(manifest))
        rt.config['thread_skills'] = roots
        return manifest
