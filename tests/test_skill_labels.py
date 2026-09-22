import copy
import json
import unittest
import test_workbench as fixtures
from contract_web.presentation import PublicView
from contract_web.runtime import visible_messages, visible_event

class SkillProjectionTests(unittest.TestCase):
    def test_native_tool_receipts_use_business_labels_in_history_and_stream(self):
        name='u-aa658ff9-tech-clause'
        part={'id':'p','sessionID':'s','type':'tool','tool':'skill','state':{'status':'error','input':{'name':name},'error':f'Unable to load {name}','output':name}}
        original=copy.deepcopy(part)
        view=PublicView(skills={name:'识别技术条款'})
        history=visible_messages([{'info':{'role':'assistant'},'parts':[part]}],view)[0]['parts'][0]
        event=visible_event({'type':'message.part.updated','properties':{'part':part}},'s',set(),view)['properties']['part']
        self.assertEqual(history,event)
        self.assertIn('识别技术条款',history['state']['detail'])
        self.assertNotIn(name,json.dumps(history))
        self.assertEqual(part,original)
        self.assertNotIn(name,json.dumps(PublicView().part(part)))

class SkillLabelAPITests(fixtures.WorkbenchTests):
    def test_custom_label_comes_from_owned_settings_and_updates_without_renaming_native_id(self):
        w,t=self.make_workspace()
        body={'content':{'label':'识别技术条款','description':'识别验收要求','body':'读取原文并回答。','files':{}}}
        r=self.client.post('/api/skills',json=body,headers=self.headers);self.assertEqual(r.status_code,200,r.text);skill=r.json()
        part={'id':'p','type':'tool','tool':'skill','state':{'status':'completed','input':{'name':skill['name']}}}
        self.native(t)['messages'].append({'info':{'id':'m','role':'assistant'},'parts':[part]})
        def detail():return self.client.get('/api/threads/'+t['id']).json()['messages'][0]['parts'][0]['state']['detail']
        self.assertEqual(detail(),'识别技术条款')
        body['content']['label']='技术要求识别';body['revision']=skill['revision']
        updated=self.client.put('/api/skills/'+skill['id'],json=body,headers=self.headers);self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(updated.json()['name'],skill['name']);self.assertEqual(detail(),'技术要求识别')
        self.login('bob');w2,t2=self.make_workspace()
        fixtures.FakeRuntime.servers['http://bob']['sessions'][t2['session_id']]['messages'].append({'info':{'id':'m','role':'assistant'},'parts':[part]})
        other=self.client.get('/api/threads/'+t2['id']).json()['messages'][0]['parts'][0]['state']['detail']
        self.assertEqual(other,'所选 Skill')

for _name in vars(fixtures.WorkbenchTests):
    if _name.startswith('test_') and _name not in vars(SkillLabelAPITests):setattr(SkillLabelAPITests,_name,None)
