"""Actual output formats and an isolated, offline HTML preview."""
import csv
import io
import json

FORMATS = {"md": "text/markdown", "html": "text/html", "txt": "text/plain",
           "json": "application/json", "csv": "text/csv", "svg": "image/svg+xml"}
PREVIEW_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
               "img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; "
               "object-src 'none'; base-uri 'none'; form-action 'none'; sandbox allow-scripts")


def validate_format(body):
    fmt = body.get("format", "md")
    if not isinstance(fmt, str) or fmt not in FORMATS:
        raise ValueError("产出支持 Markdown、HTML、TXT、JSON、CSV、SVG")
    if body.get("kind") == "revision" and fmt != "md":
        raise ValueError("结构化修改稿请用 Markdown 保存；其他排版可另存为 document")
    if fmt == "json":
        json.loads(body["content"])
    if fmt == "csv":
        list(csv.reader(io.StringIO(body["content"]), strict=True))
    if fmt == "svg":
        from xml.etree import ElementTree
        try:
            root = ElementTree.fromstring(body["content"])
        except ElementTree.ParseError:
            raise ValueError("SVG 格式无效") from None
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            raise ValueError("SVG 需要 svg 根节点")
    return fmt


def files_for(body):
    fmt = body.get("format", "md")
    return {fmt: "content." + fmt, **({"docx": "report.docx"} if fmt == "md" else {})}
