import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from contract_web.pdf_cache import PdfPageCache


class PdfCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source.pdf';self.source.write_bytes(b'fixture')
        self.cache=PdfPageCache(self.root/'cache',max_bytes=100)

    def test_overlapping_batch_and_single_request_render_each_page_once(self):
        entered,release=threading.Event(),threading.Event()
        def render(path,pages,width):
            entered.set();self.assertTrue(release.wait(2))
            return {page:f'PNG-{page}'.encode() for page in pages}
        with patch('contract_web.pdf_cache.render_pdf_pages',side_effect=render) as renderer:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                batch=pool.submit(self.cache.get,self.source,'v1',[1,2,3],960)
                self.assertTrue(entered.wait(2))
                single=pool.submit(self.cache.get,self.source,'v1',[2],960)
                release.set()
                self.assertEqual(batch.result(),{1:b'PNG-1',2:b'PNG-2',3:b'PNG-3'})
                self.assertEqual(single.result(),{2:b'PNG-2'})
            self.assertEqual(renderer.call_count,1)
            self.assertEqual(self.cache.get(self.source,'v1',[2]),{2:b'PNG-2'})
            self.assertEqual(renderer.call_count,1)

    def test_failed_render_is_not_cached_and_retry_succeeds(self):
        with patch('contract_web.pdf_cache.render_pdf_pages',side_effect=ValueError('bad page')):
            with self.assertRaises(ValueError):self.cache.get(self.source,'v1',[1])
        self.assertFalse(self.cache.pending)
        with patch('contract_web.pdf_cache.render_pdf_pages',return_value={1:b'PNG'}):
            self.assertEqual(self.cache.get(self.source,'v1',[1]),{1:b'PNG'})

    def test_versions_resolution_and_owner_paths_do_not_share_images(self):
        other=self.root/'other.pdf';other.write_bytes(b'fixture')
        with patch('contract_web.pdf_cache.render_pdf_pages',return_value={1:b'PNG'}) as renderer:
            for path,version,width in [(self.source,'v1',960),(self.source,'v2',960),(self.source,'v2',1920),(other,'v2',1920)]:
                self.cache.get(path,version,[1],width)
            self.assertEqual(renderer.call_count,4)

    def test_cache_is_bounded_and_deleted_source_cannot_be_read_from_cache(self):
        with patch('contract_web.pdf_cache.render_pdf_pages',side_effect=lambda path,pages,width:{page:b'x'*60 for page in pages}):
            self.cache.get(self.source,'v1',[1,2,3])
        self.assertLessEqual(sum(p.stat().st_size for p in (self.root/'cache').glob('*/*.png')),100)
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):self.cache.get(self.source,'v1',[3])
        self.cache.remove(self.source)
        self.assertFalse(self.cache.directory(self.source).exists())
