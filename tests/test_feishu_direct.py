"""Credential boundaries; no real Feishu identities or cloud writes."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from contract_web.feishu_direct import DirectFeishu,PATH
from contract_web.runtime import RuntimeError

spec=importlib.util.spec_from_file_location('feishu_launcher',Path(__file__).resolve().parents[1]/'runtime/scripts/feishu_cli.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class DirectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.row={'app_id':'cli_A','identity':json.dumps({'open_id':'ou_A'}),'mode':'cli','status':'connected','revision':3}
        self.lock=asyncio.Lock();self.u={'id':'A'};self.w={'id':'wa'}
        store=SimpleNamespace(root=Path(self.tmp.name),execute=lambda *a:None,all=lambda *a:[])
        self.f=SimpleNamespace(models=SimpleNamespace(encrypt=lambda x:'encrypted:'+x),store=store,lock=lambda uid:self.lock,row=lambda uid:self.row if uid=='A' else None)
        self.e=SimpleNamespace(store=store,assert_owned=AsyncMock(),binding=lambda wid:{'sandbox_id':'sA','generation':4},record=lambda *a:None,handles={})
        self.d=DirectFeishu(self.f,self.e)
        self.s=SimpleNamespace(sandbox_id='sA',commands=SimpleNamespace(run=AsyncMock()),files=SimpleNamespace(write=AsyncMock()))
        self.token={'app_id':'cli_A','open_id':'ou_A','access_token':'PRIVATE_UAT','expires_at':time.time()+7200,'revision':3,'scope':'docs:read'}
        self.env=patch.dict(os.environ,{'CW_FEISHU_ENABLED':'1','CW_FEISHU_TRANSPORT':'direct_cli'});self.env.start();self.addCleanup(self.env.stop)

    async def test_concurrent_refresh_shared_lock_and_cached_token(self):
        from contract_web.feishu import requested_scopes,SCOPES
        self.assertIn('base:record:update',requested_scopes())
        for scope in ('im:message.send_as_user','im:message','contact:user:search'):
            self.assertIn(scope,requested_scopes())
        self.assertNotIn('im:message:send_as_bot',requested_scopes())
        with patch.dict(os.environ,{'CW_FEISHU_TRANSPORT':'mcp'}):self.assertEqual(requested_scopes(),SCOPES)
        process=SimpleNamespace(returncode=0,communicate=AsyncMock(return_value=(json.dumps(self.token).encode(),b'')))
        with patch('contract_web.feishu_direct.Path.is_file',return_value=True),patch('contract_web.feishu_direct.asyncio.create_subprocess_exec',AsyncMock(return_value=process)) as spawn:
            a,b=await asyncio.gather(self.d.credential('A'),self.d.credential('A'))
            self.assertEqual(spawn.await_count,1);self.assertEqual(a,b)
            self.assertIsNone(await self.d.credential('B'))
            self.assertEqual(spawn.await_count,1)

    async def test_helper_identity_and_expiry_must_match(self):
        for change in ({'open_id':'ou_B'},{'expires_at':0}):
            process=SimpleNamespace(returncode=0,communicate=AsyncMock(return_value=(json.dumps(self.token|change).encode(),b'')))
            with patch('contract_web.feishu_direct.Path.is_file',return_value=True),patch('contract_web.feishu_direct.asyncio.create_subprocess_exec',AsyncMock(return_value=process)):
                with self.assertRaises(RuntimeError):await self.d.credential('A')
        self.assertEqual(self.d.cache,{})

    async def test_ownership_before_token_read(self):
        self.e.assert_owned.side_effect=RuntimeError('owner mismatch');self.d.credential=AsyncMock()
        with self.assertRaises(RuntimeError):await self.d.prepare({'id':'B'},self.w,self.s)
        self.d.credential.assert_not_awaited();self.s.files.write.assert_not_awaited()

    async def test_binding_and_generation_and_reuse(self):
        self.d.credential=AsyncMock(return_value=self.token)
        await self.d.prepare(self.u,self.w,self.s);await self.d.prepare(self.u,self.w,self.s)
        self.assertEqual(self.s.files.write.await_count,2)
        payload=json.loads(self.s.files.write.call_args.args[1]);self.assertEqual(payload['generation'],4)
        await self.d.prepare(self.u,self.w,self.s,force=True)
        self.assertEqual(self.s.files.write.await_count,3)
        self.s.sandbox_id='sB'
        with self.assertRaises(RuntimeError):await self.d.prepare(self.u,self.w,self.s)

    async def test_disconnect_revision_race_clears_without_injection(self):
        self.d.credential=AsyncMock(return_value=self.token)
        self.row['revision']=4
        await self.d.prepare(self.u,self.w,self.s)
        self.s.files.write.assert_not_awaited();self.assertEqual(self.d.status['wa']['state'],'not_ready')

    async def test_expiry_error_clears_file_and_disconnect_does_not_issue_token(self):
        self.d.credential=AsyncMock(side_effect=RuntimeError('reauthorize'))
        await self.d.prepare(self.u,self.w,self.s)
        self.assertIn('rm -f',self.s.commands.run.call_args.args[0]);self.assertEqual(self.d.status['wa']['state'],'failed')
        self.row['status']='configured';self.assertIsNone(await DirectFeishu(self.f,self.e).credential('A'))
        self.e.store.all=lambda *a:[{'id':'wa'}]
        self.e.owner=lambda wid:self.u
        self.e.handles={'wa':self.s};self.d.cache['A']=self.token
        await self.d.revoke('A')
        self.assertNotIn('A',self.d.cache);self.assertEqual(self.d.status['wa']['state'],'not_ready')
        self.e.assert_owned.assert_awaited();self.assertIn('rm -f',self.s.commands.run.call_args.args[0])

class LauncherTests(unittest.TestCase):
    def test_environment_user_only_no_inherited_app_secret(self):
        p={'app_id':'cli_A','access_token':'A_TOKEN','expires_at':1000}
        env=launcher.environment(p,{'PATH':'/bin','LARKSUITE_CLI_APP_SECRET':'DANGER','LARKSUITE_CLI_USER_ACCESS_TOKEN':'OTHER','OPENCLAW_HOME':'/other'},now=10)
        self.assertNotIn('LARKSUITE_CLI_APP_SECRET',env);self.assertNotIn('OPENCLAW_HOME',env)
        self.assertEqual(env['LARKSUITE_CLI_USER_ACCESS_TOKEN'],'A_TOKEN');self.assertEqual(env['LARKSUITE_CLI_STRICT_MODE'],'user')
        with self.assertRaises(ValueError):launcher.environment(p,{},now=999)

    def test_real_receipt_success_failure_and_uncertain_write_no_body(self):
        p={'revision':3,'sandbox_id':'s','generation':2}
        for code,data,outcome in ((0,{'ok':True,'data':{'document_id':'d','content':'private body'}},'success'),(1,{'error':{'message':'forbidden'}},'failed_or_uncertain'),(1,{},'failed_or_uncertain'),(0,{'code':99991400},'failed_or_uncertain')):
            r=launcher.make_receipt(['docs','+create'],data,code,12,p)
            self.assertEqual(launcher.make_receipt(['base','+record-upsert'],data,code,12,p)['kind'],'write');self.assertEqual(r['kind'],'write');self.assertEqual(r['outcome'],outcome);self.assertNotIn('private body',json.dumps(r))

class SandboxGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_metadata_blocks_pause_before_any_mutation(self):
        from contract_web.e2b_runtime import E2B
        e=E2B.__new__(E2B);e.deployment='local-test';e.owner=lambda wid:{'id':'A'}
        for metadata in ({'deployment':'production','user_id':'A','workspace_id':'wa'}, {'deployment':'local-test','user_id':'B','workspace_id':'wa'}, {'deployment':'local-test','user_id':'A','workspace_id':'wb'}):
            s=SimpleNamespace(get_info=AsyncMock(return_value=SimpleNamespace(metadata=metadata)),pause=AsyncMock())
            e.handles={'wa':s};e.state=lambda *a,**kw:self.fail('must check metadata before state mutation')
            with self.assertRaises(RuntimeError):await e.pause({'id':'A'},{'id':'wa'})
            s.pause.assert_not_awaited()

    async def test_inventory_filter_alone_cannot_authorize_destroy(self):
        from contract_web.e2b_runtime import E2B
        e=E2B.__new__(E2B);e.deployment='local-test';e.owner=lambda wid:{'id':'A'}
        info=SimpleNamespace(sandbox_id='stolen',metadata={'deployment':'production','user_id':'A','workspace_id':'wa'})
        pages=SimpleNamespace(next_items=AsyncMock(return_value=[info]),has_next=False)
        e.sandbox_class=SimpleNamespace(list=lambda **kw:pages,kill=AsyncMock(),connect=AsyncMock())
        e.binding=lambda wid:{'sandbox_id':'stolen'}
        with self.assertRaises(RuntimeError):await e.destroy({'id':'A'},{'id':'wa'})
        e.sandbox_class.kill.assert_not_awaited();e.sandbox_class.connect.assert_not_awaited()

class BootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_idempotent_startup_requests_retry_transport_errors(self):
        import httpx
        from contract_web.e2b_runtime import E2B
        from contract_web.runtime import Runtime
        e=E2B.__new__(E2B);events=[];e.record=lambda *a:events.append(a)
        failure=RuntimeError('connection');failure.__cause__=httpx.ReadError('closed')
        with patch.object(Runtime,'call',AsyncMock(side_effect=[failure,failure,True])) as call,patch('contract_web.e2b_runtime.asyncio.sleep',AsyncMock()):
            self.assertTrue(await e.bootstrap_request('wa',None,'PUT','/auth/test',{'type':'api','key':'SECRET'}))
            self.assertEqual(call.await_count,3);self.assertNotIn('SECRET',str(events))
        for method,path in [('POST','/session'),('POST','/session/a/prompt_async'),('POST','/permission/a/reply')]:
            with self.assertRaises(ValueError):await e.bootstrap_request('wa',None,method,path)
