import json
from unittest.mock import AsyncMock,patch
import test_workbench as fixtures

class TaskControlsTests(fixtures.WorkbenchTests):
    def test_trial_notice_dismissal_is_account_scoped_and_survives_settings_reset(self):
        self.assertFalse(self.client.get('/api/me').json()['trial_notice_dismissed'])
        self.store.execute("UPDATE users SET preferences=? WHERE id=?",(json.dumps({'assistant_name':'My helper','memory_enabled':True}),self.uid))
        r=self.client.post('/api/settings/trial-notice/dismiss',json={},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(self.client.get('/api/me').json()['trial_notice_dismissed'])
        prefs=self.client.get('/api/settings').json()
        self.assertEqual(prefs['effective']['assistant_name'],'My helper')
        self.assertTrue(prefs['effective']['memory_enabled'])
        self.client.put('/api/settings',json={'values':{},'revision':prefs['revision']},headers=self.headers).raise_for_status()
        self.assertTrue(self.client.get('/api/me').json()['trial_notice_dismissed'])
        self.login('bob');self.assertFalse(self.client.get('/api/me').json()['trial_notice_dismissed'])
        self.login('alice');self.assertTrue(self.client.get('/api/me').json()['trial_notice_dismissed'])

    def test_dismiss_plan_persists_without_mutating_native_execution_and_is_owner_scoped(self):
        w,t=self.make_workspace();path=f'/api/threads/{t["id"]}/tasks/dismiss'
        signature=json.dumps(['tool-call-1',[{'content':'Save report','status':'pending'}]])
        calls=len(self.native(t)['messages'])
        self.client.post(path,json={'signature':signature},headers=self.headers).raise_for_status()
        self.assertEqual(self.client.get('/api/threads/'+t['id']).json()['dismissed_todos'],signature)
        self.assertEqual(len(self.native(t)['messages']),calls)
        self.assertEqual(self.client.post(path,json={'signature':[]},headers=self.headers).status_code,422)
        self.login('bob');self.assertEqual(self.client.post(path,json={'signature':signature},headers=self.headers).status_code,404)

    def test_exhausted_default_falls_back_but_explicit_available_choice_is_preserved(self):
        w,t=self.make_workspace()
        catalog={'models':[{'id':'trial/one','providerID':'trial','label':'Trial'},{'id':'glm/glm-test','providerID':'glm','modelID':'glm-test','label':'First'},{'id':'deepseek/flash','providerID':'deepseek','label':'Second'}], 'default':'trial/one'}
        self.store.execute("UPDATE users SET trial_total=1,trial_used=1 WHERE id=?",(self.uid,))
        self.store.execute("UPDATE threads SET model='trial/one' WHERE id=?",(t['id'],))
        with patch.object(fixtures.FakeRuntime,'models',AsyncMock(return_value=catalog)):
            c=self.client.get('/api/models?thread_id='+t['id']).json()
            self.assertEqual(c['selected'],'glm/glm-test');self.assertTrue(c['available'])
            route='/api/threads/'+t['id']+'/model'
            self.assertEqual(self.client.put(route,json={'model':'trial/one'},headers=self.headers).status_code,422)
            self.client.put(route,json={'model':'deepseek/flash'},headers=self.headers).raise_for_status()
            self.assertEqual(self.client.get('/api/models?thread_id='+t['id']).json()['selected'],'deepseek/flash')
            self.store.execute("UPDATE threads SET model='trial/one' WHERE id=?",(t['id'],))
            self.send(t).raise_for_status()
            queued=self.store.one('SELECT body FROM queued_messages WHERE thread_id=?',(t['id'],))
            self.assertEqual(json.loads(queued['body'])['model'],'glm/glm-test')
        with patch.object(fixtures.FakeRuntime,'models',AsyncMock(return_value={**catalog,'models':catalog['models'][:1]})):
            c=self.client.get('/api/models?thread_id='+t['id']).json()
            self.assertIsNone(c['selected']);self.assertFalse(c['available'])

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(TaskControlsTests):setattr(TaskControlsTests,_name,None)
