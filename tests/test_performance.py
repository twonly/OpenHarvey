import asyncio
import base64
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import test_workbench as fixtures
import test_e2b as cloud_fixtures
from contract_web.artifact_service import read_blocks
from contract_web.runtime import Runtime


class SaveAndPreviewTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace

    def test_health_responds_while_report_validation_waits_in_worker(self):
        w, t = self.make_workspace()
        token = (self.store.user_root(self.uid)/'threads'/t['id']/'.publish-token').read_text()
        mapped = self.client.get(f'/api/documents/{w["document_id"]}?thread_id={t["id"]}').json()
        entered, release, expired = threading.Event(), threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            if not release.wait(2):expired.set()
            return read_blocks(*args)
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://testserver') as client:
                saving = asyncio.create_task(client.post('/internal/artifacts', json={
                    'kind':'document','source_hash':mapped['source_hash'],'content':'保存的完整正文','format':'txt'},
                    headers={'Authorization':'Bearer '+token}))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    self.assertEqual((await client.get('/health')).status_code, 200)
                    self.assertFalse(expired.is_set(), 'validation blocked the HTTP event loop')
                    self.assertFalse(saving.done())
                finally:
                    release.set()
                result = await saving
                self.assertEqual(result.status_code, 200, result.text)
                self.assertTrue(result.json()['saved'])
                aid = result.json()['artifact_id']
                self.assertEqual((self.store.user_root(self.uid)/'published'/aid/'content.txt').read_text(), '保存的完整正文')
        with patch('contract_web.artifact_service.read_blocks', slow):asyncio.run(run())

    def test_batch_and_single_pages_share_cache_and_remain_owner_scoped(self):
        pdf = (Path(__file__).parent/'fixtures/text-contract.pdf').read_bytes()
        w = self.client.post('/api/workspaces', content=pdf, headers={**self.headers,'X-Filename':'contract.pdf'}).json()
        t = self.client.post(f'/api/workspaces/{w["id"]}/threads', json={}, headers=self.headers).json()
        path = f'/api/documents/{w["document_id"]}/pages'
        query = f'?thread_id={t["id"]}&start=1&count=1&width=960'
        first = self.client.get(path+query)
        self.assertEqual(first.status_code, 200, first.text)
        png = base64.b64decode(first.json()['pages'][0]['png'])
        with patch('contract_web.pdf_cache.render_pdf_pages', side_effect=AssertionError('cache missed')):
            self.assertEqual(self.client.get(path+'/1?thread_id='+t['id']).content, png)
            self.assertEqual(self.client.get(path+query).json(), first.json())
        self.assertEqual(self.client.get(path+query.replace('count=1','count=4')).status_code, 422)
        self.assertEqual(self.client.get(path+query.replace('start=1','start=2')).status_code, 404)
        self.login('bob')
        self.assertEqual(self.client.get(path+query).status_code, 404)


