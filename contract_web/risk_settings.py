"""Versioned risk schemes and execution snapshots, never another review engine."""
import hashlib
import json
import secrets
import time
from pathlib import Path

import yaml
from fastapi import HTTPException

from .documents import active_rules
from .settings import encoded


def validate_scheme(content):
    if not isinstance(content, dict) or not isinstance(content.get('label'), str) or not 1 <= len(content['label'].strip()) <= 100:
        raise ValueError('请填写 1–100 字的方案名称')
    rules = content.get('rules')
    if not isinstance(rules, list) or len(rules) > 1000 or len(encoded(content).encode()) > 3000000:
        raise ValueError('方案最多 1000 个风险点，总大小不超过 3 MB')
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError('风险点须为对象')
        for key in ('id', 'name'):
            if not isinstance(rule.get(key), str) or not rule[key].strip() or len(rule[key]) > 200:
                raise ValueError('风险编号和名称不能为空且不超过 200 字')
        if rule['id'] in ids:
            raise ValueError('风险编号不能重复：' + rule['id'])
        ids.add(rule['id'])
        if 'enabled' in rule and not isinstance(rule['enabled'], bool):
            raise ValueError('启停状态须为布尔值')
        for key in ('category', 'industry', 'baseline', 'definition'):
            if key in rule and (not isinstance(rule[key], str) or len(rule[key]) > 50000):
                raise ValueError('风险点文本字段格式无效：' + key)
    return content


class RiskSettings:
    def __init__(self, settings, library):
        self.settings, self.store = settings, settings.store
        self.library = Path(library)
        with self.store.connect() as db:
            for table in ('users', 'threads'):
                if 'risk_scheme' not in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN risk_scheme TEXT')
        # Import the deployed library exactly once, retaining inactive points and
        # all extension fields. Later file changes do not rewrite saved schemes.
        if not self.store.one("SELECT 1 FROM config_items WHERE kind='risk' AND org_id='default'"):
            enabled = {r['id'] for r in active_rules(self.library)}
            rules = []
            for path in sorted(self.library.glob('*.yaml')):
                if not path.name.startswith('_'):
                    rules += [{**r, 'enabled': r['id'] in enabled} for r in yaml.safe_load(path.read_text()) or []]
            content = {'label': '组织默认审查方案', 'description': '从当前部署风险库导入', 'rules': rules}
            value = encoded(content)
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute("SELECT 1 FROM config_items WHERE kind='risk' AND org_id='default'").fetchone():
                    iid = secrets.token_hex(12)
                    db.execute('INSERT INTO config_items VALUES(?,?,?,?,?,?,?,0,?)', (iid, 'default', None, 'risk', 'risk-default', 1, 1, time.time()))
                    db.execute('INSERT INTO config_versions VALUES(?,?,?,?,?,?)', (iid, 1, value, hashlib.sha256(value.encode()).hexdigest(), time.time(), 'system'))
                    org = json.loads(db.execute("SELECT settings FROM organizations WHERE id='default'").fetchone()[0])
                    org['risk_scheme'] = iid
                    db.execute("UPDATE organizations SET settings=? WHERE id='default'", (encoded(org),))

    def choose(self, u, iid=None):
        iid = iid or self.store.one('SELECT risk_scheme FROM users WHERE id=?', (u['id'],))['risk_scheme'] or self.settings.organization(u)['settings'].get('risk_scheme')
        item = self.settings.item(u, iid or '')
        if item['kind'] != 'risk' or not item['enabled']:
            raise HTTPException(422, '审查方案已停用或不可用，请重新选择')
        rules = [{k: v for k, v in r.items() if k != 'enabled'} for r in item['content']['rules'] if r.get('enabled', True)]
        return {'id': item['id'], 'label': item['content']['label'], 'revision': item['revision'], 'hash': item['hash'], 'rules': rules}

    def execution(self, u, t, model, skill_versions, risk, message_id=None, after_message_id=None, model_revision=None, skill_revision=None):
        settings = self.settings.preferences(u)
        snapshot = {'after_message_id': after_message_id, 'model_revision': model_revision, 'preferences': settings['effective'], 'organization': settings['organization'],
                    'skills': skill_versions, 'risk_scheme': risk, 'model': model, 'permission_mode': t['permission_mode']}
        if skill_revision is not None:snapshot['skill_environment_revision']=skill_revision
        eid = secrets.token_hex(12)
        self.store.execute('INSERT INTO execution_configs(id,thread_id,user_id,created,config,message_id) VALUES(?,?,?,?,?,?)',
                           (eid, t['id'], u['id'], time.time(), encoded(snapshot), message_id))
        return {'id': eid, **snapshot}

    def recorded(self, u, t):
        context_path = self.store.user_root(u['id']) / 'threads' / t['id'] / 'context.json'
        context = json.loads(context_path.read_text()) if context_path.exists() else {}
        eid = context.get('execution_id')
        row = self.store.one('SELECT config FROM execution_configs WHERE id=? AND thread_id=? AND user_id=?', (eid, t['id'], u['id'])) if eid else None
        if row:
            return {'id': eid, **json.loads(row['config'])}
        return None
