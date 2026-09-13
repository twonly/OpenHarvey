"""Deterministic document preparation and evidence checks, with no LLM client."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

from .extract_text import extract_with_map, extract_docx_mapped, ExtractError
from .report_processing import CITE
from .document_outline import document_outline

MAX_UPLOAD = 20 * 1024 * 1024
SUFFIXES = {".docx", ".pdf", ".md", ".txt"}
CITATION = CITE


def prepare(path, document_id):
    if path.suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
                raise ValueError("Word 解压后的内容过大")
    # Short text attachments can be meaningful (for example, one revised date).
    if path.suffix in {".txt", ".md"}:
        text, mapping = path.read_text(encoding="utf-8"), None
    elif path.suffix == ".docx":
        text, mapping = extract_docx_mapped(path)
    else:
        text, mapping = extract_with_map(path)
    if not text.strip():
        raise ExtractError("文档没有可读取的正文")
    if mapping is None:
        mapping = {"kind": "text", "segments": [
            {"text": line, "h": 0} for line in text.splitlines() if line.strip()]}
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    for i, segment in enumerate(mapping["segments"]):
        segment["id"] = f"B{i}"
        segment["citation"] = f"【D{document_id}:B{i}】"
    annotated = "\n".join(f'{s["citation"]} {s["text"]}' for s in mapping["segments"])
    mapping.update(document_id=document_id, source_hash=source_hash, text=text)
    mapping["outline"] = document_outline(path, mapping)
    (path.parent / "contract.md").write_text(annotated, encoding="utf-8")
    (path.parent / "document.json").write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping


def validate_citations(content, documents):
    for docid, block, end in CITATION.findall(content):
        doc = documents.get(docid)
        if not doc or not 0 <= int(block) <= int(end or block) < len(doc["segments"]):
            raise ValueError(f"引用不属于当前会话材料：D{docid}:B{block}")
    # Reject malformed bracket citations too, rather than displaying a fake link.
    for candidate in re.findall(r"【[^】]*(?:D[0-9a-f]|B\d)[^】]*】", content):
        if not CITATION.fullmatch(candidate):
            raise ValueError(f"引用格式无效：{candidate}")


def read_blocks(messages, documents, paths):
    """Only successful native read outputs count; a model coverage list does not."""
    seen = {docid: set() for docid in documents}
    for message in messages:
        for part in message.get("parts", []):
            state = part.get("state", {})
            if part.get("type") != "tool" or part.get("tool") != "read" or state.get("status") != "completed":
                continue
            path = state.get("input", {}).get("filePath", "")
            docid = paths.get(path)
            if docid not in documents:
                continue
            output = state.get("output", "")
            if not isinstance(output, str):
                continue
            output = re.sub(r"(?m)^\d+: ", "", output)
            for seg in documents[docid]["segments"]:
                expected = f'{seg["citation"]} {seg["text"]}'
                if expected in output:
                    seen[docid].add(seg["id"])
    return seen


def validate_result(body, documents, rules, coverage, primary_id):
    if not isinstance(body, dict):
        raise ValueError("产出物必须是 JSON 对象")
    if body.get("source_hash") != documents[primary_id]["source_hash"]:
        raise ValueError("合同版本不匹配")
    if body.get("kind") == "revision":
        changes = body.get("changes")
        if not isinstance(changes, list) or not changes or len(changes) > 100:
            raise ValueError("修改稿需要 1–100 条 changes")
        lines = ["# 条款修改对照"]
        for i, change in enumerate(changes, 1):
            if not isinstance(change, dict):
                raise ValueError("条款修改必须是对象")
            docid = change.get("document_id")
            doc = documents.get(docid)
            block = next((s for s in doc["segments"] if s["id"] == change.get("block_id")), None) if doc else None
            quote, replacement, reason = (change.get(k) for k in ("quote", "replacement", "reason"))
            if not block or not isinstance(quote, str) or not quote or quote not in block["text"]:
                raise ValueError("修改稿原条款与当前材料不一致")
            if block["id"] not in coverage.get(docid, set()):
                raise ValueError("请先用 read 读取要修改的原条款")
            if any(not isinstance(v, str) or not v.strip() for v in (replacement, reason)):
                raise ValueError("修改稿需要建议条款和修改理由")
            lines += [f"\n## 修改 {i}", f"\n原文位置：{block['citation']}",
                      f"\n**原条款**\n\n{quote}", f"\n**建议条款**\n\n{replacement}", f"\n**修改理由**\n\n{reason}"]
        body["content"] = "\n".join(lines)
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip() or len(content) > 2_000_000:
        raise ValueError("产出物正文为空或过长")
    if body.get("kind") not in {"summary", "review", "revision", "document"}:
        raise ValueError("不支持的产出类型")
    validate_citations(content, documents)
    if body["kind"] == "document":
        return
    if not CITATION.search(content):
        raise ValueError("报告需要包含原文引用")
    if body["kind"] == "revision":
        return
    missing = {s["id"] for s in documents[primary_id]["segments"]} - coverage.get(primary_id, set())
    if missing:
        raise ValueError(f"完整报告仍有 {len(missing)} 段原文未读取；请用 read 分段继续读取 contract.md 后保存")
    if body["kind"] == "summary":
        return
    rows = body.get("findings")
    if not isinstance(rows, list):
        raise ValueError("风险报告需要 findings 数组")
    ids = [r.get("risk_id") for r in rows if isinstance(r, dict)]
    if len(ids) != len(rows) or len(set(ids)) != len(ids) or set(ids) != {r["id"] for r in rules}:
        raise ValueError("风险清单须逐项包含全部启用的风险点，且不可重复；不适用项请说明理由")
    for row in rows:
        if row.get("verdict") not in {"命中", "未命中", "信息不足"} or not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("每个风险点需要判定结论及理由")
        if not isinstance(row.get("applicable", True), bool):
            raise ValueError("applicable 必须为布尔值")
        validate_citations(row["reason"], documents)
        if row["risk_id"] not in content:
            raise ValueError("报告正文与风险清单不一致：正文缺少风险编号")
        evidence = row.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(e, dict) for e in evidence):
            raise ValueError("evidence 必须是证据对象数组")
        for e in evidence:
            doc = documents.get(e.get("document_id"))
            if not doc or e.get("source_hash") != doc["source_hash"]:
                raise ValueError("风险证据的文档或版本无效")
            block = next((s for s in doc["segments"] if s["id"] == e.get("block_id")), None)
            quote = e.get("quote", "")
            if not block or not isinstance(quote, str) or not quote or quote not in block["text"]:
                raise ValueError("风险引文与对应原文不一致")
        if row.get("applicable", True) and row["verdict"] != "信息不足" and not row.get("evidence"):
            raise ValueError("确定性风险判断需要原文证据；材料不足请标为信息不足")


def active_rules(library):
    import yaml
    points = []
    for path in sorted(Path(library).glob("*.yaml")):
        if not path.name.startswith("_"):
            points.extend(yaml.safe_load(path.read_text()) or [])
    activation = Path(library) / "_activation.yaml"
    if activation.exists():
        config = yaml.safe_load(activation.read_text()) or {}
        points = [p for p in points if p["id"] in config.get("enabled_risk_ids", [])
                  and p.get("industry", "通用") in config.get("enabled_industries", [])]
    return points
