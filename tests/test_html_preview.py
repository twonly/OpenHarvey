import unittest
from contract_web.html_preview import render_preview

class PreviewTests(unittest.TestCase):
    def test_visible_citations_are_decorated_without_rewriting_scripts_or_attributes(self):
        doc={'id':'aaaaaaaaaaaa','filename':'合同.pdf','source_hash':'v1','locations':{'B1':{'page':79,'preview':'报价 <原文>'},'B2':{'page':79}}}
        script='<script>const reference="【Daaaaaaaaaaaa:B1】";</script>'
        content='<h2 title="【Daaaaaaaaaaaa:B1】">条款【Daaaaaaaaaaaa:B1-B2】</h2>'+script
        result=render_preview(content,[doc],'r')
        self.assertIn('查看原文 · PDF 第79页',result)
        self.assertIn('报价 &lt;原文&gt;',result)
        self.assertIn(script,result);self.assertIn('title="【Daaaaaaaaaaaa:B1】"',result)
        self.assertIn('"block": "B1", "end": "B2"',result)
        self.assertEqual(result.count('data-workbench-reference="0"'),1)
        self.assertIn("parent.postMessage(ref,'*')",result)

    def test_ambiguous_missing_and_absurd_references_are_not_links(self):
        d={'id':'aaaaaaaaaaaa','source_hash':'v1','locations':{'B1':{'page':1}}}
        self.assertIn('来源待核对',render_preview('【B1】',[d,{**d,'id':'bbbbbbbbbbbb'}],'r'))
        for ref in ['【Daaaaaaaaaaaa:B1-B2】','【Daaaaaaaaaaaa:B'+('9'*5000)+'】']:
            self.assertNotIn('data-workbench-reference',render_preview(ref,[d],'r'))
