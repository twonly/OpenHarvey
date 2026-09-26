import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.export_website import hosting_config, PUBLIC_PATHS, WORKBENCH_PATHS, GUIDE_ASSETS


class WebsiteExportTests(unittest.TestCase):
    def test_same_origin_routes_cover_workbench_without_exposing_internal_endpoints(self):
        config=hosting_config('https://backend.example.com/')
        routes={r['source']:r['destination'] for r in config['rewrites']}
        for path in ('/connectors','/demo','/login','/agent','/model','/ops','/ops/:path*','/api/:path*','/static/:path*','/auth/:path*','/orca/:path*','/trial-model/:path*'):
            self.assertEqual(routes[path],'https://backend.example.com'+path)
        self.assertNotIn('/internal/:path*',routes)
        self.assertNotIn('/guide',routes)
        guide_rule=next(r for r in config['redirects'] if r['source']=='/guide')
        self.assertFalse(guide_rule['permanent'])
        self.assertEqual(guide_rule['has'],[{'type':'query','key':'topic','value':'review-tables'}])
        self.assertEqual(guide_rule['destination'],'https://backend.example.com/guide?topic=review-tables')
        for row in config['headers']:
            if any(h['key']=='Content-Security-Policy' for h in row['headers']):
                self.assertIn(row['source'],PUBLIC_PATHS)
        for path in WORKBENCH_PATHS:
            headers={h['key']:h['value'] for row in config['headers'] if row['source']==path for h in row['headers']}
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertEqual(headers['CDN-Cache-Control'],'no-store')

    def test_export_keeps_chinese_and_english_product_links_relative(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'site'
            subprocess.run([sys.executable,'-m','scripts.export_website',str(dest),'--workbench-origin','https://backend.example.com'],cwd=root,check=True,capture_output=True)
            for path in ('index.html','en.html'):
                body=(dest/path).read_text()
                self.assertNotIn('agent.tokrace.com',body)
                self.assertIn('site-telemetry.js',body)
                for link in ('/demo','/spaces','/guide'):
                    self.assertIn('href="'+link+('?lang=en' if path=='en.html' else '')+'"',body)
            self.assertTrue(json.loads((dest/'vercel.json').read_text())['rewrites'])
            guide=(dest/'guide.html').read_text()
            self.assertIn('id="materials"',guide)
            self.assertIn('materials-labs.zh-CN.md',guide)
            self.assertIn('官网手册与服务升级分别发布',guide)
            self.assertIn('/guide-assets/product-guide.js',guide)
            for asset in GUIDE_ASSETS:
                self.assertEqual((dest/'guide-assets'/asset).read_bytes(),(root/'static'/asset).read_bytes())
            for path in ('features.html','en/features.html','static/showcase.css','static/site-telemetry.js'):
                self.assertTrue((dest/path).is_file(),path)
            for path in (root/'static/product').glob('*.png'):
                self.assertEqual((dest/'static/product'/path.name).read_bytes(),path.read_bytes())

    def test_upstream_requires_bare_https_origin(self):
        for origin in ('http://backend.example.com','https://name:secret@backend.example.com','https://backend.example.com/path','https://backend.example.com?x=1'):
            with self.assertRaises(ValueError):hosting_config(origin)
