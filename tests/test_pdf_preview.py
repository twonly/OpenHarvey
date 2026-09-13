import concurrent.futures
import io
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from contract_web.pdf_preview import render_pdf_page


class PdfPreviewTests(unittest.TestCase):
    def test_pdfium_handles_never_overlap_across_documents_or_threads(self):
        guard=threading.Lock()
        counts={'active':0,'peak':0,'documents':0,'pages':0,'bitmaps':0}

        class Bitmap:
            def to_pil(self):return Image.new('RGB',(8,8),'white')
            def close(self):counts['bitmaps']+=1

        class Page:
            def render(self,scale):return Bitmap()
            def close(self):counts['pages']+=1

        class Document:
            def __init__(self,path):
                with guard:
                    counts['active']+=1
                    counts['peak']=max(counts['peak'],counts['active'])
                time.sleep(.01)  # Allow competing workers to enter if the lock is absent.
            def __enter__(self):return self
            def __len__(self):return 1
            def __getitem__(self,index):return Page()
            def __exit__(self,*args):
                with guard:
                    counts['active']-=1;counts['documents']+=1

        with patch('contract_web.pdf_preview.pypdfium2.PdfDocument',Document):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                images=list(pool.map(lambda i:render_pdf_page(f'/document-{i%3}.pdf',1),range(24)))
        self.assertEqual(counts,{'active':0,'peak':1,'documents':24,'pages':24,'bitmaps':24})
        for image in images:
            with Image.open(io.BytesIO(image)) as decoded:self.assertEqual(decoded.size,(8,8))

    def test_bitmap_page_and_document_close_when_png_encoding_fails(self):
        from pathlib import Path
        import pypdfium2
        pdf=pypdfium2.PdfDocument(Path(__file__).parent/'fixtures/text-contract.pdf')
        page=pdf[0];bitmap=page.render(scale=1.4)
        with patch('contract_web.pdf_preview.pypdfium2.PdfDocument',return_value=pdf), \
             patch.object(type(pdf),'__getitem__',return_value=page), \
             patch.object(page,'render',return_value=bitmap), \
             patch('PIL.Image.Image.save',side_effect=OSError('encode failure')):
            with self.assertRaisesRegex(OSError,'encode failure'):render_pdf_page('unused.pdf',1)
        self.assertIsNone(bitmap.raw);self.assertIsNone(page.raw);self.assertIsNone(pdf.raw)
