"""Bounded, disposable page images. Callers must authenticate every request."""
import hashlib
import os
import shutil
import threading
from concurrent.futures import Future
from pathlib import Path
from .pdf_preview import render_pdf_pages


class PdfPageCache:
    VERSION = 1

    def __init__(self, root, max_bytes=256 * 1024 * 1024):
        self.root, self.max_bytes = Path(root), max_bytes
        self.lock = threading.Lock()
        self.pending = {}

    def directory(self, path):
        # Include the owner/source path; identical private files aren't shared.
        return self.root / hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()

    def get(self, path, source_hash, pages, width=960):
        pages = list(dict.fromkeys(pages))
        if not 1 <= len(pages) <= 3 or not 320 <= width <= 2880:
            raise ValueError("每次预览最多 3 页，宽度须在 320–2880 之间")
        path = Path(path)
        prefix = hashlib.sha256(f'{self.VERSION}:{source_hash}:{width}'.encode()).hexdigest()
        files = {page: self.directory(path) / f'{prefix}-{page}.png' for page in pages}
        result, owned, waiting = {}, {}, {}
        with self.lock:
            if not path.is_file():
                raise FileNotFoundError(path)
            for page, file in files.items():
                try:
                    result[page] = file.read_bytes()
                    os.utime(file, None)
                    continue
                except FileNotFoundError:
                    pass
                future = self.pending.get(file)
                if future is None:
                    future = self.pending[file] = Future()
                    owned[page] = future
                else:
                    waiting[page] = future
        if owned:
            try:
                rendered = render_pdf_pages(path, list(owned), width)
                with self.lock:
                    for page, future in owned.items():
                        data = rendered[page]
                        # Cache failures must not turn a rendered page into an error.
                        if path.is_file() and len(data) <= self.max_bytes:
                            try:
                                file = files[page]
                                file.parent.mkdir(parents=True, exist_ok=True)
                                temporary = file.with_suffix('.tmp')
                                temporary.write_bytes(data)
                                os.replace(temporary, file)
                            except OSError:
                                try:
                                    file.with_suffix('.tmp').unlink(missing_ok=True)
                                except OSError:
                                    pass
                        result[page] = data
                        future.set_result(data)
                        self.pending.pop(files[page], None)
                    self._trim()
            except BaseException as error:
                with self.lock:
                    for page, future in owned.items():
                        if not future.done():
                            future.set_exception(error)
                        self.pending.pop(files[page], None)
                raise
        # Finish owned pages before waiting: overlapping batches cannot deadlock.
        for page, future in waiting.items():
            result[page] = future.result()
        return {page: result[page] for page in pages}

    def _trim(self):
        try:
            files = [(p.stat().st_mtime_ns, p.stat().st_size, p) for p in self.root.glob('*/*.png')]
            total = sum(size for _, size, _ in files)
            for _, size, path in sorted(files):
                if total <= self.max_bytes:
                    break
                path.unlink(missing_ok=True)
                total -= size
        except OSError:
            pass

    def remove(self, path):
        with self.lock:
            shutil.rmtree(self.directory(path), ignore_errors=True)
