import asyncio
import json
from pathlib import Path

import test_workbench as fixtures
from test_workbench import FakeRuntime
from contract_web.settings import Settings


class SettingsTests(fixtures.WorkbenchTests):
    # Reuse the fixture, not the inherited test suite.
    def skill(self, **extra):
        body = {'content': {'label': '付款检查', 'description': '读取合同并检查付款安排',
                            'body': '读取 references/guide.md，再回答付款问题。', 'files': {'references/guide.md': '版本一：说明付款期限'}}, **extra}
        r = self.client.post('/api/skills', json=body, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_settings_scopes_admin_and_optimistic_versions(self):
        self.assertEqual(self.client.get('/api/me').json()['role'], 'member')
        prefs = self.client.get('/api/settings').json()
        self.assertEqual(prefs['effective']['perspective'], '乙方')
        value = {'values': {'perspective': '甲方', 'permission_mode': 'cautious'}, 'revision': prefs['revision']}
        r = self.client.put('/api/settings', json=value, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.put('/api/settings', json=value, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.put('/api/admin/organization', json={}, headers=self.headers).status_code, 403)
        w,t = self.make_workspace()
        self.assertEqual(t['permission_mode'], 'cautious')
        context = json.loads((self.store.user_root(self.uid)/'threads'/t['id']/'context.json').read_text())
        self.assertEqual(context['default_perspective'], '甲方')
        self.login('bob');self.assertEqual(self.client.get('/api/settings').json()['effective']['perspective'], '乙方')

    def test_skill_owner_org_copy_traversal_and_conflicts(self):
        skill = self.skill()
        route = '/api/skills/'+skill['id']
        bad = {**skill, 'revision': 0}
        self.assertEqual(self.client.put(route, json=bad, headers=self.headers).status_code, 409)
        body = {**skill, 'content': {**skill['content'], 'files': {'../secret.txt': 'bad'}}}
        self.assertEqual(self.client.put(route, json=body, headers=self.headers).status_code, 422)
        self.login('bob')
        self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.put(route, json=skill, headers=self.headers).status_code, 404)
        self.assertNotIn(skill['id'], [s['id'] for s in self.client.get('/api/skills').json()])
        self.login('alice');self.store.execute("UPDATE users SET role='admin' WHERE id=?", (self.uid,))
        shared = self.skill(scope='public', name='payment-guide')
        self.login('bob')
        self.assertEqual(self.client.get('/api/skills/'+shared['id']).status_code, 200)
        self.assertEqual(self.client.put('/api/skills/'+shared['id'],json=shared,headers=self.headers).status_code,403)
        copy = self.client.post('/api/skills/'+shared['id']+'/copy',json={},headers=self.headers).json()
        self.assertEqual(copy['scope'],'personal');self.assertNotEqual(copy['name'],shared['name'])

    def test_skill_reference_version_is_pinned_until_next_idle_refresh(self):
        skill = self.skill(); w,t = self.make_workspace()
        wd = self.store.user_root(self.uid)/'threads'/t['id']
        before = (wd/'opencode.json').read_bytes()
        old = wd/'.skill-versions'/skill['hash']/skill['name']/'references/guide.md'
        self.assertEqual(old.read_text(),'版本一：说明付款期限')
        self.native(t)['status'] = {'type':'busy'}
        body = {**skill,'content':{**skill['content'],'files':{'references/guide.md':'版本二：说明付款金额'}}}
        updated = self.client.put('/api/skills/'+skill['id'],json=body,headers=self.headers)
        self.assertEqual(updated.status_code,200,updated.text)
        updated = updated.json();self.assertNotEqual(updated['hash'],skill['hash'])
        route = '/api/threads/'+t['id']+'/skills/refresh'
        self.assertEqual(self.client.post(route,json={},headers=self.headers).status_code,409)
        self.assertEqual((wd/'opencode.json').read_bytes(),before)
        self.native(t)['status'] = {'type':'idle'}
        self.assertEqual(self.client.post(route,json={},headers=self.headers).status_code,200)
        self.assertEqual(old.read_text(),'版本一：说明付款期限')
        current = wd/'.skill-versions'/updated['hash']/skill['name']/'references/guide.md'
        self.assertEqual(current.read_text(),'版本二：说明付款金额')
        self.assertEqual(len(self.client.get('/api/skills/'+skill['id']+'/versions').json()),2)
        perms = asyncio.run(FakeRuntime(self.store.runtime('alice')).permissions(t['id'], []))
        self.assertTrue(any(p['permission']=='edit' and p['action']=='deny' and p['pattern'].endswith('/.skill-versions/*') for p in perms))

    def test_default_execution_changes_next_turn_but_explicit_thread_choice_wins(self):
        w,t=self.make_workspace()
        prefs=self.client.get('/api/settings').json()
        self.client.put('/api/settings',json={'values':{'permission_mode':'cautious'},'revision':prefs['revision']},headers=self.headers).raise_for_status()
        self.assertEqual(self.send(t).status_code,202)
        self.assertEqual(self.store.one('SELECT permission_mode FROM threads WHERE id=?',(t['id'],))['permission_mode'],'cautious')
        self.native(t)['status']={'type':'idle'}
        self.client.put('/api/threads/'+t['id']+'/permission-mode',json={'mode':'auto'},headers=self.headers).raise_for_status()
        self.assertEqual(self.send(t).status_code,202)
        self.assertEqual(self.store.one('SELECT permission_mode FROM threads WHERE id=?',(t['id'],))['permission_mode'],'auto')

    def test_password_changes_revoke_sessions(self):
        self.assertEqual(self.client.put('/api/settings/password',json={'current':'wrong','password':'Contract1'},headers=self.headers).status_code,422)
        r = self.client.put('/api/settings/password',json={'current':'alice-password-2026','password':'Contract1'},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'username':'alice','password':'Contract1'},headers=self.headers).status_code,200)


# Inherited fixture helpers are useful; collect only the settings-specific cases.
for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(SettingsTests):
        setattr(SettingsTests, _name, None)
