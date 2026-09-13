"""Reading navigation from source structure; never infer headings from clause text."""
import logging
import re

from .extract_text import extract_docx_mapped
from .pdf_preview import read_pdf_outline


def document_outline(path, mapping):
    kind = {".docx": "word-headings", ".pdf": "pdf-bookmarks", ".md": "markdown-headings"}.get(path.suffix, "none")
    entries = []
    try:
        if kind == "pdf-bookmarks":
            entries = read_pdf_outline(path)
        elif kind == "word-headings":
            segments = mapping["segments"]
            # Older saved source maps have inferred h values. Re-read only native
            # metadata, and bind it to the unchanged saved block IDs/text.
            native = segments if all("outline_level" in s for s in segments if s.get("node") == "p") else extract_docx_mapped(path)[1]["segments"]
            for original, heading in zip(segments, native):
                if heading.get("outline_level") and original["text"] == heading["text"]:
                    entries.append({"title": original["text"], "level": heading["outline_level"], "block_id": original["id"]})
        elif kind == "markdown-headings":
            fence = None
            for segment in mapping["segments"]:
                text = segment["text"]
                marker = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
                if marker:
                    token = marker[1]
                    if fence is None:
                        fence = token
                    elif token[0] == fence[0] and len(token) >= len(fence) and not text[marker.end():].strip():
                        fence = None
                    continue
                heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", text)
                if not fence and heading:
                    title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2])
                    entries.append({"title": title, "level": len(heading[1]), "block_id": segment["id"]})
        return {"source": kind, "entries": entries}
    except Exception:
        logging.getLogger(__name__).warning("Source outline could not be read", exc_info=True)
        return {"source": kind, "entries": [], "unavailable": True}
