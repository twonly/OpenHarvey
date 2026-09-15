import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contract_web.outline_jobs import OutlineJobs


class OutlineJobTests(unittest.TestCase):
    def test_cached_empty_pdf_survives_restart_and_invalidates_by_source_hash(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'source.pdf'
            mapping = {'source_hash': 'v1', 'outline': {'source': 'pdf-bookmarks', 'entries': []}}
            with patch('contract_web.outline_jobs.document_outline', return_value={'entries': []}) as extract:
                jobs = OutlineJobs()
                self.assertEqual(jobs.get(path, mapping)['status'], 'pending')
                jobs.close()
                self.assertEqual(extract.call_count, 1)
                jobs = OutlineJobs()
                try:
                    self.assertEqual(jobs.get(path, mapping)['status'], 'ready')
                    self.assertEqual(extract.call_count, 1)
                    mapping = {**mapping, 'source_hash': 'v2'}
                    self.assertEqual(jobs.get(path, mapping)['status'], 'pending')
                finally:
                    jobs.close()
                self.assertEqual(extract.call_count, 2)
                self.assertEqual(json.loads((path.parent/'outline.json').read_text())['source_hash'], 'v2')

    def test_worker_failure_finishes_instead_of_staying_pending(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'source.pdf';mapping = {'source_hash': 'v1'}
            jobs = OutlineJobs()
            with patch('contract_web.outline_jobs.document_outline', side_effect=ValueError('broken PDF')):
                with self.assertLogs('contract_web.outline_jobs', level='ERROR'):
                    jobs.get(path, mapping);jobs.close()
            result = jobs.get(path, mapping)
            self.assertEqual(result['status'], 'ready')
            self.assertTrue(result['unavailable'])
