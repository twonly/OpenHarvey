"""Product metadata only. OpenCode owns messages, tools, todos and execution."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .settings import migrate
from .session_policy import session_seconds


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ":" + value.hex()


def password_matches(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(":")[0]), encoded)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "app.sqlite"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS logins (
                  token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                  expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS workspaces (
                  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                  document_id TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS threads (
                  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                  session_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                  save_token TEXT UNIQUE NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                  workspace_id TEXT NOT NULL, thread_id TEXT,
                  filename TEXT NOT NULL, suffix TEXT NOT NULL, source_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                  kind TEXT NOT NULL, title TEXT NOT NULL, content_hash TEXT NOT NULL,
                  source_hash TEXT NOT NULL, created REAL NOT NULL,
                  UNIQUE(thread_id, kind, content_hash));
                CREATE TABLE IF NOT EXISTS risk_feedback (
                  artifact_id TEXT NOT NULL REFERENCES artifacts(id), risk_id TEXT NOT NULL,
                  user_id TEXT NOT NULL REFERENCES users(id), source_hash TEXT NOT NULL,
                  decision TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL,
                  revision INTEGER NOT NULL, PRIMARY KEY(artifact_id,risk_id,revision));
            """)
            if "model" not in {r[1] for r in db.execute("PRAGMA table_info(users)")}:
                db.execute("ALTER TABLE users ADD COLUMN model TEXT")
            workspace_columns = {r[1] for r in db.execute("PRAGMA table_info(workspaces)")}
            if "starred" not in workspace_columns:
                db.execute("ALTER TABLE workspaces ADD COLUMN starred INTEGER NOT NULL DEFAULT 0")
            if "deleted_at" not in workspace_columns:
                db.execute("ALTER TABLE workspaces ADD COLUMN deleted_at REAL")
            if "last_activity_at" not in workspace_columns:
                db.execute("ALTER TABLE workspaces ADD COLUMN last_activity_at REAL NOT NULL DEFAULT 0")
            if "purging_at" not in workspace_columns:
                db.execute("ALTER TABLE workspaces ADD COLUMN purging_at REAL")
            if "purge_error" not in workspace_columns:
                db.execute("ALTER TABLE workspaces ADD COLUMN purge_error TEXT")
            db.execute("""
                UPDATE workspaces SET last_activity_at=MAX(
                  created,
                  COALESCE((SELECT MAX(created) FROM threads WHERE workspace_id=workspaces.id),created),
                  COALESCE((SELECT MAX(created) FROM artifacts WHERE workspace_id=workspaces.id),created)
                ) WHERE last_activity_at=0
            """)
            if "permission_mode" not in {r[1] for r in db.execute("PRAGMA table_info(threads)")}:
                db.execute("ALTER TABLE threads ADD COLUMN permission_mode TEXT NOT NULL DEFAULT 'auto'")

            columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
            if "position" not in columns:
                db.execute("ALTER TABLE threads ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
                rows = db.execute("SELECT id FROM threads ORDER BY workspace_id,created,id").fetchall()
                db.executemany("UPDATE threads SET position=? WHERE id=?", [(i, row["id"]) for i, row in enumerate(rows)])
            for column in ("archived_at", "deleted_at"):
                if column not in columns:
                    db.execute(f"ALTER TABLE threads ADD COLUMN {column} REAL")

            if "model" not in columns:
                db.execute("ALTER TABLE threads ADD COLUMN model TEXT")

            for column in ('custom_title','seen_completion','dismissed_todos'):
                if column not in {r[1] for r in db.execute('PRAGMA table_info(threads)')}:
                    db.execute(f'ALTER TABLE threads ADD COLUMN {column} TEXT')
                    if column=='seen_completion' and db.execute("SELECT 1 FROM sqlite_master WHERE name='queued_messages'").fetchone():
                        db.execute("UPDATE threads SET seen_completion=(SELECT id FROM queued_messages WHERE thread_id=threads.id AND status='completed' ORDER BY seq DESC LIMIT 1)")
            migrate(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def user_root(self, uid):
        return self.root / "users" / uid

    def add_user(self, username, password):
        import re
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", username):
            raise ValueError("用户名须为 2–32 位小写字母、数字、下划线或短横线")
        if len(password) < 8:
            raise ValueError("密码至少需要 8 个字符")
        uid = secrets.token_hex(12)
        self.execute("INSERT INTO users(id,username,password) VALUES(?,?,?)",
                     (uid, username, password_hash(password)))
        for name in ("sources", "threads", "published"):
            (self.user_root(uid) / name).mkdir(parents=True, exist_ok=True)
        return uid

    def login(self, username, password):
        user = self.one("SELECT * FROM users WHERE username=? AND active=1", (username,))
        # Also run the password KDF for nonexistent accounts.
        encoded = user["password"] if user else password_hash("unavailable-account", "00" * 16)
        if not password_matches(password, encoded) or not user:
            return None
        token = secrets.token_urlsafe(32)
        self.execute("DELETE FROM logins WHERE expires < ?", (time.time(),))
        self.execute("INSERT INTO logins VALUES(?,?,?)", (digest(token), user["id"], time.time()+session_seconds()))
        return token

    def authenticate(self, token):
        return self.one("SELECT u.id,u.username,u.model,u.org_id,u.role,u.account_kind,u.expires_at,u.auth_subject FROM users u JOIN logins l ON l.user_id=u.id "
                        "WHERE l.token=? AND l.expires>? AND u.active=1 AND (u.expires_at IS NULL OR u.expires_at>?)", (digest(token), time.time(), time.time()))

    def login_failure_reason(self, token):
        if not token:return 'cookie_missing'
        row=self.one("SELECT l.expires,u.active,u.expires_at FROM logins l JOIN users u ON u.id=l.user_id WHERE l.token=?", (digest(token),))
        if not row:return 'credential_unknown_or_revoked'
        if not row['active']:return 'account_disabled'
        now=time.time()
        if row['expires_at'] is not None and row['expires_at']<=now:return 'account_expired'
        if row['expires']<=now:return 'login_expired'
        return 'state_changed'

    def renew_login(self, token):
        # Never resurrect expired/revoked sessions or extend demo account lifetime.
        now = time.time()
        row = self.one("SELECT l.expires,u.expires_at FROM logins l JOIN users u ON u.id=l.user_id WHERE l.token=? AND l.expires>? AND u.active=1 AND (u.expires_at IS NULL OR u.expires_at>?)", (digest(token), now, now))
        if not row:return None
        expires = min(now + session_seconds(), row['expires_at'] or float('inf'))
        if expires - row['expires'] < min(3600, session_seconds() / 2):return None
        self.execute("UPDATE logins SET expires=? WHERE token=? AND expires>?", (expires, digest(token), now))
        return max(1, int(expires-now))

    def runtime(self, username):
        configs = json.loads((self.root / "runtimes.json").read_text())
        config = configs[username]
        if not config.get("url") or not config.get("password"):
            raise ValueError("运行时配置不完整")
        if sum(c.get("url") == config["url"] for c in configs.values()) != 1:
            raise ValueError("每个账号必须使用独立的 OpenCode 服务")
        return config
