import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import test_workbench as fixtures
from contract_web.store import Store


class WorkspaceManagementTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace
    native = fixtures.WorkbenchTests.native

    def manage(self, workspace, action, **body):
        return self.client.patch(f'/api/workspaces/{workspace["id"]}',
                                 json={"action": action, **body}, headers=self.headers)

    def test_list_counts_scope_sort_and_ownership(self):
        first, thread = self.make_workspace()
        second, _ = self.make_workspace("另一份合同")
        self.client.post(f'/api/workspaces/{first["id"]}/threads', json={}, headers=self.headers)
        self.client.post(f'/api/threads/{thread["id"]}/attachments', content=b'extra',
                         headers={**self.headers, 'X-Filename': 'extra.txt'})
        self.store.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',
                           ('artifact', first['id'], thread['id'], 'document', '成果', 'hash', 'source', time.time()))
        rows = self.client.get('/api/workspaces?scope=active').json()
        row = next(item for item in rows if item['id'] == first['id'])
        self.assertEqual((row['thread_count'], row['active_thread_count'], row['document_count'], row['artifact_count']), (2, 2, 2, 1))
        self.assertIn('last_activity_at', row)
        self.assertEqual(self.client.get('/api/workspaces?scope=bad').status_code, 422)
        self.assertEqual(self.manage(second, 'star').status_code, 200)
        self.assertEqual(self.client.get('/api/workspaces').json()[0]['id'], second['id'])
        self.login('bob')
        self.assertEqual(self.manage(first, 'star').status_code, 404)
        self.assertEqual(self.client.get('/api/workspaces?scope=all').json(), [])

    def test_star_rename_activity_and_audit(self):
        workspace, _ = self.make_workspace()
        before = self.store.one('SELECT last_activity_at FROM workspaces WHERE id=?', (workspace['id'],))['last_activity_at']
        result = self.manage(workspace, 'star').json()
        self.assertEqual(result['starred'], 1)
        self.assertEqual(self.manage(workspace, 'rename', title='  采购框架协议  ').status_code, 200)
        row = self.store.one('SELECT * FROM workspaces WHERE id=?', (workspace['id'],))
        self.assertEqual(row['title'], '采购框架协议')
        self.assertGreaterEqual(row['last_activity_at'], before)
        self.assertEqual(self.manage(workspace, 'rename', title='').status_code, 422)
        actions = {item['action'] for item in self.store.all('SELECT action FROM audit_log WHERE target=?', (workspace['id'],))}
        self.assertTrue({'workspace.star', 'workspace.rename'} <= actions)

    def test_soft_delete_blocks_active_access_preserves_and_restores(self):
        workspace, thread = self.make_workspace()
        source = self.store.user_root(self.uid) / 'sources' / workspace['document_id']
        self.assertEqual(self.manage(workspace, 'delete').status_code, 422)
        deleted = self.manage(workspace, 'delete', confirmed=True)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(source.exists())
        self.assertEqual(self.client.get(f'/api/workspaces/{workspace["id"]}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/threads/{thread["id"]}').status_code, 404)
        self.assertEqual(self.client.get('/api/workspaces').json(), [])
        self.assertEqual(self.client.get('/api/workspaces?scope=deleted').json()[0]['id'], workspace['id'])
        self.assertEqual(self.manage(workspace, 'rename', title='不可改').status_code, 409)
        self.assertEqual(self.manage(workspace, 'restore').status_code, 200)
        self.assertEqual(self.client.get(f'/api/threads/{thread["id"]}').status_code, 200)

    def test_delete_rejects_busy_pending_and_queued_work(self):
        workspace, thread = self.make_workspace()
        self.native(thread)['status'] = {'type': 'busy'}
        response = self.manage(workspace, 'delete', confirmed=True)
        self.assertEqual(response.status_code, 409)
        self.native(thread)['status'] = {'type': 'idle'}
        server = fixtures.FakeRuntime.servers['http://alice']
        server['requests']['question'] = [{'id': 'q', 'sessionID': thread['session_id']}]
        self.assertEqual(self.manage(workspace, 'delete', confirmed=True).status_code, 409)
        server['requests']['question'] = []
        user = self.store.one('SELECT * FROM users WHERE id=?', (self.uid,))
        self.app.state.queue.enqueue(user, thread['id'], {'text': 'pending'})
        self.assertEqual(self.manage(workspace, 'delete', confirmed=True).status_code, 409)

    def test_purge_is_retryable_and_removes_owned_data(self):
        workspace, thread = self.make_workspace()
        artifact = 'artifact-to-purge'
        self.store.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',
                           (artifact, workspace['id'], thread['id'], 'document', '成果', 'hash', 'source', time.time()))
        published = self.store.user_root(self.uid) / 'published' / artifact
        published.mkdir(); (published / 'content.txt').write_text('saved')
        self.assertEqual(self.manage(workspace, 'delete', confirmed=True).status_code, 200)
        self.assertEqual(self.manage(workspace, 'purge').status_code, 422)
        fixtures.FakeRuntime.servers['http://alice']['delete_fail'] = True
        failed = self.manage(workspace, 'purge', confirmed=True)
        self.assertEqual(failed.status_code, 503)
        row = self.store.one('SELECT * FROM workspaces WHERE id=?', (workspace['id'],))
        self.assertTrue(row['purging_at']); self.assertTrue(row['purge_error'])
        self.assertEqual(self.manage(workspace, 'restore').status_code, 409)
        completed = self.manage(workspace, 'purge', confirmed=True)
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertTrue(completed.json()['purged'])
        self.assertIsNone(self.store.one('SELECT * FROM workspaces WHERE id=?', (workspace['id'],)))
        self.assertIsNone(self.store.one('SELECT * FROM threads WHERE id=?', (thread['id'],)))
        self.assertIsNone(self.store.one('SELECT * FROM artifacts WHERE id=?', (artifact,)))
        self.assertFalse(published.exists())
        self.assertIsNotNone(self.store.one("SELECT * FROM audit_log WHERE action='workspace.purge' AND target=?", (workspace['id'],)))

    def test_legacy_workspace_migration_backfills_activity(self):
        with tempfile.TemporaryDirectory() as root:
            db = sqlite3.connect(Path(root) / 'app.sqlite')
            db.executescript('''
              CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE,password TEXT,active INTEGER DEFAULT 1);
              CREATE TABLE workspaces(id TEXT PRIMARY KEY,user_id TEXT,document_id TEXT,title TEXT,created REAL);
              CREATE TABLE threads(id TEXT PRIMARY KEY,workspace_id TEXT,session_id TEXT,title TEXT,save_token TEXT,created REAL);
              CREATE TABLE documents(id TEXT PRIMARY KEY,user_id TEXT,workspace_id TEXT,thread_id TEXT,filename TEXT,suffix TEXT,source_hash TEXT);
              CREATE TABLE artifacts(id TEXT PRIMARY KEY,workspace_id TEXT,thread_id TEXT,kind TEXT,title TEXT,content_hash TEXT,source_hash TEXT,created REAL,UNIQUE(thread_id,kind,content_hash));
              CREATE TABLE risk_feedback(artifact_id TEXT,risk_id TEXT,user_id TEXT,source_hash TEXT,decision TEXT,note TEXT,created REAL,revision INTEGER,PRIMARY KEY(artifact_id,risk_id,revision));
              INSERT INTO workspaces VALUES('w','u','d','旧合同',1);
              INSERT INTO threads VALUES('t','w','s','旧会话','token',5);
            ''')
            db.commit(); db.close()
            row = Store(root).one('SELECT * FROM workspaces WHERE id="w"')
            self.assertEqual(row['last_activity_at'], 5)
            self.assertEqual(row['starred'], 0)
            self.assertIsNone(row['deleted_at'])
