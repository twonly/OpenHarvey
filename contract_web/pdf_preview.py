"""PDFium calls must never overlap, even for different PDF documents."""
import io
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


def render_pdf_page(path, page_number):
    with _PDFIUM_LOCK:
        with pypdfium2.PdfDocument(path) as pdf:
            if not 1 <= page_number <= len(pdf):
                raise IndexError("页码不存在")
            page = pdf[page_number - 1]
            try:
                bitmap = page.render(scale=1.4)
                try:
                    with bitmap.to_pil() as image:
                        output = io.BytesIO()
                        image.save(output, format="PNG")
                        return output.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()
