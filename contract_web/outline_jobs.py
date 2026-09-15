"""Background navigation metadata, cached separately from immutable source maps."""
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

from .document_outline import document_outline

VERSION = 1
PENDING = {"status": "pending", "entries": []}


class OutlineJobs:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-outline")
        self.jobs = {}

    def get(self, path, mapping):
        # Called from the app event loop only. Futures work across request loops
        # and a single worker bounds CPU/PDFium use during batches of uploads.
        key = (path, mapping["source_hash"])
        cache = path.parent / "outline.json"
        try:
            saved = json.loads(cache.read_text())
            if saved.get("version") == VERSION and saved.get("source_hash") == key[1]:
                self.jobs.pop(key, None)
                return saved["outline"]
        except (OSError, ValueError, KeyError):
            pass
        existing = mapping.get("outline", {})
        if existing.get("status") != "pending" and "entries" in existing:
            # Existing native outlines remain valid; empty PDFs need the new
            # link fallback. Old maps without metadata are rebuilt in the worker.
            if path.suffix != ".pdf" or existing["entries"]:
                return {**existing, "status": "ready"}
        future = self.jobs.get(key)
        if future is None:
            self.jobs[key] = self.pool.submit(self._extract, path, mapping)
        elif future.done():
            return future.result()
        return dict(PENDING)

    @staticmethod
    def _extract(path, mapping):
        try:
            outline = {**document_outline(path, mapping), "status": "ready"}
        except Exception:
            logging.getLogger(__name__).exception("Directory recognition failed")
            outline = {"status": "ready", "entries": [], "unavailable": True}
        temporary = None
        try:
            # Never recreate a source directory if it was deleted during work.
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".outline-", delete=False) as file:
                temporary = file.name
                json.dump({"version": VERSION, "source_hash": mapping["source_hash"], "outline": outline}, file, ensure_ascii=False)
            os.replace(temporary, path.parent / "outline.json")
        except OSError:
            logging.getLogger(__name__).warning("Directory cache could not be saved", exc_info=True)
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return outline

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
