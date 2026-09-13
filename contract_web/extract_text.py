#!/usr/bin/env python3
"""合同文本抽取：docx / 文字版 PDF / md|txt -> 条款化 Markdown。

保留条款编号与层级，供后续 LLM 分类与风险判定使用。
用法：
    python3 extract_text.py <合同文件> [-o 输出.md]
不带 -o 时输出到 stdout。扫描件（无文字层的 PDF）会明确报错。
"""

import argparse
import re
import sys
from pathlib import Path


class ExtractError(Exception):
    """文档无法抽取出可用文本（扫描件、格式不支持等），message 直接面向用户。"""


# 中文合同常见条款编号样式，按层级从高到低
HEADING_PATTERNS = [
    (re.compile(r"^第[一二三四五六七八九十百零\d]+[章部分]"), 1),
    (re.compile(r"^第[一二三四五六七八九十百零\d]+条"), 2),
    (re.compile(r"^[一二三四五六七八九十]+、"), 2),
    (re.compile(r"^\d+(\.\d+)+\s*[、.\s]?"), 3),
    (re.compile(r"^（[一二三四五六七八九十\d]+）"), 3),
]


def detect_heading_level(text: str) -> int | None:
    for pattern, level in HEADING_PATTERNS:
        if pattern.match(text):
            return level
    return None


def _iter_docx_blocks(doc):
    """按文档顺序产出段落和表格（python-docx 默认分开存放）。"""
    from docx.document import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parent = doc.element.body
    for child in parent.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def _docx_list_number(paragraph, counters: dict) -> str:
    """还原 Word 自动编号（正文里不存数字，需按 numId/ilvl 计数重建）。

    简化实现：同一 numId 内层级递增计数，更浅层级递增时重置更深层级。
    对常规合同的多级条款编号足够；异常样式最多编号不准，不丢正文。
    """
    numpr = paragraph._p.find(
        ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr"
    )
    if numpr is None:
        return ""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    numid_el = numpr.find(f"{ns}numId")
    ilvl_el = numpr.find(f"{ns}ilvl")
    if numid_el is None:
        return ""
    numid = numid_el.get(f"{ns}val")
    ilvl = int(ilvl_el.get(f"{ns}val")) if ilvl_el is not None else 0

    key = numid
    levels = counters.setdefault(key, {})
    levels[ilvl] = levels.get(ilvl, 0) + 1
    for deeper in [l for l in levels if l > ilvl]:
        del levels[deeper]
    parts = [str(levels.get(l, 1)) for l in range(ilvl + 1)]
    return ".".join(parts) + " "


def _native_outline_level(paragraph):
    """Respect Word's direct/inherited outline level, including body-text overrides."""
    from docx.oxml.ns import qn
    elements = [paragraph._p]
    style, seen = paragraph.style, set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        elements.append(style.element)
        style = style.base_style
    for element in elements:
        value = element.find("./" + qn("w:pPr") + "/" + qn("w:outlineLvl"))
        if value is not None:
            level = int(value.get(qn("w:val")))
            return level + 1 if 0 <= level <= 8 else 0
    return 0


def extract_docx_mapped(path: Path) -> tuple[str, dict]:
    """Word -> (条款化 Markdown, 结构映射)。

    映射里的 segment 顺序与产出的非空 Markdown 行一致，供 Web 端把
    docx-preview 渲染出的段落/表格行关联回条款定位索引。Markdown 表头
    分隔行没有 Word DOM 对应节点，因此用 ``skip`` 明确标记。
    """
    import docx

    doc = docx.Document(str(path))
    lines: list[str] = []
    segments: list[dict] = []
    counters: dict = {}

    for block in _iter_docx_blocks(doc):
        if block.__class__.__name__ == "Table":
            rows = []
            for row in block.rows:
                cells = [" ".join(c.text.split()) for c in row.cells]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                header_sep = "|" + " --- |" * len(block.rows[0].cells)
                lines.append(rows[0])
                segments.append({"text": rows[0], "h": 0, "node": "tr"})
                lines.append(header_sep)
                segments.append({"text": header_sep, "h": 0, "skip": True})
                lines.extend(rows[1:])
                segments.extend({"text": row, "h": 0, "node": "tr"}
                                for row in rows[1:])
                lines.append("")
            continue

        text = block.text.strip()
        number = _docx_list_number(block, counters)
        if not text:
            continue
        text = number + text

        style = (block.style.name or "").lower()
        heading_match = re.match(r"heading (\d)", style)
        if heading_match:
            level = min(int(heading_match.group(1)), 4)
        else:
            level = detect_heading_level(text)

        if level:
            lines.append(f"{'#' * (level + 1)} {text}")
        else:
            lines.append(text)
        segments.append({"text": text, "h": level or 0, "node": "p",
                         "outline_level": _native_outline_level(block)})
        lines.append("")

    return "\n".join(lines), {"kind": "docx", "segments": segments}


