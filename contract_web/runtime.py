"""Small OpenCode 1.16.2 HTTP adapter. No model client or agent loop."""
import json
import posixpath
import re
import asyncio
from pathlib import PurePosixPath

import yaml

import httpx
from .presentation import PublicView


class RuntimeError(Exception):
    pass


class Runtime:
    def __init__(self, config):
        self.config = config
        self.request_client = None

    def client(self, **kwargs):
        return httpx.AsyncClient(base_url=self.config["url"],
            auth=("opencode", self.config["password"]), trust_env=False,
            timeout=httpx.Timeout(30, read=45), headers=self.config.get("headers", {}), **kwargs)

    def directory(self, tid):
        return str(PurePosixPath(self.config["work_root"]) / tid)

    def source_path(self, docid):
        return str(PurePosixPath(self.config["source_root"]) / docid / "contract.md")

    async def call(self, method, path, *, tid=None, body=None, params=None, allow_not_found=False):
        query = dict(params or {})
        if tid:
            query["directory"] = self.directory(tid)
        try:
            if self.request_client is not None:
                response = await self.request_client.request(method, path, params=query, json=body)
            else:
                async with self.client() as client:
                    response = await client.request(method, path, params=query, json=body)
            if response.status_code == 404 and allow_not_found:
                return None
            if response.is_error:
                raise RuntimeError(f"OpenCode 请求失败（HTTP {response.status_code}），请重试或联系管理员")
            if not response.content:
                return None
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("OpenCode 暂时无法连接，请稍后重试；已保存的材料仍然保留") from exc

    async def permissions(self, tid, documents, mode="auto"):
        if mode=='full':raise RuntimeError('全权执行仅适用于云端隔离沙箱')
        # OpenCode matches read/edit against paths relative to its worktree;
        # for non-Git projects that worktree is often '/', not the session cwd.
        worktree = (await self.call("GET", "/path", tid=tid))["worktree"]
        relative = lambda path: posixpath.relpath(path, worktree)
        action = "ask" if mode == "cautious" else "allow"
        rules = [{"permission": "bash", "pattern": "*", "action": "ask"},
                 {"permission": "question", "pattern": "*", "action": "allow"},
                 {"permission": "read", "pattern": "*", "action": "deny"},
                 {"permission": "edit", "pattern": "*", "action": "deny"}]
        root = self.directory(tid)
        shared = self.config["skill_root"]
        # Models legitimately quote script paths. Keep all three spellings scoped
        # to the same save-only publisher, including already-running local servers.
        for quote in ("", "\"", "'"):
            rules.append({"permission": "bash", "pattern": f"python3 {quote}{shared}/scripts/publish.py{quote} *", "action": action})
        for path in [root + "/*", shared + "/*"] + [self.source_path(d["id"]).rsplit("/",1)[0]+"/*" for d in documents]:
            rules.append({"permission": "read", "pattern": relative(path), "action": "allow"})
        rules += [
            {"permission": "memory", "pattern": "*", "action": "allow"},
            {"permission": "read", "pattern": "*/.memory-capability", "action": "deny"},
            {"permission": "edit", "pattern": relative(root + "/.memory-capability"), "action": "deny"},
            {"permission": "read", "pattern": "*/.publish-token", "action": "deny"},
            {"permission": "edit", "pattern": relative(root + "/*"), "action": action},
            {"permission": "edit", "pattern": relative(root + "/context.json"), "action": "deny"},
            {"permission": "edit", "pattern": relative(root + "/risk-library.json"), "action": "deny"},
            {"permission": "edit", "pattern": relative(root + "/.publish-token"), "action": "deny"},
            *[{"permission": "edit", "pattern": relative(root + suffix), "action": "deny"}
              for suffix in ("/opencode.json", "/opencode.jsonc", "/.opencode/*", "/.skill-versions/*", "/.skill-versions.json")],
            {"permission": "external_directory", "pattern": "*", "action": "deny"},
        ]
        for path in [shared + "/*"] + [self.source_path(d["id"]).rsplit("/",1)[0]+"/*" for d in documents]:
            rules.append({"permission": "external_directory", "pattern": path, "action": "allow"})
        return rules

    async def skills(self, tid):
        """Expose only business skill metadata discovered by this native instance."""
        root = PurePosixPath(posixpath.normpath(self.config["skill_root"])) / "skills"
        catalog = []
        for skill in await self.call("GET", "/skill", tid=tid):
            location = PurePosixPath(posixpath.normpath(skill.get("location", "")))
            name = skill.get("name", "")
            if not (location.is_relative_to(root) or location.is_relative_to(PurePosixPath(self.directory(tid)) / ".skill-versions")) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                continue
            heading = re.search(r"^#\s+(.+)$", skill.get("content", ""), re.MULTILINE)
            catalog.append({"name": name, "label": heading[1].strip() if heading else name,
                            "description": skill.get("description", "")})
        return sorted(catalog, key=lambda skill: skill["name"])

    async def refresh_skills(self, tid, directory):
        """Only invalidate the native instance when its skill definitions changed."""
        root = PurePosixPath(self.config["skill_root"]) / "skills"
        actual = {s["name"]: (s.get("description", ""), s.get("content", "").strip())
                  for s in await self.call("GET", "/skill", tid=tid)
                  if PurePosixPath(posixpath.normpath(s.get("location", ""))).is_relative_to(root)}
        expected = {}
        for path in directory.rglob("SKILL.md"):
            parts = path.read_text().split("---", 2)
            if len(parts) == 3:
                meta = yaml.safe_load(parts[1]) or {}
                if meta.get("name"):
                    expected[meta["name"]] = (meta.get("description", ""), parts[2].strip())
        if expected != actual:
            await self.call("POST", "/instance/dispose", tid=tid)
        return await self.skills(tid)

    async def models(self):
        """Project configured native models only; credentials never cross the BFF."""
        providers, config = await asyncio.gather(self.call("GET", "/provider"), self.call("GET", "/config"))
        models = []
        for provider in providers["all"]:
            pid = provider["id"]
            if pid not in providers["connected"]:
                continue
            configured = config.get("provider", {}).get(pid, {}).get("models", {})
            for mid in configured:
                model = provider["models"].get(mid)
                if model and model.get("capabilities", {}).get("toolcall", True):
                    models.append({"id": f"{pid}/{mid}", "providerID": pid, "modelID": mid,
                                   "providerLabel": config.get("provider", {}).get(pid, {}).get("name") or provider.get("name") or pid,
                                   "label": model.get("name") or mid})
        return {"models": models, "default": config.get("model")}

    async def messages(self, thread):
        # Native pagination, oldest-to-newest. No second conversation store.
        result, before = [], None
        while True:
            params = {"limit": 100}
            if before:
                params["before"] = before
            page = await self.call("GET", f'/session/{thread["session_id"]}/message', tid=thread["id"], params=params)
            if not page:
                break
            result = page + result
            next_before = page[0]["info"]["id"]
            if len(page) < 100 or next_before == before:
                break
            before = next_before
        return result

    async def status(self, thread):
        values = await self.call("GET", "/session/status", tid=thread["id"])
        return values.get(thread["session_id"], {"type": "idle"})

    async def last_assistant(self, thread):
        before = None
        while True:
            params = {'limit': 10, **({'before': before} if before else {})}
            page = await self.call('GET', f'/session/{thread["session_id"]}/message', tid=thread['id'], params=params)
            info = next((m['info'] for m in reversed(page) if m['info']['role']=='assistant'), None)
            if info is not None:return info
            if len(page) < 10 or page[0]['info']['id'] == before:return {}
            before = page[0]['info']['id']

    async def events(self, thread):
        async with self.client() as client:
            async with client.stream("GET", "/event", params={"directory": self.directory(thread["id"])}) as response:
                response.raise_for_status()
                data = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        try:
                            yield json.loads("\n".join(data))
                        except json.JSONDecodeError:
                            pass
                        data = []


