"""PDFium calls must never overlap, even for different PDF documents."""
import io
import ctypes
import math
import re
import threading

import pypdfium2

# Shared by every request/app in this process. Keep handle cleanup inside it too:
# https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading
_PDFIUM_LOCK = threading.Lock()


def read_pdf_outline(path):
    # The same lock covers rendering, bookmark traversal and handle cleanup.
    with _PDFIUM_LOCK:
        with pypdfium2.PdfDocument(path) as pdf:
            entries = []
            for bookmark in pdf.get_toc():
                dest = bookmark.get_dest()
                if dest is None:
                    # PDF bookmarks may store an internal GoTo action instead
                    # of a direct destination. External actions are not followed.
                    raw = pypdfium2.raw
                    action = raw.FPDFBookmark_GetAction(bookmark)
                    if action and raw.FPDFAction_GetType(action) == raw.PDFACTION_GOTO:
                        target = raw.FPDFAction_GetDest(pdf, action)
                        if target:
                            dest = pypdfium2.PdfDest(target, pdf=pdf)
                index = dest.get_index() if dest else None
                title = bookmark.get_title().strip()
                if title and index is not None and 0 <= index < len(pdf):
                    entries.append({"title": title, "level": bookmark.level + 1, "page": index + 1})
            return entries


def read_pdf_link_outline(path, mapping):
    """Read internal links on printed TOC pages, using existing extracted text.

    Do not scan arbitrary body links or guess destinations from printed numbers.
    Release PDFium between pages so preview rendering can proceed concurrently.
    """
    pages = {}
    for segment in mapping.get("segments", []):
        pages.setdefault(segment.get("page"), []).append(segment.get("text", ""))
    candidates = [page for page, lines in pages.items() if page and (
        any(re.fullmatch(r"目录|目次|contents|tableofcontents", re.sub(r"\s", "", line), re.I) for line in lines)
        or sum(bool(re.search(r"[.．·…]{3,}\s*\d+\s*$", line)) for line in lines) >= 3)]
    entries, seen = [], set()
    raw = pypdfium2.raw
    for number in sorted(candidates):
        with _PDFIUM_LOCK:
            with pypdfium2.PdfDocument(path) as pdf:
                if not 1 <= number <= len(pdf):
                    continue
                page = pdf[number - 1]
                try:
                    text = page.get_textpage()
                    try:
                        position, link = ctypes.c_int(0), raw.FPDF_LINK()
                        rows = []
                        while raw.FPDFLink_Enumerate(page, ctypes.byref(position), ctypes.byref(link)):
                            action = raw.FPDFLink_GetAction(link)
                            # PDFium can return a destination for remote GoToR
                            # actions too; never interpret those as local pages.
                            if action and raw.FPDFAction_GetType(action) != raw.PDFACTION_GOTO:
                                continue
                            dest = raw.FPDFLink_GetDest(pdf, link)
                            if not dest:
                                if action and raw.FPDFAction_GetType(action) == raw.PDFACTION_GOTO:
                                    dest = raw.FPDFAction_GetDest(pdf, action)
                            target = raw.FPDFDest_GetDestPageIndex(pdf, dest) if dest else -1
                            rect = raw.FS_RECTF()
                            if not 0 <= target < len(pdf) or not raw.FPDFLink_GetAnnotRect(link, ctypes.byref(rect)):
                                continue
                            title = text.get_text_bounded(rect.left, rect.bottom, rect.right, rect.top).strip()
                            # Word exports may link only the page number, or link
                            # the title and number separately. Recover the row.
                            if re.fullmatch(r"[\divxlcdm\s]+", title, re.I):
                                title = text.get_text_bounded(0, rect.bottom, page.get_width(), rect.top).strip()
                            title = re.sub(r"[.．·…]{2,}.*$", "", title, flags=re.S)
                            title = re.sub(r"\s+\d+\s*$", "", title)
                            title = re.sub(r"\s+", " ", title).strip()
                            if title and not re.fullmatch(r"[\divxlcdm\s]+", title, re.I):
                                rows.append((-rect.top, rect.left, title, target + 1))
                        for _, _, title, target in sorted(rows):
                            key = (re.sub(r"\s", "", title), target)
                            if key in seen:
                                continue
                            seen.add(key)
                            section = re.match(r"^(\d+(?:\.\d+)+)\b", title)
                            level = min(9, section[1].count('.') + 1) if section else 1
                            entries.append({"title": title, "level": level, "page": target})
                    finally:
                        text.close()
                finally:
                    page.close()
    return entries


def render_pdf_page(path, page_number, width=960):
    return render_pdf_pages(path, [page_number], width)[page_number]


def render_pdf_pages(path, page_numbers, width=960):
    """Open once for a small batch, closing every bitmap before the next page."""
    if not 320 <= width <= 2880:
        raise ValueError("预览宽度超出范围")
    with _PDFIUM_LOCK:
        with pypdfium2.PdfDocument(path) as pdf:
            if any(not 1 <= number <= len(pdf) for number in page_numbers):
                raise IndexError("页码不存在")
            result = {}
            for page_number in page_numbers:
                page = pdf[page_number - 1]
                try:
                    page_width, page_height = page.get_size()
                    scale = (width - 1e-6) / page_width
                    if width * math.ceil(page_height * scale) > 16_000_000:
                        raise ValueError("页面尺寸过大，请下载原件查看")
                    bitmap = page.render(scale=scale)
                    try:
                        with bitmap.to_pil() as image:
                            output = io.BytesIO()
                            image.save(output, format="PNG")
                            result[page_number] = output.getvalue()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            return result