def extract_docx(path: Path) -> str:
    return extract_docx_mapped(path)[0]


def extract_pdf_mapped(path: Path) -> tuple[str, dict]:
    """文字版 PDF -> (条款化 Markdown, 位置映射)。

    位置映射供 Web 端在 PDF 原件上定位条款：每个产出的标题/正文行对应
    原 PDF 的页码与 bbox（PDF 点坐标，原点在页面左上角）：
        {"pages": [{"w", "h"}, ...],
         "segments": [{"page", "text", "bbox": [x0, top, x1, bottom], "h"}, ...]}
    """
    import pdfplumber

    pages: list[dict] = []
    raw_lines: list[tuple[str, int, list[float]]] = []
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            pages.append({"w": round(page.width, 2), "h": round(page.height, 2)})
            for ln in page.extract_text_lines(return_chars=False):
                text = (ln.get("text") or "").strip()
                if text:
                    raw_lines.append((text, pno, [
                        round(ln["x0"], 2), round(ln["top"], 2),
                        round(ln["x1"], 2), round(ln["bottom"], 2)]))

    if sum(len(t) for t, _, _ in raw_lines) < 50:
        raise ExtractError(
            "该 PDF 几乎没有可提取的文字层，疑似扫描件。"
            "请提供文字版 PDF 或 Word 原件，或先做 OCR。"
        )

    lines: list[str] = []
    segments: list[dict] = []
    for text, pno, bbox in raw_lines:
        # 去掉常见页眉页脚噪声（纯页码）
        if re.fullmatch(r"[-—\s]*\d{1,3}[-—\s]*", text):
            continue
        level = detect_heading_level(text)
        if level:
            lines.append("")
            lines.append(f"{'#' * (level + 1)} {text}")
            lines.append("")
        else:
            lines.append(text)
        segments.append({"page": pno, "text": text, "bbox": bbox, "h": level or 0})
    return "\n".join(lines), {"kind": "pdf", "pages": pages,
                                "segments": segments}


def extract_pdf(path: Path) -> str:
    return extract_pdf_mapped(path)[0]


def extract_with_map(path: Path) -> tuple[str, dict | None]:
    """extract() 的带原件映射版本；PDF/Word 返回映射，文本格式返回 None。"""
    suffix = path.suffix.lower()
    source_map = None
    if suffix == ".docx":
        body, source_map = extract_docx_mapped(path)
    elif suffix == ".pdf":
        body, source_map = extract_pdf_mapped(path)
    elif suffix in (".md", ".txt", ".markdown"):
        body = path.read_text(encoding="utf-8")
    else:
        raise ExtractError(f"不支持的文件格式 {suffix}（支持 .docx / .pdf / .md / .txt）")

    if len(body.strip()) < 50:
        raise ExtractError("未能从文件中提取到有效文本。")
    return f"# {path.stem}\n\n{body.strip()}\n", source_map


def extract(path: Path) -> str:
    return extract_with_map(path)[0]


def main():
    parser = argparse.ArgumentParser(description="合同文本抽取 -> 条款化 Markdown")
    parser.add_argument("file", help="合同文件路径 (.docx/.pdf/.md/.txt)")
    parser.add_argument("-o", "--output", help="输出 markdown 文件路径，缺省打印到 stdout")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"错误：文件不存在 {path}")

    try:
        markdown = extract(path)
    except ExtractError as e:
        sys.exit(f"错误：{e}")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"已写入 {out}（{len(markdown)} 字符）")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
