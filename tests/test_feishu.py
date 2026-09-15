import asyncio
import json
import os
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

import test_workbench as fixtures
from contract_web.feishu import CALLBACK, OAUTH_COOKIE, SCOPES, command
from fastapi import HTTPException


class FeishuTests(fixtures.WorkbenchTests):
    def setUp(self):
        self.feature = patch.dict(os.environ, {'CW_FEISHU_ENABLED': '1', 'CW_CONNECTOR_ORIGIN': 'http://127.0.0.1:8842'})
        self.feature.start()
        super().setUp()
        self.f = self.app.state.feishu

    def tearDown(self):
        super().tearDown()
        self.feature.stop()

    def configure(self):
        return self.client.put('/api/connectors/feishu', json={'app_id': 'cli_test123', 'app_secret': 'PRIVATE_FEISHU_SECRET', 'revision': 0}, headers=self.headers)

    def connect(self):
        self.configure()
        r = self.f.row(self.uid)
        self.f.store_tokens(self.uid, r['revision'], {'access_token': 'PRIVATE_FEISHU_UAT', 'refresh_token': 'PRIVATE_REFRESH', 'expires_in': 7200, 'refresh_token_expires_in': 60000, 'scope': ' '.join(SCOPES)}, {'name': '测试用户', 'open_id': 'ou_test'})

    def test_configuration_is_encrypted_isolated_and_versioned(self):
        result = self.configure()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn('PRIVATE_FEISHU_SECRET', result.text)
        self.assertNotIn('PRIVATE_FEISHU_SECRET', self.f.row(self.uid)['secret'])
        self.assertEqual(result.json()['status'], 'configured')
        self.assertEqual(self.configure().status_code, 409)
        self.login('bob')
        self.assertFalse(self.client.get('/api/connectors/feishu').json()['secret_configured'])

    def test_oauth_state_pkce_browser_binding_and_replay(self):
        self.configure()
        auth = self.client.post('/api/connectors/feishu/authorize', json={}, headers=self.headers)
        query = parse_qs(urlsplit(auth.json()['authorization_url']).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(set(query['scope'][0].split()), set(SCOPES))
        self.assertNotIn('PRIVATE_FEISHU_SECRET', auth.text)
        state = query['state'][0]
        callback = CALLBACK + '?state=' + state + '&code=test-code'
        browser = self.client.cookies.get(OAUTH_COOKIE)
        self.client.cookies.delete(OAUTH_COOKIE)
        self.assertEqual(self.client.get(callback).status_code, 400)
        self.client.cookies.set(OAUTH_COOKIE, browser, path=CALLBACK)
        token = {'access_token': 'PRIVATE_FEISHU_UAT', 'expires_in': 3600, 'scope': 'docx:document:readonly'}
        with patch.object(self.f, 'request', AsyncMock(return_value=token)) as exchange, patch.object(self.f, 'identity', AsyncMock(return_value={'name': '测试', 'open_id': 'ou_test'})):
            result = self.client.get(callback, follow_redirects=False)
            self.assertEqual(result.status_code, 303, result.text)
            self.assertIn('feishu=connected', result.headers['location'])
            self.assertIn('code_verifier', exchange.call_args.kwargs['data'])
            self.assertEqual(self.client.get(callback).status_code, 400)
        public = self.client.get('/api/connectors/feishu')
        self.assertNotIn('PRIVATE_FEISHU_UAT', public.text)
        self.assertEqual(public.json()['granted_scopes'], ['docx:document:readonly'])

    def test_oauth_rejects_logged_out_session_and_config_changes(self):
        self.configure()
        auth = self.client.post('/api/connectors/feishu/authorize', json={}, headers=self.headers).json()
        state = parse_qs(urlsplit(auth['authorization_url']).query)['state'][0]
        self.client.post('/api/logout', headers=self.headers)
        self.assertEqual(self.client.get(CALLBACK+'?state='+state+'&code=x').status_code, 400)

    def test_cancelled_oauth_returns_actionable_page(self):
        self.configure()
        auth = self.client.post('/api/connectors/feishu/authorize', json={}, headers=self.headers).json()
        state = parse_qs(urlsplit(auth['authorization_url']).query)['state'][0]
        result = self.client.get(CALLBACK+'?state='+state+'&error=access_denied', follow_redirects=False)
        self.assertEqual(result.headers['location'], '/connectors?feishu=denied')
        self.assertEqual(self.f.public(self.uid)['status'], 'configured')

    def test_refresh_rotates_once_for_concurrent_reads_and_retains_on_network_error(self):
        self.connect()
        row = self.f.row(self.uid)
        tokens = json.loads(self.app.state.models.decrypt(row['tokens']))
        tokens['expires_at'] = 0
        self.store.execute('UPDATE feishu_connections SET tokens=? WHERE user_id=?', (self.app.state.models.encrypt(json.dumps(tokens)), self.uid))
        async def refresh():
            with patch.object(self.f, 'request', AsyncMock(return_value={'access_token': 'rotated', 'refresh_token': 'new-refresh', 'expires_in': 7200, 'refresh_token_expires_in': 9000, 'scope': ' '.join(SCOPES)})) as request:
                values = await asyncio.gather(self.f.access(self.uid), self.f.access(self.uid))
                self.assertEqual(request.call_count, 1)
                self.assertEqual([v[1] for v in values], ['rotated', 'rotated'])
        asyncio.run(refresh())
        tokens['expires_at'] = 0
        self.store.execute('UPDATE feishu_connections SET tokens=? WHERE user_id=?', (self.app.state.models.encrypt(json.dumps(tokens)), self.uid))
        with patch.object(self.f, 'request', AsyncMock(side_effect=HTTPException(503, '网络故障'))):
            with self.assertRaises(HTTPException):
                asyncio.run(self.f.access(self.uid))
        self.assertEqual(self.f.row(self.uid)['status'], 'connected')

    def test_command_boundary_and_source_receipt(self):
        self.connect()
        for args in [{'url': 'https://evil.test/docx/abc'}, {'url': 'http://127.0.0.1/docx/abc'}, {'url': 'https://x.feishu.cn.evil.test/docx/abc'}, {'url': 'https://x.feishu.cn/docx/abc', 'shell': 'rm -rf /'}]:
            with self.assertRaises(ValueError):
                command('read_document', args)
        with self.assertRaises(ValueError):
            command('send_message', {})
        self.assertEqual(command('search_documents', {'query': '渠道政策'})[-4:], ['--as', 'user', '--format', 'json'])
        with patch.object(self.f, 'run_cli', AsyncMock(return_value={'document': {'revision_id': 2, 'content': '<p id="b1">政策内容</p>'}})):
            result = self.client.post('/api/connectors/feishu/read', json={'name': 'read_document', 'arguments': {'url': 'https://example.feishu.cn/docx/abc', 'scope': 'full'}}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['data']['document']['revision_id'], 2)
        self.assertEqual(result.json()['scope'], 'full')

    def test_native_mcp_and_disconnect_revokes_existing_capability(self):
        self.connect()
        w, t = self.make_workspace()
        rt = AsyncMock()
        rt.config = {'local': True}
        rt.call.return_value = {'feishu': {'status': 'connected'}}
        u = self.store.one('SELECT * FROM users WHERE id=?', (self.uid,))
        asyncio.run(self.f.attach(u, t, rt))
        config = rt.call.call_args.kwargs['body']['config']
        self.assertNotIn('PRIVATE_FEISHU', json.dumps(config))
        headers = config['headers']
        endpoint = '/internal/connectors/feishu/mcp'
        result = self.client.post(endpoint, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()['result']['tools']), 2)
        with patch.object(self.f, 'run_cli', AsyncMock(return_value={'items': []})):
            result = self.client.post(endpoint, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'search_documents', 'arguments': {'query': '政策'}}}, headers=headers)
        self.assertFalse(result.json()['result'].get('isError', False))
        self.client.delete('/api/connectors/feishu', headers=self.headers)
        self.assertEqual(self.client.post(endpoint, json={}, headers=headers).status_code, 401)
        row = self.f.row(self.uid)
        self.f.store_tokens(self.uid, row['revision'], {'access_token': 'new', 'expires_in': 3600})
        self.assertEqual(self.client.post(endpoint, json={}, headers=headers).status_code, 401)

    def test_cli_uses_account_credentials_without_inheriting_desktop_auth(self):
        self.connect()
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b'{"ok":true,"data":{"items":[]}}', b'')
        with patch.dict(os.environ, {'LARKSUITE_CLI_APP_SECRET': 'OTHER_USER_SECRET', 'LARKSUITE_CLI_AUTH_PROXY': 'http://other', 'OPENCLAW_HOME': '/other'}), patch('contract_web.feishu.cli_path', return_value='/bin/lark-cli'), patch('asyncio.create_subprocess_exec', AsyncMock(return_value=proc)) as spawn:
            asyncio.run(self.f.execute(self.uid, 'search_documents', {'query': 'test'}))
        env = spawn.call_args.kwargs['env']
        self.assertEqual(env['LARKSUITE_CLI_USER_ACCESS_TOKEN'], 'PRIVATE_FEISHU_UAT')
        self.assertNotIn('LARKSUITE_CLI_APP_SECRET', env)
        self.assertNotIn('LARKSUITE_CLI_AUTH_PROXY', env)
        self.assertNotIn('OPENCLAW_HOME', env)
        self.assertNotIn('PRIVATE_FEISHU_UAT', str(spawn.call_args.args))

    def test_disabled_feature_and_csrf(self):
        self.assertEqual(self.client.post('/api/connectors/feishu/authorize', json={}).status_code, 403)
        with patch.dict(os.environ, {'CW_FEISHU_ENABLED': '0'}):
            self.assertEqual(self.client.get('/api/connectors/feishu').status_code, 404)
        self.assertEqual(self.client.get('/connectors').status_code, 200)

    def test_cli_managed_identity_is_verified_and_can_disconnect(self):
        self.store.execute("INSERT INTO feishu_connections(user_id,app_id,secret,mode,updated) VALUES(?,'cli_native','','cli',?)", (self.uid, time.time()))
        evidence = {'appId': 'cli_native', 'identity': 'user', 'verified': True,
                    'identities': {'user': {'openId': 'ou_native', 'userName': '原生用户', 'scope': 'docx:document:readonly'}}}
        with patch.object(self.f.quick, 'command', AsyncMock(return_value=evidence)):
            result = self.client.post('/api/connectors/feishu/test', json={}, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['status'], 'connected')
            self.assertEqual(result.json()['identity']['name'], '原生用户')
            self.assertFalse(result.json()['secret_configured'])
            self.assertTrue(result.json()['app_configured'])
            self.assertNotIn('managed_by', result.text)
            self.assertEqual(self.client.post('/api/connectors/feishu/authorize', json={}, headers=self.headers).status_code, 422)
            self.assertEqual(self.client.delete('/api/connectors/feishu', headers=self.headers).status_code, 200)
        self.assertEqual(self.f.public(self.uid)['status'], 'configured')

    def test_native_verification_rejects_wrong_app_and_failed_user(self):
        self.store.execute("INSERT INTO feishu_connections(user_id,app_id,secret,mode,updated) VALUES(?,'cli_native','','cli',?)", (self.uid, time.time()))
        for evidence in ({'appId': 'cli_other', 'identity': 'user', 'verified': True, 'identities': {'user': {'openId': 'ou_x'}}},
                         {'appId': 'cli_native', 'identity': 'bot', 'verified': True}):
            with patch.object(self.f.quick, 'command', AsyncMock(return_value=evidence)):
                self.assertEqual(self.client.post('/api/connectors/feishu/test', json={}, headers=self.headers).status_code, 401)
        self.assertEqual(self.f.public(self.uid)['status'], 'configured')

    def test_quick_setup_resumes_saved_app_without_recreating_it(self):
        from contract_web.feishu_quick import cli_environment
        root, env = cli_environment(self.store, self.uid)
        (root/'config.json').write_text('{}')
        async def scenario():
            with patch.object(self.f.quick, 'command', AsyncMock(return_value={'appId': 'cli_saved'})) as command, patch.object(self.f.quick, 'verify', AsyncMock()):
                self.f.quick.start(self.uid)
                first = self.f.quick.jobs[self.uid]['task']
                self.f.quick.start(self.uid)
                self.assertIs(first, self.f.quick.jobs[self.uid]['task'])
                await first
                self.assertEqual(self.f.quick.public(self.uid)['step'], 'done')
                self.assertFalse(any('init' in c.args[1] for c in command.call_args_list))
                from contract_web.feishu import requested_scopes
                login = next(c.args[1] for c in command.call_args_list if c.args[1][:2] == ['auth', 'login'])
                self.assertEqual(login[login.index('--scope')+1].split(), requested_scopes())
                self.assertEqual(self.f.row(self.uid)['mode'], 'cli')
        for transport in ('mcp', 'direct_cli'):
            with self.subTest(transport=transport), patch.dict(os.environ, {'CW_FEISHU_TRANSPORT': transport}):
                asyncio.run(scenario())
        self.assertNotIn('LARKSUITE_CLI_USER_ACCESS_TOKEN', env)

    def test_quick_url_parser_preserves_official_url_only(self):
        from contract_web.feishu_quick import verification_url
        url = 'https://accounts.feishu.cn/device?x=a%2Fb&y=one+two'
        self.assertEqual(verification_url(json.dumps({'verification_uri_complete': url})), url)
        self.assertEqual(verification_url('  '+url+'\n'), url)
        for line in ('https://feishu.cn.evil.com/device', 'https://a@accounts.feishu.cn/device', '{"device_code":"PRIVATE"}', 'ordinary log line'):
            self.assertIsNone(verification_url(line))

    def test_https_origin_and_lark_authorization_are_account_scoped(self):
        from contract_web.feishu import origin
        from contract_web.feishu_quick import cli_environment, verification_url
        with patch.dict(os.environ, {'CW_CONNECTOR_ORIGIN':'https://openharvey.com'}):
            self.assertEqual(origin(),'https://openharvey.com')
            self.assertEqual(self.f.public(self.uid)['redirect_uri'],'https://openharvey.com'+CALLBACK)
            self.assertFalse(self.f.public(self.uid)['local_preview'])
        for value in ('http://example.com','https://user@example.com','https://example.com/path'):
            with patch.dict(os.environ, {'CW_CONNECTOR_ORIGIN':value}), self.assertRaises(ValueError):origin()
        url='https://accounts.larksuite.com/device?x=a%2Fb'
        self.assertEqual(verification_url(url),url)
        self.assertIsNone(verification_url('https://accounts.larksuite.com.evil.com/device'))
        async def scenario():
            with patch.object(self.f.quick,'run',AsyncMock()):
                self.f.quick.start(self.uid,'lark')
                await self.f.quick.jobs[self.uid]['task']
            self.assertEqual(cli_environment(self.store,self.uid)[1]['LARKSUITE_CLI_BRAND'],'lark')
            self.assertEqual(self.f.public(self.uid)['brand'],'lark')
            with self.assertRaises(HTTPException): self.f.quick.start(self.uid,'feishu')
            with self.assertRaises(HTTPException): self.f.quick.start(self.uid,'evil')
        asyncio.run(scenario())

    def test_quick_timeout_stops_launcher_and_child_process(self):
        import sys
        started = time.monotonic()
        script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); time.sleep(20)"
        with patch('contract_web.feishu.cli_path', return_value=sys.executable):
            with self.assertRaises(TimeoutError):
                asyncio.run(self.f.quick.command(self.uid, ['-c', script], timeout=0.15))
        self.assertLess(time.monotonic()-started, 2)


for _name in list(vars(fixtures.WorkbenchTests)):
    if _name.startswith('test_') and _name not in vars(FeishuTests):
        setattr(FeishuTests, _name, None)