def public_error(error):
    data = error.get("data", {})
    return {"name": error.get("name", "RuntimeError"), "data": {
        k: data[k] for k in ("message", "statusCode", "isRetryable") if k in data}}


def visible_messages(messages, view=None):
    view = view or PublicView()
    out = []
    for message in messages:
        parts = [p for p in message.get("parts", []) if p.get("type") in {"text", "tool", "file"}
                 and not p.get("synthetic")]
        info = dict(message["info"])
        if info.get("error"):
            info["error"] = public_error(info["error"])
        out.append({"info": view.info(info), "parts": [view.part(p) for p in parts]})
    return out


def visible_event(event, session_id, text_parts, view=None):
    view = view or PublicView()
    kind = event.get("type", "")
    p = event.get("properties", {})
    owner = p.get("sessionID") or p.get("part", {}).get("sessionID") or p.get("info", {}).get("sessionID")
    if kind == "session.updated":owner = p.get("info", {}).get("id")
    if owner != session_id:
        return None
    message_id = p.get("messageID") or p.get("part", {}).get("messageID")
    if message_id in view.suppressed_messages:
        return None
    if kind == "message.part.updated":
        part = p.get("part", {})
        if part.get("type") == "text" and not part.get("synthetic"):
            text_parts.add(part.get("id"))
        if part.get("type") not in {"text", "tool", "file"} or part.get("synthetic"):
            return None
    elif kind == "message.part.delta":
        if p.get("partID") not in text_parts or p.get("field") != "text":
            return None
    elif kind not in {"session.updated", "message.updated", "session.status", "session.error", "todo.updated", "session.compacted",
                      "question.asked", "question.replied", "question.rejected",
                      "permission.asked", "permission.replied"}:
        return None
    view = view or PublicView()
    if kind == "message.part.updated":
        p = {"part": view.part(p["part"])}
    elif kind == "message.part.delta":
        # Project complete text so a path split across native deltas cannot bypass redaction.
        part = view.text_parts.get(p.get("partID"))
        if not part:
            return None
        part = {**part, "text": part.get("text", "") + p.get("delta", "")}
        return {"type": "message.part.updated", "properties": {"part": view.part(part)}}
    elif kind == "session.error" and p.get("error"):
        p = {**p, "error": public_error(p["error"])}
    elif kind == "message.updated":
        info = dict(p["info"])
        if info.get("error"):
            info["error"] = public_error(info["error"])
        p = {"info": view.info(info)}
    elif kind == "permission.asked":
        p = view.request(p)
    return {"type": kind, "properties": view.clean(p)}
