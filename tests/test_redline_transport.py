import importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'runtime/scripts/submit.py'
spec=importlib.util.spec_from_file_location('redline_submit',SCRIPT);submitter=importlib.util.module_from_spec(spec);spec.loader.exec_module(submitter)
class RedlineTransportTests(unittest.TestCase):
    def test_reads_are_fresh_while_identical_writes_keep_transport_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'context.json').write_text(json.dumps({'thread_id':'thread','execution_id':'run'}))
            with patch('pathlib.Path.cwd',return_value=root),patch.dict(os.environ,{'CW_EXCHANGE_DIR':str(root/'exchange')}):
                f=root/'request.json';f.write_text(json.dumps({'kind':'redline','action':'inspect','document_id':'doc'}))
                a=submitter.submit('request.json',timeout=0);b=submitter.submit('request.json',timeout=0)
                self.assertNotEqual(a['request_id'],b['request_id'])
                f.write_text(json.dumps({'kind':'redline','action':'apply','document_id':'doc','request_id':'operation'}))
                a=submitter.submit('request.json',timeout=0);b=submitter.submit('request.json',timeout=0)
                self.assertEqual(a['request_id'],b['request_id'])
