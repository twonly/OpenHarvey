"""Deterministic presentation normalization. Never judge or rewrite risk reasoning."""
import copy
import re

CITE = re.compile(r"【D([a-f0-9]{12}):B(\d+)(?:-B(\d+))?】")
RUN = re.compile(CITE.pattern + r"(?:[ \t\u3000]*" + CITE.pattern + r")*")


def marker(docid, start, end=None):
    return f"【D{docid}:B{start}" + (f"-B{end}" if end is not None and end != start else "") + "】"


def merge_citations(text):
    """Merge only touching/overlapping references in an uninterrupted citation run."""
    def replace(match):
        groups = []
        for token in CITE.finditer(match[0]):
            doc, start, end = token.groups()
            start, end = int(start), int(end or start)
            groups.append([doc, start, end])
            # A newly added interval can bridge two earlier ones (B1,B3,B2).
            while len(groups) > 1:
                a, b = groups[-2:]
                if a[0] != b[0] or a[2] < a[1] or b[2] < b[1] or b[1] > a[2]+1 or b[2] < a[1]-1:
                    break
                groups[-2:] = [[doc, min(a[1], b[1]), max(a[2], b[2])]]
        return "".join(marker(*g) for g in groups)
    return RUN.sub(replace, text)


def evidence_groups(evidence):
    grouped = {}
    for e in evidence:
        key = (e["document_id"], e["source_hash"])
        blocks = grouped.setdefault(key, {})
        quotes = blocks.setdefault(int(e["block_id"][1:]), [])
        if e["quote"] not in quotes:
            quotes.append(e["quote"])
    result = []
    for (doc, version), blocks in grouped.items():
        for block in sorted(blocks):
            if result and result[-1]["document_id"] == doc and result[-1]["source_hash"] == version and result[-1]["end"]+1 == block:
                result[-1]["end"] = block
                result[-1]["quote"] += "\n" + "\n".join(blocks[block])
            else:
                result.append({"document_id": doc, "source_hash": version, "start": block, "end": block,
                               "quote": "\n".join(blocks[block])})
    for g in result:
        g["citation"] = marker(g["document_id"], g["start"], g["end"])
    return result


def process_report(body, rules):
    result = copy.deepcopy(body)
    # HTML/JSON/CSV may contain executable code or literal structured values.
    if result.get("format", "md") in {"md", "txt"}:
        result["content"] = merge_citations(result.get("content", ""))
    lookup = {r["id"]: r for r in rules}
    for finding in (result.get("findings", []) if result.get("kind") == "review" else []):
        rule = lookup.get(finding["risk_id"], {})
        finding.setdefault("risk_name", rule.get("name", finding["risk_id"]))
        finding.setdefault("category", rule.get("category", "其他"))
        finding["reason"] = merge_citations(finding.get("reason", ""))
        finding["evidence_groups"] = evidence_groups(finding.get("evidence", []))
    result["presentation_version"] = 1
    return result


def export_citations(text, documents):
    """Human-readable labels in the Word export; canonical JSON keeps exact IDs."""
    def replace(m):
        doc = documents.get(m[1])
        start, end = int(m[2]), int(m[3] or m[2])
        if not doc or not 0 <= start <= end < len(doc["segments"]):
            return m[0]
        first, last = doc["segments"][start], doc["segments"][end]
        pages = [first.get("page"), last.get("page")]
        location = (f"第 {pages[0]} 页" if pages[0] == pages[1] else f"第 {pages[0]}–{pages[1]} 页") if all(pages) else (f"第 {start+1} 段" if start == end else f"第 {start+1}–{end+1} 段")
        return f"【{doc.get('filename', '原文')} · {location}】"
    return CITE.sub(replace, text)
