import json
import test_workbench as fixtures
from contract_web.traces import redact

class TraceTests(fixtures.WorkbenchTests):
    def test_contract_ids_sessions_and_chronological_turns_are_not_merged(self):
        w,t=self.make_workspace();w2,t2=self.make_workspace()
        t3=self.client.post(f'/api/workspaces/{w["id"]}/threads',json={},headers=self.headers).json()
        self.assertEqual(w['title'],w2['title'])
        for thread in [t,t2,t3]:
            messages=[]
            for n in range(55 if thread==t else 1):
                messages.extend([
                    {'info':{'id':f'msg_user_{n:03}','role':'user'},'parts':[{'type':'text','text':f'第{n+1}次问题'}]},
                    {'info':{'id':f'msg_assistant_{n:03}','role':'assistant','finish':'stop'},'parts':[{'type':'tool','tool':'read','state':{'status':'completed','input':{'filePath':f'file-{n+1}.txt'},'output':f'第{n+1}轮结果'}}]}])
            self.native(thread)['messages']=messages;self.native(thread)['status']={'type':'idle'}
        refresh=self.client.post('/api/traces/refresh',json={},headers=self.headers)
        self.assertEqual(refresh.status_code,200,refresh.text)
        groups=self.client.get('/api/traces/contracts').json()
        self.assertEqual(groups['total'],2);self.assertEqual({r['id'] for r in groups['contracts']},{w['id'],w2['id']})
        sessions=self.client.get(f'/api/traces/contracts/{w["id"]}/threads').json()['threads']
        self.assertEqual({s['id'] for s in sessions},{t['id'],t3['id']})
        first=self.client.get(f'/api/traces/threads/{t["id"]}/runs').json()
        last=self.client.get(f'/api/traces/threads/{t["id"]}/runs?offset=50').json()
        self.assertEqual(first['total'],55)
        self.assertEqual([r['summary']['turn'] for r in first['runs']+last['runs']],list(range(1,56)))
        self.assertEqual(first['runs'][0]['summary']['tool_count'],1)
        detail=self.client.get('/api/traces/'+first['runs'][0]['id']).json()
        self.assertEqual(len(detail['messages']),2);self.assertEqual(detail['messages'][1]['parts'][0]['state']['output'],'第1轮结果')
        self.assertEqual(self.client.get('/api/traces/contracts',params={'q':w['id']}).json()['total'],1)
        self.assertEqual(self.client.get('/api/traces/contracts',params={'q':'第55次问题'}).json()['total'],1)
        self.login('bob')
        self.assertEqual(self.client.get('/api/traces/contracts').json()['contracts'],[])
        for path in [f'/api/traces/contracts/{w["id"]}/threads',f'/api/traces/threads/{t["id"]}/runs']:
            self.assertEqual(self.client.get(path).status_code,404)
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.get('/api/traces/contracts').json()['total'],0)
        self.store.execute("INSERT INTO organizations(id,name,settings,revision) VALUES('other','Other','{}',1)")
        self.store.execute("UPDATE users SET org_id='other' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.get('/api/traces/contracts').json()['total'],0)
        self.assertEqual(self.client.get(f'/api/traces/threads/{t["id"]}/runs').status_code,404)

    def test_settings_deep_links_start_with_hidden_login(self):
        for path in ['/config','/model','/skills','/risks','/traces','/organization','/members']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertIn('body data-auth="loading"',response.text)
            self.assertIn('id="loginView" class="login-view" hidden',response.text)

    def test_native_trace_error_usage_and_secret_redaction(self):
        w,t=self.make_workspace();self.send(t)
        token=(self.store.user_root(self.uid)/'threads'/t['id']/'.publish-token').read_text()
        self.native(t)['messages'] += [{'info':{'id':'msg_result','role':'assistant','providerID':'glm','modelID':'glm-test','parentID':self.native(t)['messages'][0]['info']['id'],'time':{'created':1789000000000,'completed':1789000001000},'finish':'stop','tokens':{'input':120,'output':30},'cost':0},'parts':[
            {'type':'reasoning','text':'PRIVATE_INTERNAL_REASONING'},
            {'type':'tool','tool':'read','state':{'status':'error','input':{'filePath':'/work/missing.txt','apiKey':'secret-value'},'error':'File not found: missing.txt','output':'token='+token+' API_KEY=PRIVATE_KEY'}},
            {'type':'text','text':'参考文件不存在，请补充。'}]}]
        self.native(t)['status']={'type':'idle'}
        self.client.get('/api/threads/'+t['id'])
        runs=self.client.get('/api/traces').json()['runs']
        self.assertEqual(len(runs),1);self.assertEqual(runs[0]['summary']['tokens'],150);self.assertIsNone(runs[0]['summary']['cost'])
        self.assertEqual(runs[0]['summary']['tool_errors'],1)
        self.assertEqual(self.client.get('/api/traces/contracts?status=errors').json()['total'],1)
        self.assertEqual(self.client.get('/api/traces/contracts?status=failed').json()['total'],0)
        detail=self.client.get('/api/traces/'+runs[0]['id']);self.assertEqual(detail.status_code,200,detail.text)
        for forbidden in ['PRIVATE_INTERNAL_REASONING','PRIVATE_KEY','secret-value',token]:self.assertNotIn(forbidden,detail.text)
        self.assertIn('File not found',detail.text)
        raw=self.store.one('SELECT summary FROM trace_runs WHERE id=?',(runs[0]['id'],))['summary']
        self.assertNotIn('missing.txt',raw)
        self.assertIsNotNone(detail.json()['configuration'])

    def test_trace_admin_access_audit_does_not_expand_artifact_access(self):
        w,t=self.make_workspace();self.send(t);self.client.get('/api/threads/'+t['id'])
        rid=self.client.get('/api/traces').json()['runs'][0]['id']
        self.login('bob')
        self.assertEqual(self.client.get('/api/traces/'+rid).status_code,404)
        self.assertEqual(self.client.get('/api/traces').json()['runs'],[])
        self.assertEqual(self.client.get('/api/admin/audit').status_code,403)
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.get('/api/traces/'+rid).status_code,404)
        audit=self.client.get('/api/admin/audit').json()
        self.assertFalse(any(r['target']==rid for r in audit))
        self.assertEqual(self.client.get('/api/workspaces/'+w['id']).status_code,404)

    def test_rotated_native_auth_credentials_are_hidden_in_errors_and_tools(self):
        w,t=self.make_workspace();self.send(t)
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.uid,))
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));models=self.app.state.models
        body={'id':'custom','label':'自定义','base_url':'https://example.com/v1','models':[{'id':'one','label':'模型'}], 'key':'OLD_OPAQUE_CREDENTIAL'}
        models.save(u,body);models.save(u,{**body,'revision':1,'key':'CURRENT_OPAQUE_CREDENTIAL'})
        self.native(t)['messages'][0]['parts'].append({'type':'text','text':'OLD_OPAQUE_CREDENTIAL CURRENT_OPAQUE_CREDENTIAL runtime-password'})
        self.native(t)['messages'].append({'info':{'id':'msg_error','role':'assistant','error':{'name':'APIError','data':{'message':'Failed OLD_OPAQUE_CREDENTIAL'}}},'parts':[
            {'type':'tool','tool':'read','state':{'status':'error','output':'OLD_OPAQUE_CREDENTIAL CURRENT_OPAQUE_CREDENTIAL','error':'失败'}}]})
        self.native(t)['status']={'type':'idle'}
        self.client.get('/api/threads/'+t['id'])
        listing=self.client.get('/api/traces');detail=self.client.get('/api/traces/'+listing.json()['runs'][0]['id'])
        self.assertEqual(detail.status_code,200,detail.text)
        turns=self.client.get(f'/api/traces/threads/{t["id"]}/runs')
        for response in [listing,detail,turns]:
            self.assertNotIn('OLD_OPAQUE_CREDENTIAL',response.text);self.assertNotIn('CURRENT_OPAQUE_CREDENTIAL',response.text)
            self.assertNotIn('runtime-password',response.text)
        self.assertNotIn('OLD_OPAQUE_CREDENTIAL',self.store.one('SELECT summary FROM trace_runs')['summary'])

    def test_native_compaction_is_visible_without_creating_a_fake_user_run(self):
        w,t=self.make_workspace();self.send(t)
        self.native(t)['messages'] += [
            {'info':{'id':'msg_compact','role':'user'},'parts':[{'type':'compaction','auto':True}]},
            {'info':{'id':'msg_internal','role':'assistant','summary':True,'finish':'stop'},'parts':[{'type':'text','text':'INTERNAL_COMPACTION_SUMMARY'}]},
            {'info':{'id':'msg_final','role':'assistant','finish':'stop'},'parts':[{'type':'text','text':'合同金额为 128000 元。'}]}]
        self.native(t)['status']={'type':'idle'}
        snapshot=self.client.get('/api/threads/'+t['id'])
        self.assertIn('INTERNAL_COMPACTION_SUMMARY',snapshot.text)
        runs=self.client.get('/api/traces').json()['runs'];self.assertEqual(len(runs),1)
        detail=self.client.get('/api/traces/'+runs[0]['id'])
        self.assertNotIn('INTERNAL_COMPACTION_SUMMARY',detail.text)
        self.assertIn('128000',detail.text)

    def test_redaction_retains_business_tokens_and_masks_credentials(self):
        value=redact({'tokens':{'input':100},'Authorization':'Bearer abc','nested':{'api_key':'abc'},'message':'Authorization: Bearer sk-12345678901234567890'})
        self.assertEqual(value['tokens']['input'],100)
        self.assertNotIn('12345678901234567890',json.dumps(value))

for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(TraceTests):setattr(TraceTests,_name,None)
