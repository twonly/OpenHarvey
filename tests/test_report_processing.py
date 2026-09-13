import unittest
from contract_web.report_processing import merge_citations, marker, process_report
from contract_web.documents import validate_citations
from contract_web.presentation import PublicView
from contract_web.runtime import visible_event


class CitationProcessingTests(unittest.TestCase):
    def test_adjacent_overlap_duplicate_and_idempotence(self):
        d='aaaaaaaaaaaa'
        text='依据：'+marker(d,935)+marker(d,936)+' '+marker(d,937)+marker(d,938)+marker(d,938)
        self.assertEqual(merge_citations(text),'依据：'+marker(d,935,938))
        self.assertEqual(merge_citations(merge_citations(text)),merge_citations(text))
        self.assertEqual(merge_citations(marker(d,5,8)+marker(d,7,10)),marker(d,5,10))
        bridged=marker(d,1)+marker(d,3)+marker(d,2)
        self.assertEqual(merge_citations(bridged),marker(d,1,3))
        self.assertEqual(merge_citations(merge_citations(bridged)),marker(d,1,3))

    def test_do_not_merge_gaps_documents_or_separate_claims(self):
        d='aaaaaaaaaaaa'
        for value in [marker(d,1)+marker(d,3),marker(d,1)+'。'+marker(d,2),
                      marker(d,1)+'\n'+marker(d,2),marker(d,1)+'解释'+marker(d,2),
                      marker(d,1)+marker('bbbbbbbbbbbb',2)]:
            self.assertEqual(merge_citations(value),value)

    def test_ranges_are_validated_and_evidence_not_rewritten(self):
        d='aaaaaaaaaaaa';maps={d:{'segments':[{}, {}, {}]}}
        validate_citations(marker(d,0,2),maps)
        for value in [marker(d,0,3),marker(d,2,1)]:
            with self.assertRaises(ValueError):validate_citations(value,maps)
        evidence=[{'document_id':d,'source_hash':'v1','block_id':'B'+str(i),'quote':'段落'+str(i)} for i in [1,2]]
        body={'kind':'review','content':marker(d,1)+marker(d,2),'findings':[{'risk_id':'R','reason':marker(d,1)+marker(d,2),'evidence':evidence}]}
        result=process_report(body,[{'id':'R','name':'付款'}])
        self.assertEqual(result['findings'][0]['evidence'],evidence)
        self.assertEqual(result['findings'][0]['evidence_groups'][0]['end'],2)
        self.assertNotIn('evidence_groups',body['findings'][0])
        self.assertEqual(process_report({**body,'format':'html'},[])['content'],body['content'])
        custom={'kind':'document','format':'json','content':'{}','findings':{'custom':'data'}}
        self.assertEqual(process_report(custom,[])['findings'],custom['findings'])

    def test_native_text_deltas_use_same_deterministic_processing(self):
        view=PublicView();known=set();d='aaaaaaaaaaaa'
        part={'id':'p','sessionID':'s','messageID':'m','type':'text','text':marker(d,1)}
        visible_event({'type':'message.part.updated','properties':{'part':part}},'s',known,view)
        event=visible_event({'type':'message.part.delta','properties':{'sessionID':'s','partID':'p','field':'text','delta':marker(d,2)}},'s',known,view)
        self.assertEqual(event['properties']['part']['text'],marker(d,1,2))

    def test_relative_native_permission_paths_use_the_same_public_alias(self):
        view=PublicView({'/private/var/run/demo/threads/current':'本次对话'})
        for path in ['/private/var/run/demo/threads/current/draft.md','private/var/run/demo/threads/current/draft.md']:
            self.assertEqual(view.text(path),'本次对话/draft.md')

    def test_web_sources_survive_path_redaction_in_snapshots_and_streams(self):
        view=PublicView({'/work/contracts':'合同材料'})
        text='来源 [网页](https://example.com/work/contracts/home?q=1)；本地 /work/contracts/a.txt'
        self.assertEqual(view.text(text),'来源 [网页](https://example.com/work/contracts/home?q=1)；本地 合同材料/a.txt')
        self.assertEqual(view.text('C:/private/file.txt'),'工作文件/file.txt')
        known=set()
        part={'id':'p','sessionID':'s','messageID':'m','type':'text','text':'https:'}
        visible_event({'type':'message.part.updated','properties':{'part':part}},'s',known,view)
        event=visible_event({'type':'message.part.delta','properties':{'sessionID':'s','partID':'p','field':'text','delta':'//opencode.ai/docs/tools/'}},'s',known,view)
        self.assertEqual(event['properties']['part']['text'],'https://opencode.ai/docs/tools/')
