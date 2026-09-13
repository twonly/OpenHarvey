#!/usr/bin/env python3
"""Generate a static Compose deployment for existing accounts; never run Docker."""
import argparse
import json
import os
import secrets
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract_web.store import Store
from contract_web.cli import runtime_config


def generate(data, output, provider, *, uid=1000, gid=1000, port=8080):
    if uid == 0:
        raise ValueError("请指定非 root 的容器 UID")
    model_env = {}
    for value in provider.get("provider", {}).values():
        key = value.get("options", {}).get("apiKey", "")
        match = re.fullmatch(r"\{env:(CW_[A-Z0-9_]+)\}", key)
        if key and not match:
            raise ValueError("apiKey 必须使用 {env:CW_...} 引用，不能包含明文密钥")
        if match:
            name = match[1]
            model_env[name] = "${" + name + ":?请设置对应模型 API 密钥}"
    store = Store(data)
    users = store.all("SELECT id,username FROM users WHERE active=1 ORDER BY username")
    if not users:
        raise ValueError("请先使用 add-user 创建账号")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    configs_path = store.root/"runtimes.json"
    previous = json.loads(configs_path.read_text()) if configs_path.exists() else {}
    configs, networks = {}, {"front": {}}
    security = {"user": f"{uid}:{gid}", "read_only": True, "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"], "tmpfs": ["/tmp"],
                "restart": "unless-stopped", "pids_limit": 256}
    services = {"web": {**security, "build": {"context": str(ROOT), "dockerfile": "deploy/Dockerfile.web"},
                "ports": [f"127.0.0.1:{port}:8080"], "volumes": [f"{store.root}:/data"],
                "environment": {"CW_DATA_DIR": "/data", "CW_SANDBOX_BACKEND": "local", "CW_SECURE_COOKIE": "${CW_SECURE_COOKIE:-1}",
                                "CW_PUBLIC_ORIGIN": "${CW_PUBLIC_ORIGIN:?请设置实际 HTTPS 访问源地址}"},
                "networks": ["front"],
                "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"], "interval": "30s", "timeout": "5s", "retries": 3}}}
    for u in users:
        name = "agent-"+u["username"]
        net = "user-"+u["id"]
        networks[net] = {}
        services["web"]["networks"].append(net)
        root = store.user_root(u["id"])
        for child in ("sources", "threads", "published", "opencode"):
            (root/child).mkdir(parents=True, exist_ok=True)
        secret = previous.get(u["username"], {}).get("password") or secrets.token_urlsafe(32)
        configs[u["username"]] = {"url": f"http://{name}:4096", "password": secret,
            "work_root": "/work", "source_root": "/sources", "skill_root": "/opt/contract",
            "save_url": "http://web:8080/internal/artifacts"}
        cfg = runtime_config(Path("/opt/contract"))
        cfg.update({k: provider[k] for k in ("model", "small_model", "provider", "enabled_providers") if k in provider})
        conf = output/(name+".json")
        conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        conf.chmod(0o644)  # Contains env references, never model key values.
        env_file = output/(name+".env")
        env_file.write_text("OPENCODE_SERVER_PASSWORD="+secret+"\n")
        env_file.chmod(0o600)
        services[name] = {**security,
            "build": {"context": str(ROOT), "dockerfile": "deploy/Dockerfile.runtime"},
            "volumes": [f"{root/'sources'}:/sources:ro", f"{root/'threads'}:/work", f"{root/'opencode'}:/state",
                        f"{ROOT/'runtime'}:/opt/contract:ro", f"{conf}:/run/opencode.json:ro"],
            "env_file": [str(env_file)], "environment": model_env,
            "networks": [net]}
    configs_path.write_text(json.dumps(configs, indent=2))
    configs_path.chmod(0o600)
    compose = output/"compose.yaml"
    compose.write_text(yaml.safe_dump({"name": "contract-workbench", "services": services, "networks": networks}, allow_unicode=True, sort_keys=False))
    return compose


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data",type=Path,required=True)
    p.add_argument("--provider-config",type=Path,required=True)
    p.add_argument("--output",type=Path,default=ROOT/"deploy/generated")
    p.add_argument("--uid",type=int,default=os.getuid() or 1000)
    p.add_argument("--gid",type=int,default=os.getgid() or 1000)
    p.add_argument("--port",type=int,default=8080)
    a=p.parse_args()
    provider=json.loads(a.provider_config.read_text())
    # Refuse to make a world-readable runtime config containing a literal key.
    for value in provider.get("provider",{}).values():
        key=value.get("options",{}).get("apiKey","")
        if key and not key.startswith("{env:"):
            p.error("provider 配置中的 apiKey 必须使用 {env:CW_MODEL_API_KEY}，不要写入明文密钥")
    result=generate(a.data,a.output,provider,uid=a.uid,gid=a.gid,port=a.port)
    print(f"已生成 {result}；请确认数据目录可由 UID {a.uid} / GID {a.gid} 读写")
