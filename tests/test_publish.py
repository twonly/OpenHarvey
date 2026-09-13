import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1]/'runtime/scripts/publish.py'


class PublishScriptTests(unittest.TestCase):
    def test_markdown_file_is_posted_verbatim_with_thread_credential(self):
        received=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200);self.end_headers();self.wfile.write(b'{"saved":true,"artifact_id":"test"}')
            def log_message(self,*args):pass
        with tempfile.TemporaryDirectory() as temp, http.server.HTTPServer(('127.0.0.1',0),Handler) as server:
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            root=Path(temp);content='# 摘要\n\n原文有 "英文引号"，也有“中文引号”。\n'
            (root/'report.md').write_text(content)
            (root/'report.json').write_text(json.dumps({'kind':'summary','content_file':'report.md'}))
            (root/'context.json').write_text(json.dumps({'save_url':f'http://127.0.0.1:{server.server_port}/internal/artifacts'}))
            (root/'.publish-token').write_text('synthetic-token')
            try:
                result=subprocess.run([sys.executable,str(SCRIPT),'report.json'],cwd=root,text=True,capture_output=True,timeout=10)
            finally:server.shutdown();worker.join()
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertTrue(json.loads(result.stdout)['saved'])
            self.assertEqual(received,[('Bearer synthetic-token',{'kind':'summary','content':content})])
            self.assertNotIn('synthetic-token',result.stdout)

    def test_body_file_cannot_escape_thread_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'report.json').write_text(json.dumps({'content_file':'../outside.md'}))
            result=subprocess.run([sys.executable,str(SCRIPT),'report.json'],cwd=root,text=True,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,1)
            self.assertFalse(json.loads(result.stdout)['saved'])
