import asyncio
import json
import os
import secrets
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from contract_web.presentation import PublicView
from contract_web.runtime import Runtime, visible_messages, visible_event
import test_workbench as fixtures


class MemoryTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace

    def enable(self, enabled=True):
        status = self.client.get('/api/settings/labs').json()
        r = self.client.patch('/api/settings/labs', json={'memory_enabled': enabled, 'revision': status['revision']}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def add(self, text='Start summaries with the conclusion.'):
        r = self.client.post('/api/memories', json={'content': text}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['item']

    def execution(self):
        self.enable()
        w, t = self.make_workspace()
        u = self.store.one('SELECT * FROM users WHERE id=?', (self.uid,))
        thread = self.store.one('SELECT * FROM threads WHERE id=?', (t['id'],))
        rt = Runtime({'work_root': str(self.store.user_root(self.uid)/'threads'), 'save_url':'http://testserver/internal/artifacts'})
        e = self.app.state.risks.execution(u, thread, {}, [], {})
        self.app.state.memory.prepare(u, thread, rt, e, 'msg_user')
        cap = json.loads((self.store.user_root(self.uid)/'threads'/t['id']/'.memory-capability').read_text())
        req = {'request_id': secrets.token_hex(32), 'execution_id': e['id'], 'thread_id': t['id'], 'session_id': thread['session_id'], 'message_id': 'msg_assistant', 'action':'create', 'content':'Use concise paragraphs.'}
        return w, thread, u, e, cap, req

    def test_default_manual_management_disable_and_general_reset(self):
        self.assertFalse(self.client.get('/api/settings/labs').json()['effective'])
        item = self.add()
        self.enable()
        prefs = self.client.get('/api/settings').json()
        r = self.client.put('/api/settings', json={'revision':prefs['revision'],'values':{'onboarding_completed':True}}, headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(self.client.get('/api/settings/labs').json()['effective'])
        self.enable(False)
        r = self.client.patch('/api/memories/'+item['id'],json={'content':'Edited manually','revision':1},headers=self.headers)
        self.assertEqual(r.json()['item']['revision'],2)
        self.login('alice')
        self.assertEqual(self.client.get('/api/memories').json()['items'][0]['content'],'Edited manually')
        self.assertFalse(self.client.get('/api/settings/labs').json()['effective'])
        self.enable()
        self.assertEqual(len(self.client.get('/api/memories').json()['items']),1)
        self.assertEqual(self.client.get('/labs').status_code,200)

    def test_isolation_conflicts_limits_demo_and_kill_switch(self):
        item = self.add()
        self.login('bob')
        self.assertEqual(self.client.get('/api/memories').json()['items'],[])
        r=self.client.delete('/api/memories/'+item['id']+'?revision=1',headers=self.headers)
        self.assertEqual(r.status_code,404)
        self.login('alice')
        r=self.client.patch('/api/memories/'+item['id'],json={'content':'changed','revision':0},headers=self.headers)
        self.assertEqual(r.status_code,409)
        self.assertEqual(self.client.post('/api/memories',json={'content':'x'*501},headers=self.headers).status_code,422)
        self.client.delete('/api/memories/'+item['id']+'?revision=1',headers=self.headers)
        for _ in range(24):self.add('x'*500)
        self.assertEqual(self.client.post('/api/memories',json={'content':'x'},headers=self.headers).status_code,422)
        with patch.dict(os.environ,{'CW_MEMORY_ENABLED':'0'}):
            self.assertFalse(self.client.get('/api/settings/labs').json()['available'])
        self.store.execute("UPDATE users SET account_kind='demo' WHERE id=?",(self.uid,))
        self.assertFalse(self.client.get('/api/settings/labs').json()['available'])

    def test_native_commit_retry_switch_and_credential_boundary(self):
        w,t,u,e,cap,req=self.execution()
        endpoint=lambda body,token=cap['token']:self.client.post('/internal/memory',json=body,headers={'Authorization':'Bearer '+token})
        first=endpoint(req)
        self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(first.json()['saved'])
        self.assertEqual(endpoint(req).json(),first.json())
        self.assertEqual(len(self.app.state.memory.items(u)),1)
        self.assertEqual(endpoint({**req,'content':'changed'}).status_code,409)
        self.assertEqual(endpoint(req,'bad-token').status_code,403)
        self.enable(False)
        self.assertEqual(endpoint(req).status_code,403)
        self.enable()
        self.store.execute("UPDATE execution_configs SET status='completed' WHERE id=?",(e['id'],))
        self.assertEqual(endpoint(req).json(),first.json())
        self.assertEqual(endpoint({**req,'request_id':secrets.token_hex(32)}).status_code,409)

    def test_snapshots_and_server_verified_historical_references(self):
        item=self.add()
        w,t,u,e,cap,req=self.execution()
        view=PublicView(memory=self.app.state.memory.projector(u,t))
        info={'id':'msg_assistant','role':'assistant','parentID':'msg_user'}
        text={'id':'part_text','messageID':'msg_assistant','type':'text','text':f"Answer [[memory:{item['id']}:1]] [[memory:{'f'*24}:1]]"}
        projected=visible_messages([{'info':info,'parts':[text]}],view)[0]['parts'][0]
        self.assertEqual(len(projected['memory_references']),1)
        self.assertNotIn('[[memory:',projected['text'])
        self.app.state.memory.manual(u,'update',{'id':item['id'],'revision':1,'content':'New preference'})
        self.assertEqual(view.part(text)['memory_references'][0]['current_revision'],2)
        self.assertEqual(view.part(text)['memory_references'][0]['content'],item['content'])
        self.app.state.memory.manual(u,'delete',{'id':item['id'],'revision':2})
        self.assertIsNone(view.part(text)['memory_references'][0]['current_revision'])
        self.assertEqual(self.app.state.memory.snapshot(u)['items'],[])
        forged={**text,'messageID':'msg_other'}
        self.assertNotIn('memory_references',view.part(forged))
        r=self.app.state.memory.execute(u,req,token=cap['token'])
        p={'id':'part_tool','type':'tool','tool':'memory','messageID':'msg_assistant','state':{'status':'completed','output':json.dumps(r)}}
        self.assertTrue(view.part(p)['memory_receipt']['saved'])
        self.assertNotIn('memory_receipt',view.part({**p,'messageID':'msg_forged'}))
        p['state']['output']=json.dumps({'saved':True,'request_id':'fake'})
        self.assertNotIn('memory_receipt',view.part(p))

    def test_e2b_collector_retries_and_rejects_other_workspace(self):
        w,t,u,e,cap,req=self.execution()
        folder='/workspace/exchange/memory/'
        path=folder+req['request_id']+'.request.json'
        content={path:json.dumps(req).encode()}
        class Files:
            async def list(self,*args,**kwargs):return [SimpleNamespace(name=Path(p).name,path=p,size=len(v)) for p,v in list(content.items())]
            async def read(self,p,**kwargs):return content[p]
            async def write(self,p,v):content[p]=v.encode()
            async def remove(self,p):content.pop(p,None)
        sbx=SimpleNamespace(files=Files())
        asyncio.run(self.app.state.memory.collect(u,w,sbx))
        result=json.loads(content[path.replace('.request.','.receipt.')])
        self.assertTrue(result['saved'])
        content[path]=json.dumps(req).encode()
        asyncio.run(self.app.state.memory.collect(u,w,sbx))
        self.assertEqual(len(self.app.state.memory.items(u)),1)
        with self.assertRaises(HTTPException):self.app.state.memory.execute(u,req,workspace_id='different')

    def test_disabled_snapshot_never_carries_items(self):
        self.add()
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        self.assertEqual(self.app.state.memory.snapshot(u),{'enabled':False,'items':[]})


if __name__=='__main__':unittest.main()
