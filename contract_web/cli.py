"""Admin-only provisioning. No account registration endpoint."""
import argparse
import getpass
import json
import os
import secrets
import subprocess
from pathlib import Path

from .store import Store

ROOT = Path(__file__).resolve().parents[1]


def runtime_config(shared):
    return {"$schema": "https://opencode.ai/config.json", "default_agent": "contract",
            "share": "disabled", "autoupdate": False, "snapshot": False,
            "plugin": [(shared / "plugins/request-params.js").as_uri(), (shared / "plugins/memory.js").as_uri()],
            "compaction": {"auto": True, "prune": False},
            "skills": {"paths": [str(shared / "skills")]},
            "agent": {"contract": {"mode": "primary", "description": "合同工作台助手",
                        "permission": {"question": "allow"},
                        "prompt": (ROOT / "runtime/agent.md").read_text()}},
            "permission": {"task": "deny", "webfetch": "allow", "websearch": "allow",
                           "bash": {"*": "ask", f"python3 {shared}/scripts/publish.py *": "allow"}}}


def main():
    parser = argparse.ArgumentParser(description="合同工作台账号与本地开发运行时")
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("CW_DATA_DIR", ROOT/"data")))
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-user")
    add.add_argument("username")
    add.add_argument("--password-env", help="从指定环境变量读取初始密码，否则交互输入")
    disable = sub.add_parser("disable-user")
    disable.add_argument("username")
    sub.add_parser("list-users")
    bootstrap = sub.add_parser("init-admin", help="指定默认组织首位管理员（只可初始化一次）")
    bootstrap.add_argument("username")
    local = sub.add_parser("local-runtime", help="仅用于单机开发，生产使用隔离容器")
    local.add_argument("username")
    local.add_argument("--port", type=int, default=4096)
    local.add_argument("--web-url", default="http://127.0.0.1:8080")
    local.add_argument("--provider-config", type=Path, required=True,
                       help="仅包含 OpenCode provider/model 配置的 JSON 文件；凭据建议使用环境变量引用")
    args = parser.parse_args()
    store = Store(args.data)
    if args.command == "add-user":
        password = os.environ[args.password_env] if args.password_env else getpass.getpass("初始密码（至少 8 位）：")
        uid = store.add_user(args.username, password)
        print(json.dumps({"username": args.username, "id": uid}))
    elif args.command == "init-admin":
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():
                raise ValueError("已有有效管理员，请在网页成员管理中调整角色")
            if not db.execute("UPDATE users SET role='admin' WHERE username=? AND active=1", (args.username,)).rowcount:
                raise ValueError("请指定已有的有效账号")
        print("首位管理员已初始化")
    elif args.command == "disable-user":
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE username=?", (args.username,)).fetchone()
            if row and row["active"] and row["role"] == "admin" and db.execute(
                    "SELECT COUNT(*) FROM users WHERE org_id=? AND active=1 AND role='admin'", (row["org_id"],)).fetchone()[0] <= 1:
                raise ValueError("必须保留至少一位有效管理员")
            db.execute("UPDATE users SET active=0 WHERE username=?", (args.username,))
            db.execute("DELETE FROM logins WHERE user_id IN (SELECT id FROM users WHERE username=?)", (args.username,))
        try:
            config = store.runtime(args.username)
            if config.get("local"):
                import asyncio
                from .runtime_manager import LocalProcessDriver
                asyncio.run(LocalProcessDriver().stop(config))
        except (FileNotFoundError, KeyError):
            pass
        print("账号已禁用，现有登录及保存凭据均不再有效")
    elif args.command == "list-users":
        print(json.dumps(store.all("SELECT id,username,active FROM users ORDER BY username"), ensure_ascii=False, indent=2))
    elif args.command == "local-runtime":
        user = store.one("SELECT * FROM users WHERE username=? AND active=1", (args.username,))
        if not user:
            raise ValueError("请先创建账号")
        root = store.user_root(user["id"])
        config_path = store.root / "runtimes.json"
        configs = json.loads(config_path.read_text()) if config_path.exists() else {}
        secret = configs.get(args.username, {}).get("password") or secrets.token_urlsafe(32)
        shared = (ROOT/"runtime").resolve()
        config = {"url": f"http://127.0.0.1:{args.port}", "password": secret,
                  "source_root": str(root/"sources"), "work_root": str(root/"threads"),
                  "skill_root": str(shared), "save_url": args.web_url.rstrip("/")+"/internal/artifacts", "local": True}
        if any(c["url"] == config["url"] for name, c in configs.items() if name != args.username):
            raise ValueError("端口已分配给其他用户")
        configs[args.username] = config
        config_path.write_text(json.dumps(configs, indent=2))
        config_path.chmod(0o600)
        oc = runtime_config(shared)
        provider = json.loads(args.provider_config.read_text())
        oc.update({k: provider[k] for k in ("model", "small_model", "provider", "enabled_providers") if k in provider})
        state = root/"opencode"
        state.mkdir(exist_ok=True)
        ocpath = state/"opencode.json"
        ocpath.write_text(json.dumps(oc, ensure_ascii=False, indent=2))
        ocpath.chmod(0o600)
        env = dict(os.environ)
        env.pop("OPENCODE_CONFIG_CONTENT", None)
        # Clean XDG directories avoid loading the operator's personal plugins and credentials.
        env.update({"XDG_CONFIG_HOME": str(state/"config"), "XDG_DATA_HOME": str(state/"data"),
                    "XDG_STATE_HOME": str(state/"state"), "XDG_CACHE_HOME": str(state/"cache"),
                    "OPENCODE_CONFIG": str(ocpath),
                    "OPENCODE_SERVER_PASSWORD": secret, "OPENCODE_DISABLE_CLAUDE_CODE": "true",
                    "OPENCODE_ENABLE_QUESTION_TOOL": "true",
                    "OPENCODE_ENABLE_EXA": "true", "OPENCODE_WEBSEARCH_PROVIDER": "exa",
                    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true"})
        print(f"启动 {args.username} 的本地开发运行时，端口 {args.port}；此模式不提供容器级隔离", flush=True)
        subprocess.run(["opencode", "serve", "--pure", "--hostname", "127.0.0.1", "--port", str(args.port)],
                       cwd=root/"threads", env=env, check=True)


if __name__ == "__main__":
    main()
