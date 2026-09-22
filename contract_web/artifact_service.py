"""Business artifact validation and persistence, independent of submission transport."""
import hashlib
import json
import secrets
import shutil
import time
from starlette.concurrency import run_in_threadpool
from .documents import read_blocks, validate_result
from .artifact_formats import validate_format
from .report_processing import process_report, export_citations
from .export import _md_to_docx_bytes


class ArtifactService:
    def __init__(self, store, risks, documents_for, source_dir):
        self.store, self.risks = store, risks
        self.documents_for, self.source_dir = documents_for, source_dir

    async def save(self, u, t, w, body, rt, *, native=None):
        if body.get('kind') == 'redline':
            return await self.redline.apply(u, t, {**body, 'agent': True})
        if native is None:
            native = await rt.messages(t)
        # Validation, document conversion and disk/SQLite work must not occupy
        # the HTTP event loop. Keep the existing caller's save lock and receipt.
        return await run_in_threadpool(self._save, u, t, w, body, rt, native)

    def _save(self, u, t, w, body, rt, native):
        docs = self.documents_for(u, t)
        maps = {d["id"]: json.loads((self.source_dir(u, d["id"])/"document.json").read_text()) for d in docs}
        coverage = read_blocks(native, maps, {rt.source_path(d["id"]): d["id"] for d in docs})
        execution = self.risks.recorded(u, t)
        if execution:
            rules = execution["risk_scheme"]["rules"]
        else:
            # Existing sessions can publish using the exact file prepared for them.
            saved_rules = self.store.user_root(u["id"]) / "threads" / t["id"] / "risk-library.json"
            rules = json.loads(saved_rules.read_text()) if saved_rules.exists() else []
        body.pop("execution_config", None)
        if execution:
            body["execution_config"] = execution
        validate_result(body, maps, rules, coverage, w["document_id"])
        fmt = validate_format(body)
        body = process_report(body, rules)
        title = str(body.get("title") or {"summary": "合同摘要", "review": "风险审查报告", "revision": "条款修改稿", "document": "合同产出物"}[body["kind"]])[:120]
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self.store.one("SELECT * FROM artifacts WHERE thread_id=? AND kind=? AND content_hash=?",
                             (t["id"], body["kind"], content_hash))
        if existing:
            return {"saved": True, "artifact_id": existing["id"], "title": existing["title"]}
        aid = secrets.token_hex(12)
        dest = self.store.user_root(u["id"]) / "published" / aid
        dest.mkdir(parents=True)
        try:
            (dest/f"content.{fmt}").write_text(body["content"], encoding="utf-8")
            (dest/"report.json").write_text(encoded)
            if fmt == "md":
                export_maps = {d["id"]: {**maps[d["id"]], "filename": d["filename"]} for d in docs}
                (dest/"report.docx").write_bytes(_md_to_docx_bytes(export_citations(body["content"], export_maps)))
            self.store.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)", (aid, w["id"], t["id"],
                          body["kind"], title, content_hash, body["source_hash"], time.time()))
            self.store.execute("UPDATE workspaces SET last_activity_at=? WHERE id=?", (time.time(), w["id"]))
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return {"saved": True, "artifact_id": aid, "title": title,
                "download_url": f"/api/artifacts/{aid}/file?format={fmt}"}
