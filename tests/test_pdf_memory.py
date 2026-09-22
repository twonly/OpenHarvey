"""Long PDFs must not retain parsed layouts for earlier pages."""
from pathlib import Path
import unittest
import tempfile
import pypdfium2
from unittest.mock import patch

import pdfplumber
from pdfplumber.page import Page

from contract_web.extract_text import extract_pdf_mapped


class PdfMemoryTests(unittest.TestCase):
    def test_previous_page_layout_is_released_and_mapping_is_unchanged(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'long-synthetic.pdf'
        with pypdfium2.PdfDocument(Path(__file__).parent/'fixtures/text-contract.pdf') as source, pypdfium2.PdfDocument.new() as document:
            for _ in range(40):document.import_pages(source, pages=[0])
            document.save(path)
        # Compare against the same parser without per-page cache release.
        with patch.object(Page, 'close', lambda page: None):
            expected_text, expected_mapping = extract_pdf_mapped(path)
        original = Page.extract_text_lines
        previous = []
        def checked(page, *args, **kwargs):
            if previous:
                self.assertNotIn('_layout', previous[-1].__dict__)
                self.assertNotIn('_objects', previous[-1].__dict__)
                self.assertEqual(previous[-1].get_textmap.cache_info().currsize, 0)
            previous.append(page)
            return original(page, *args, **kwargs)
        with patch.object(Page, 'extract_text_lines', checked):
            text, mapping = extract_pdf_mapped(path)
        self.assertEqual(len(mapping['pages']), 40)
        self.assertEqual(text, expected_text)
        self.assertEqual(mapping, expected_mapping)

    def test_page_is_released_if_extraction_fails(self):
        path = Path(__file__).parent / 'fixtures/text-contract.pdf'
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[0]
            _ = page.chars
            original_close = Page.close
            closed = []
            def tracked(item):
                original_close(item)
                closed.append(item)
            with patch('pdfplumber.open', return_value=pdf), \
                 patch.object(page, 'extract_text_lines', side_effect=ValueError('bad page')), \
                 patch.object(Page, 'close', tracked):
                with self.assertRaisesRegex(ValueError, 'bad page'):
                    extract_pdf_mapped(path)
            self.assertIn(page, closed)
            self.assertNotIn('_layout', page.__dict__)
            self.assertNotIn('_objects', page.__dict__)
