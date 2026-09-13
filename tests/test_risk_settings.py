import json
from unittest.mock import patch
from fastapi import HTTPException
import test_workbench as fixtures


class RiskSettingsTests(fixtures.WorkbenchTests):
    def copy_scheme(self):
        org = self.client.get('/api/risk-schemes').json()[0]
        return self.client.post('/api/risk-schemes/'+org['id']+'/copy',json={},headers=self.headers).json()

    def delete_scheme(self, item, revision=None):
        return self.client.delete('/api/risk-schemes/'+item['id'],params={'revision':revision or item['revision']},headers=self.headers)

    def test_delete_preserves_versions_active_execution_and_report(self):
        org = self.client.get('/api/risk-schemes').json()[0]
        item = self.copy_scheme()
        self.client.put('/api/risk-schemes/selection',json={'id':item['id']},headers=self.headers)
        w,t = self.make_workspace()
        self.assertEqual(self.send(t,risk_scheme=item['id']).status_code,202)
        self.read_all(w,t)
        context = self.store.user_root(self.uid)/'threads'/t['id']/'risk-library.json'
        library = context.read_bytes()
        snapshots = self.store.all('SELECT * FROM execution_configs')
        versions = self.store.all('SELECT * FROM config_versions WHERE item_id=?',(item['id'],))
        response = self.delete_scheme(item)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/risk-schemes/'+item['id']).status_code,404)
        self.assertNotIn(item['id'],[s['id'] for s in self.client.get('/api/risk-schemes').json()])
        self.assertEqual(self.client.get('/api/risk-schemes/options').json()['selected'],'public-risk-examples')
        self.assertIsNone(self.store.one('SELECT risk_scheme FROM users WHERE id=?',(self.uid,))['risk_scheme'])
        self.assertIsNone(self.store.one('SELECT risk_scheme FROM threads WHERE id=?',(t['id'],))['risk_scheme'])
        self.assertEqual(self.store.all('SELECT * FROM config_versions WHERE item_id=?',(item['id'],)),versions)
        self.assertEqual(self.store.all('SELECT * FROM execution_configs'),snapshots)
        self.assertEqual(context.read_bytes(),library)
        body,mapped = self.report(w)
        body.update(kind='review',content='TEST-1：合同约定验收后30日付款。'+mapped['segments'][3]['citation'],findings=[{'risk_id':'TEST-1','verdict':'未命中','reason':'已约定付款期限。','evidence':[{'document_id':w['document_id'],'source_hash':mapped['source_hash'],'block_id':'B3','quote':'验收后 30 日付款。'}]}])
        published = self.publish(t,body)
        self.assertEqual(published.status_code,200,published.text)
        report = self.client.get('/api/artifacts/'+published.json()['artifact_id']).json()
        self.assertEqual(report['execution_config']['risk_scheme']['id'],item['id'])
        self.assertEqual(report['findings'][0]['risk_name'],'付款')
        self.finish(t)
        self.assertEqual(self.send(t).status_code,202)
        latest = self.store.all('SELECT config FROM execution_configs ORDER BY created DESC')[0]
        self.assertEqual(json.loads(latest['config'])['risk_scheme']['id'],'public-risk-examples')
        self.assertEqual(self.client.get('/api/artifacts/'+published.json()['artifact_id']).json()['execution_config']['risk_scheme']['id'],item['id'])
        audit = self.store.all("SELECT actor_id,target FROM audit_log WHERE action='risk.delete'")
        self.assertEqual(audit,[{'actor_id':self.uid,'target':item['id']}])

    def test_delete_permissions_conflicts_and_default_guard(self):
        public = self.client.get('/api/risk-schemes/public-risk-examples').json()
        item = self.copy_scheme()
        self.assertEqual(self.delete_scheme(public).status_code,403)
        self.assertEqual(self.delete_scheme(item,item['revision']+1).status_code,409)
        self.login('bob')
        self.assertEqual(self.delete_scheme(item).status_code,404)
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.bid,))
        self.assertEqual(self.delete_scheme(item).status_code,404)
        self.assertEqual(self.delete_scheme(public).status_code,422)
        replacement=self.client.post('/api/risk-schemes',json={'scope':'public','content':{'label':'新示例','rules':[]}},headers=self.headers).json()
        self.assertEqual(self.delete_scheme(replacement).status_code,200)
        self.assertEqual(self.client.get('/api/risk-schemes/public-risk-examples').status_code,200)
        self.assertEqual(self.client.put('/api/admin/organization',json={},headers=self.headers).status_code,410)

    def test_delete_rejects_an_edit_that_read_the_previous_revision(self):
        item = self.copy_scheme()
        from contract_web.settings import Settings
        # Emulate an editor that read its revision just before the delete commits.
        settings = Settings(self.store,self.root/'skills')
        user = self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        self.assertEqual(self.delete_scheme(item).status_code,200)
        with patch.object(settings,'item',return_value=item):
            with self.assertRaises(HTTPException) as error:
                settings.save_item(user,'risk',{'revision':item['revision'],'content':item['content']},item['id'])
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.store.one('SELECT deleted FROM config_items WHERE id=?',(item['id'],))['deleted'],1)

    def test_seed_personal_scheme_isolation_and_immutable_report(self):
        org = self.client.get('/api/risk-schemes').json()[0]
        self.assertEqual(org['content']['rules'][0]['id'],'TEST-1')
        self.assertTrue(org['editable'])
        copy = self.client.post('/api/risk-schemes/'+org['id']+'/copy',json={},headers=self.headers).json()
        content = {**copy['content'],'label':'我的付款方案','rules':[{'id':'PERSONAL-1','name':'个人付款点','category':'付款','baseline':'30 天内付款','enabled':True}]}
        saved = self.client.put('/api/risk-schemes/'+copy['id'],json={'revision':copy['revision'],'content':content},headers=self.headers).json()
        self.assertEqual(self.client.put('/api/risk-schemes/selection',json={'id':copy['id']},headers=self.headers).status_code,200)
        w,t = self.make_workspace()
        self.assertEqual(self.send(t).status_code,202)
        self.read_all(w,t)
        body,mapped = self.report(w)
        body.update(kind='review',content='PERSONAL-1：合同约定验收后30日付款。'+mapped['segments'][3]['citation'],findings=[{'risk_id':'PERSONAL-1','verdict':'未命中','reason':'已约定付款期限。','evidence':[{'document_id':w['document_id'],'source_hash':mapped['source_hash'],'block_id':'B3','quote':'验收后 30 日付款。'}]}])
        changed = {**saved['content'],'rules':[{'id':'PERSONAL-2','name':'新版不同风险点','enabled':True}]}
        response = self.client.put('/api/risk-schemes/'+copy['id'],json={'revision':saved['revision'],'content':changed},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        published = self.publish(t,body)
        self.assertEqual(published.status_code,200,published.text)
        report = self.client.get('/api/artifacts/'+published.json()['artifact_id']).json()
        self.assertEqual(report['findings'][0]['risk_name'],'个人付款点')
        self.assertEqual(report['execution_config']['risk_scheme']['revision'],saved['revision'])
        self.assertEqual(report['execution_config']['risk_scheme']['rules'][0]['id'],'PERSONAL-1')
        self.finish(t)
        self.assertEqual(self.send(t).status_code,202)
        path=self.store.user_root(self.uid)/'threads'/t['id']/'risk-library.json'
        self.assertEqual(json.loads(path.read_text())[0]['id'],'PERSONAL-2')
        self.assertEqual(self.client.get('/api/artifacts/'+published.json()['artifact_id']).json()['findings'][0]['risk_name'],'个人付款点')
        self.login('bob')
        self.assertEqual(self.client.get('/api/risk-schemes/'+copy['id']).status_code,404)
        self.assertEqual(self.client.get('/api/risk-schemes/options').json()['selected'],'public-risk-examples')
        self.assertEqual(self.client.get('/api/artifacts/'+published.json()['artifact_id']).status_code,404)

    def test_admin_default_validation_import_versions_and_extension_fields(self):
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.uid,))
        org=self.client.get('/api/risk-schemes').json()[0]
        content={**org['content'],'rules':[{**org['content']['rules'][0],'examples':{'hit':'例子'},'future_extension':{'keep':[1,2]}}]}
        r=self.client.put('/api/risk-schemes/'+org['id'],json={'revision':org['revision'],'content':content},headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        exported=self.client.get('/api/risk-schemes/'+org['id']+'/export').json()
        self.assertEqual(exported['content']['rules'][0]['future_extension'],{'keep':[1,2]})
        self.assertEqual(self.client.put('/api/risk-schemes/'+org['id'],json={'revision':1,'content':content},headers=self.headers).status_code,409)
        self.assertEqual(self.client.put('/api/risk-schemes/'+org['id'],json={'revision':2,'content':content,'enabled':False},headers=self.headers).status_code,422)
        self.assertEqual(len(self.client.get('/api/risk-schemes/'+org['id']+'/versions').json()),2)
        body,_=self.report(self.make_workspace()[0])
        self.login('bob')
        self.assertEqual(self.client.post('/api/risk-schemes/'+org['id']+'/default',json={'revision':1},headers=self.headers).status_code,403)


for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(RiskSettingsTests):
        setattr(RiskSettingsTests,_name,None)
