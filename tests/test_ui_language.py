import json
import unittest
from unittest.mock import patch

import test_workbench as fixtures
from contract_web.presentation import PublicView
from contract_web.runtime import visible_event


class UILanguageTests(fixtures.WorkbenchTests):
    def choose(self, value):
        return self.client.put('/api/settings/language', json={'ui_language': value}, headers=self.headers)

    def test_language_is_account_owned_validated_and_does_not_touch_models(self):
        prefs=self.client.get('/api/settings').json()
        self.assertEqual(prefs['effective']['ui_language'],'zh-CN')
        self.client.put('/api/settings',json={'values':{'assistant_name':'合同助手-自定义','background':'中文业务背景'},'revision':prefs['revision']},headers=self.headers).raise_for_status()
        with patch.object(self.app.state.manager,'ensure',side_effect=AssertionError('UI settings must not prepare a runtime')):
            self.choose('en').raise_for_status()
        prefs=self.client.get('/api/settings').json()
        self.assertEqual(prefs['effective']['ui_language'],'en')
        self.assertEqual(prefs['values']['assistant_name'],'合同助手-自定义')
        self.assertEqual(prefs['values']['background'],'中文业务背景')
        self.assertEqual(self.client.get('/api/me').json()['ui_language'],'en')
        for invalid in ['fr',None,[],{'locale':'en'}]:
            self.assertEqual(self.choose(invalid).status_code,422)
        self.assertEqual(self.client.put('/api/settings/language',json={'ui_language':'en','model':'bad'},headers=self.headers).status_code,422)
        self.login('bob');self.assertEqual(self.client.get('/api/settings').json()['effective']['ui_language'],'zh-CN')
        self.login('alice');self.assertEqual(self.client.get('/api/me').json()['ui_language'],'en')

    def test_general_settings_preserve_language_and_keep_revision_conflicts(self):
        original=self.client.get('/api/settings').json()
        self.choose('en').raise_for_status()
        stale=self.client.put('/api/settings',json={'values':{},'revision':original['revision']},headers=self.headers)
        self.assertEqual(stale.status_code,409)
        prefs=self.client.get('/api/settings').json()
        self.client.put('/api/settings',json={'values':{'verbosity':'concise'},'revision':prefs['revision']},headers=self.headers).raise_for_status()
        self.assertEqual(self.client.get('/api/settings').json()['effective']['ui_language'],'en')

    def test_snapshot_and_sse_translate_only_public_receipt_labels(self):
        w,t=self.make_workspace();source='保存、删除、合同助手是用户原文。'
        part={'id':'part1','messageID':'msg1','type':'tool','tool':'read','state':{'status':'completed','input':{'filePath':f'/sources/{w["document_id"]}/contract.md','offset':2,'limit':3},'output':source}}
        self.native(t)['messages']=[{'info':{'id':'msg1','role':'assistant','time':{'completed':1}},'parts':[part,{'id':'text1','type':'text','text':source}]}]
        self.choose('en').raise_for_status()
        snapshot=self.client.get('/api/threads/'+t['id']).json()
        self.assertIn('Lines 2–4',snapshot['messages'][0]['parts'][0]['state']['detail'])
        self.assertEqual(snapshot['messages'][0]['parts'][1]['text'],source)
        async def events(rt,thread):
            yield {'type':'message.part.updated','properties':{'sessionID':t['session_id'],'part':part}}
        with patch.object(fixtures.FakeRuntime,'events',events):
            result=self.client.get('/api/threads/'+t['id']+'/events').text
        self.assertIn('Lines 2',result)
        self.assertNotIn('"output"',result)
        self.assertEqual(part['state']['output'],source)
        self.send(t).raise_for_status()
        context=json.loads((self.store.user_root(self.uid)/'threads'/t['id']/'context.json').read_text())
        self.assertNotIn('ui_language',context['preferences'])
        calls=fixtures.FakeRuntime.servers['http://alice']['calls']
        body=next(body for method,path,tid,body in reversed(calls) if path.endswith('/prompt_async'))
        self.assertNotIn('ui_language',body['system'])
        self.assertNotIn('working language',body['system'])


for name in vars(fixtures.WorkbenchTests):
    if name.startswith('test_') and name not in vars(UILanguageTests):setattr(UILanguageTests,name,None)


class PublicLanguageTests(unittest.TestCase):
    def test_paths_quotes_todos_and_permission_identity(self):
        en=PublicView({'/work/thread':'This conversation'},locale='en')
        self.assertEqual(en.text('原文 /work/thread/中文.md https://example.com/work/thread/x'),'原文 This conversation/中文.md https://example.com/work/thread/x')
        self.assertEqual(en.text('C:/tmp/中文.md'),'Working file/中文.md')
        request={'id':'req','sessionID':'ses','permission':'bash','patterns':['python *'],'metadata':{'description':'生成报告'}}
        result=en.request(request)
        self.assertEqual(result['id'],'req');self.assertEqual(result['patterns'],['python *']);self.assertEqual(result['description'],'生成报告')
        todo=en.part({'type':'tool','tool':'todowrite','state':{'status':'running','input':{'todos':[{'content':'读取中文合同'}]}}})
        self.assertIn('读取中文合同',todo['state']['detail'])
        rejected=en.part({'type':'tool','tool':'bash','state':{'status':'error','error':'user rejected'}})
        self.assertIn('You rejected',rejected['state']['detail'])
        zh=PublicView();self.assertEqual(zh.text('/tmp/a.txt'),'工作文件/a.txt')

    def test_changing_locale_keeps_streaming_text_state(self):
        view=PublicView();known=set()
        part={'id':'p','sessionID':'s','messageID':'m','type':'text','text':'原文'}
        visible_event({'type':'message.part.updated','properties':{'part':part}},'s',known,view)
        view.locale='en'
        result=visible_event({'type':'message.part.delta','properties':{'sessionID':'s','partID':'p','field':'text','delta':'保留'}},'s',known,view)
        self.assertEqual(result['properties']['part']['text'],'原文保留')
