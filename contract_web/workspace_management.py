"""User-owned, recoverable lifecycle for the contract-space index."""
import asyncio
import shutil
import time

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def register_workspace_management(app, store, settings, user, workspace, runtime, manager, queue, traces):
    async def ensure_idle(u, current):
        threads = store.all("SELECT * FROM threads WHERE workspace_id=? AND deleted_at IS NULL", (current["id"],))
        if not threads:
            return threads
        rt = runtime(u,wid=current["id"])
        for item in threads:
            status, questions, permissions = await asyncio.gather(
                rt.status(item), rt.call("GET", "/question", tid=item["id"]),
                rt.call("GET", "/permission", tid=item["id"]))
            pending = queue.state(item["id"])
            if status["type"] != "idle" or pending["active"] or pending["items"] or any(
                    prompt.get("sessionID") == item["session_id"] for prompt in questions + permissions):
                raise HTTPException(409, "空间内仍有运行任务、待处理请求或排队消息，请先处理后再删除")
            traces.sync(u, item, await rt.messages(item), status)
        return threads

    async def purge(u, current):
        if not current["deleted_at"]:
            raise HTTPException(409, "请先将合同空间移入最近删除")
        store.execute("UPDATE workspaces SET purging_at=COALESCE(purging_at,?),purge_error=NULL WHERE id=?",
                      (time.time(), current["id"]))
        threads = store.all("SELECT * FROM threads WHERE workspace_id=?", (current["id"],))
        try:
            if current.get('backend')=='e2b':
                await app.state.e2b.destroy(u,current)
            elif threads:
                rt = runtime(u,wid=current["id"])
                for item in threads:
                    await rt.call("DELETE", f'/session/{item["session_id"]}', tid=item["id"], allow_not_found=True)
            documents = store.all("SELECT id,suffix FROM documents WHERE workspace_id=?", (current["id"],))
            artifacts = store.all("SELECT id FROM artifacts WHERE workspace_id=?", (current["id"],))
            root = store.user_root(u["id"])
            for folder, rows in (("sources", documents), ("threads", threads), ("published", artifacts)):
                for item in rows:
                    path = root / folder / item["id"]
                    if path.exists():
                        shutil.rmtree(path)
                    if folder == 'sources':
                        await run_in_threadpool(app.state.pdf_cache.remove, path / ('source' + item['suffix']))
            tids = [item["id"] for item in threads]
            aids = [item["id"] for item in artifacts]
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                for table, column, values in (
                    ("risk_feedback", "artifact_id", aids), ("trace_runs", "thread_id", tids),
                    ("memory_receipts", "thread_id", tids), ("execution_configs", "thread_id", tids), ("queued_messages", "thread_id", tids),
                    ("queue_state", "thread_id", tids)):
                    if values:
                        marks = ",".join("?" for _ in values)
                        db.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", values)
                db.execute("DELETE FROM artifacts WHERE workspace_id=?", (current["id"],))
                db.execute("DELETE FROM documents WHERE workspace_id=?", (current["id"],))
                db.execute("DELETE FROM threads WHERE workspace_id=?", (current["id"],))
                db.execute("INSERT INTO audit_log(org_id,actor_id,action,target,created) VALUES(?,?,?,?,?)",
                           (u["org_id"], u["id"], "workspace.purge", current["id"], time.time()))
                for table in ('e2b_files','e2b_bindings','e2b_events','e2b_receipts'):
                    db.execute('DELETE FROM '+table+' WHERE workspace_id=?',(current['id'],))
                for tid in tids:db.execute('DELETE FROM e2b_history WHERE thread_id=?',(tid,))
                shutil.rmtree(root/'runtime-archives'/current['id'],ignore_errors=True)
                db.execute("DELETE FROM workspaces WHERE id=?", (current["id"],))
        except Exception:
            if store.one("SELECT 1 FROM workspaces WHERE id=? AND user_id=?", (current["id"], u["id"])):
                store.execute("UPDATE workspaces SET purge_error=? WHERE id=?",
                              ("部分内容未能清理，请重试永久删除。", current["id"]))
            raise HTTPException(503, "永久删除未完成，合同空间仍保留在最近删除中，可稍后重试") from None
        return {"id": current["id"], "purged": True}

    app.state.purge_workspace=purge

    @app.patch("/api/workspaces/{wid}")
    async def manage_workspace(wid: str, request: Request):
        u = user(request)
        body = await request.json()
        action = body.get("action") if isinstance(body, dict) else None
        if action not in {"star", "unstar", "rename", "delete", "restore", "purge"}:
            raise HTTPException(422, "合同空间操作无效")
        current = workspace(u, wid, include_deleted=True)
        if current["purging_at"] and action != "purge":
            raise HTTPException(409, "合同空间正在清理或上次清理未完成，请重试永久删除")
        if action in {"delete", "purge"} and body.get("confirmed") is not True:
            raise HTTPException(422, "请先确认删除操作")
        if action == "rename":
            title = str(body.get("title", "")).strip()
            if not 1 <= len(title) <= 120:
                raise HTTPException(422, "合同空间名称须为 1–120 字")

        async with manager.lock('queue-'+current['id'] if current.get('backend')=='e2b' else u['id']):
            current = workspace(u, wid, include_deleted=True)
            if action == "purge":
                return await purge(u, current)
            if action == "delete":
                if current["deleted_at"]:
                    raise HTTPException(409, "合同空间已在最近删除中")
                await ensure_idle(u, current)
                store.execute("UPDATE workspaces SET deleted_at=? WHERE id=?", (time.time(), wid))
            elif action == "restore":
                if not current["deleted_at"]:
                    raise HTTPException(409, "合同空间已恢复，请刷新列表")
                store.execute("UPDATE workspaces SET deleted_at=NULL,last_activity_at=? WHERE id=?", (time.time(), wid))
            elif action == "rename":
                if current["deleted_at"]:
                    raise HTTPException(409, "请先恢复合同空间再重命名")
                store.execute("UPDATE workspaces SET title=?,last_activity_at=? WHERE id=?", (title, time.time(), wid))
            else:
                if current["deleted_at"]:
                    raise HTTPException(409, "请先恢复合同空间")
                store.execute("UPDATE workspaces SET starred=? WHERE id=?", (1 if action == "star" else 0, wid))
            settings.audit(u, "workspace." + action, wid)
        result = workspace(u, wid, include_deleted=True)
        return {key: result[key] for key in (
            "id", "title", "starred", "deleted_at", "last_activity_at", "purging_at", "purge_error")}