class BackgroundPerformanceTests(unittest.TestCase):
    setUp = cloud_fixtures.E2BTests.setUp
    tearDown = cloud_fixtures.E2BTests.tearDown
    login = cloud_fixtures.E2BTests.login
    make_workspace = cloud_fixtures.E2BTests.make_workspace
    send = cloud_fixtures.E2BTests.send
    run_async = cloud_fixtures.E2BTests.run_async
    current = cloud_fixtures.E2BTests.current
    sandbox = cloud_fixtures.E2BTests.sandbox
    finish = cloud_fixtures.E2BTests.finish

    def test_healthy_stream_skips_full_sync_but_recovery_and_completion_reconcile(self):
        w, t = self.make_workspace();self.send(t);t=self.current(t)
        ready = asyncio.Event();ready.set();self.cloud.stream_ready[t['id']]=ready
        self.run_async(self.cloud.collect_thread(self.u,t))
        with patch.object(Runtime,'call',wraps=None,side_effect=AssertionError('unnecessary full sync')):
            self.run_async(self.cloud.refresh_threads(self.u,[t]))
        self.cloud.last_collected[t['id']] = time.monotonic()-61
        with patch.object(self.cloud,'collect_thread', wraps=self.cloud.collect_thread) as collect:
            self.run_async(self.cloud.refresh_threads(self.u,[t]));self.assertEqual(collect.call_count,1)
            ready.clear();self.cloud.last_collected[t['id']]=time.monotonic()-6
            self.run_async(self.cloud.refresh_threads(self.u,[t]));self.assertEqual(collect.call_count,2)
            ready.set()
            self.cloud.ingest_event(self.u,t,{'type':'session.status','properties':{'sessionID':t['session_id'],'status':{'type':'idle'}}})
            self.run_async(self.cloud.refresh_threads(self.u,[t]));self.assertEqual(collect.call_count,3)

    def test_unchanged_snapshot_and_trace_do_not_write_again(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);t=self.current(t)
        before=self.store.one('SELECT * FROM e2b_history WHERE thread_id=?',(t['id'],))
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE performance_writes(kind TEXT);
                CREATE TRIGGER count_trace_update AFTER UPDATE ON trace_runs BEGIN INSERT INTO performance_writes VALUES('trace'); END;
                CREATE TRIGGER count_execution_update AFTER UPDATE ON execution_configs BEGIN INSERT INTO performance_writes VALUES('execution'); END;
                CREATE TRIGGER count_history_update AFTER UPDATE ON e2b_history BEGIN INSERT INTO performance_writes VALUES('history'); END;''')
        self.run_async(self.cloud.collect_thread(self.u,t))
        self.assertEqual(self.store.all('SELECT * FROM performance_writes'), [])
        self.assertEqual(self.store.one('SELECT * FROM e2b_history WHERE thread_id=?',(t['id'],)), before)

    def test_live_updates_during_collection_do_not_trigger_continuous_full_reads(self):
        w,t=self.make_workspace();self.send(t);t=self.current(t)
        ready=asyncio.Event();ready.set();self.cloud.stream_ready[t['id']]=ready
        original=self.cloud.save_snapshot
        def raced(u,thread,messages,snapshot,revision):
            self.cloud.ingest_event(u,thread,{'type':'session.status','properties':{'sessionID':thread['session_id'],'status':{'type':'busy'}}})
            return original(u,thread,messages,snapshot,revision)
        self.cloud.sync_requested.add(t['id'])
        with patch.object(self.cloud,'save_snapshot',side_effect=raced):
            self.run_async(self.cloud.collect_thread(self.u,t))
        with patch.object(Runtime,'call',side_effect=AssertionError('stream progress caused another full read')):
            self.run_async(self.cloud.refresh_threads(self.u,[t]))
        self.cloud.ingest_event(self.u,t,{'type':'message.part.updated','properties':{'part':{
            'id':'part_missing','messageID':'msg_missing','sessionID':t['session_id'],'type':'text','text':'Recovered later'}}})
        self.assertIn(t['id'],self.cloud.sync_requested)

    def test_sidebar_uses_snapshots_and_preserves_completion_failure_and_waits(self):
        w,t=self.make_workspace();result=self.send(t);self.finish(w,t);t=self.current(t)
        self.store.execute("UPDATE queued_messages SET status='completed' WHERE id=?",(result.json()['id'],))
        url=f'/api/workspaces/{w["id"]}/thread-status'
        with patch.object(self.cloud,'history',side_effect=AssertionError('sidebar fetched full history')):
            completed=self.client.get(url).json()[0]
            self.assertEqual(completed['activity'],'completed')
            self.store.execute('UPDATE threads SET seen_completion=? WHERE id=?',(completed['completion_id'],t['id']))
            self.assertEqual(self.client.get(url).json()[0]['activity'],'idle')
            self.cloud.ingest_event(self.u,t,{'type':'question.asked','properties':{'id':'q','sessionID':t['session_id'],'questions':[]}})
            self.assertEqual(self.client.get(url).json()[0]['activity'],'waiting')
            self.cloud.ingest_event(self.u,t,{'type':'question.replied','properties':{'sessionID':t['session_id'],'requestID':'q'}})
            last=self.cloud.snapshot(t['id'])['last_assistant']
            self.cloud.ingest_event(self.u,t,{'type':'message.updated','properties':{'info':{**last,'finish':'length'}}})
            self.assertEqual(self.client.get(url).json()[0]['activity'],'failed')
        self.login('bob');self.assertEqual(self.client.get(url).status_code,404)

    def test_legacy_sidebar_summary_is_derived_once(self):
        w,t=self.make_workspace();self.send(t);self.finish(w,t);t=self.current(t)
        self.cloud.live_history.pop(t['id'],None)
        self.store.execute("UPDATE e2b_history SET snapshot=json_remove(snapshot,'$.last_assistant') WHERE thread_id=?",(t['id'],))
        first=self.cloud.last_assistant(t['id'])
        with patch.object(self.cloud,'history',side_effect=AssertionError('legacy summary not saved')):
            self.assertEqual(self.cloud.last_assistant(t['id']), first)
