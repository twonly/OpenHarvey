import json
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contract_web.marketing import register_marketing
from contract_web.product_showcase import FEATURES

class Metadata(HTMLParser):
    def __init__(self,html):
        super().__init__();self.links=[];self.meta=[];self.scripts=[];self.capture=False;self.current='';self.lang=None;self.feed(html)
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='html':self.lang=values.get('lang')
        if tag=='link':self.links.append(values)
        if tag=='meta':self.meta.append(values)
        if tag=='script' and values.get('type')=='application/ld+json':self.capture=True;self.current=''
    def handle_data(self,data):
        if self.capture:self.current+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.capture:self.scripts.append(json.loads(self.current));self.capture=False

class MarketingTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();page=register_marketing(app,None)
        app.add_api_route('/',lambda:page(),methods=['GET'])
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def test_sitemap_targets_are_bilingual_canonical_and_have_valid_schema(self):
        tree=ET.fromstring(self.client.get('/sitemap.xml').text)
        urls=[node.text for node in tree.findall('{*}url/{*}loc')]
        self.assertEqual(len(urls),10)
        for url in urls:
            path=url.removeprefix('https://openharvey.com')
            response=self.client.get(path);self.assertEqual(response.status_code,200)
            metadata=Metadata(response.text)
            self.assertEqual(metadata.lang,'en' if path.startswith('/en') else 'zh-CN')
            self.assertIn({'rel':'canonical','href':url},metadata.links)
            self.assertEqual({x['hreflang'] for x in metadata.links if x.get('rel')=='alternate'},{'zh-CN','en','x-default'})
            self.assertTrue(metadata.scripts)
        self.assertEqual(self.client.get('/en/',follow_redirects=False).status_code,308)

    def test_each_public_page_has_a_unique_description_within_bing_limits(self):
        descriptions=[]
        for path in ('/','/en','/security','/en/security','/open-source','/en/open-source',
                     '/harvey-alternative','/en/harvey-alternative','/features','/en/features'):
            metadata=Metadata(self.client.get(path).text)
            description=next(item['content'] for item in metadata.meta if item.get('name')=='description')
            self.assertGreaterEqual(len(description),25,path)
            self.assertLessEqual(len(description),160,path)
            descriptions.append(description)
        self.assertEqual(len(set(descriptions)),len(descriptions))
    def test_private_endpoints_excluded_from_index_and_public_pages_state_boundaries(self):
        robots=self.client.get('/robots.txt').text
        for private in ('/api/','/agent','/auth/','/traces','/trial-model/'):
            self.assertIn('Disallow: '+private,robots)
        self.assertIn('primarily Chinese',self.client.get('/en').text)
        self.assertIn('not affiliated',self.client.get('/en/harvey-alternative').text)
        self.assertIn('remote models',self.client.get('/en/security').text)

    def test_product_screenshots_have_bilingual_copy_and_structured_features(self):
        for path,lang in (('/features','zh'),('/en/features','en')):
            body=self.client.get(path).text
            self.assertEqual(body.count('<article class="showcase-feature"'),5)
            self.assertEqual(body.count('loading="lazy"'),5)
            for feature in FEATURES:
                self.assertIn('/static/product/'+feature['image'],body)
                self.assertIn(feature[lang][0],body)
                self.assertIn('alt="'+feature[lang][3]+'"',body)
            application=next(s for s in Metadata(body).scripts if s['@type']=='SoftwareApplication')
            self.assertEqual(len(application['screenshot']),5)
            self.assertEqual(len(application['featureList']),5)
        zh=self.client.get('/features').text
        for value in ('10 次','20 次','兼容 OpenAI','已保存','供应商','合同摘要','合同风险审查','条款修改'):
            self.assertIn(value,zh)
        self.assertIn('not internal model calls',self.client.get('/en/features').text)
        for path in ('/','/en'):
            body=self.client.get(path).text
            self.assertIn('class="showcase-grid"',body)
            self.assertNotIn('href="https://agent.tokrace.com',body)
