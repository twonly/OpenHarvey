import test from 'node:test';
import assert from 'node:assert/strict';
import {activeDocuments,sourceReferencesHTML} from '../static/materials-ui.js';

test('available materials exclude removed and historical sources, citations retain their identity',()=>{
  const docs=[
    {id:'aaaaaaaaaaaa',filename:'主合同.txt',source_hash:'a',primary:true,locations:{B0:{ordinal:1}}},
    {id:'bbbbbbbbbbbb',filename:'<报价>.txt',source_hash:'b',removed_at:1,thread_id:'t',locations:{B0:{ordinal:1}}},
    {id:'cccccccccccc',filename:'过去资料.txt',source_hash:'c',historical_only:true,locations:{B0:{ordinal:1}}}
  ];
  assert.deepEqual(activeDocuments(docs).map(d=>d.id),['aaaaaaaaaaaa']);
  const html=sourceReferencesHTML('依据【Dbbbbbbbbbbbb:B0】和【Dbbbbbbbbbbbb:B0】，错误位置【Daaaaaaaaaaaa:B4】',docs);
  assert.match(html,/引用来源.*1/);assert.match(html,/&lt;报价&gt;/);assert.match(html,/已移除/);
  assert.match(html,/data-doc="bbbbbbbbbbbb"/);assert.doesNotMatch(html,/data-doc="aaaaaaaaaaaa"/);
  assert.equal(sourceReferencesHTML('资料均可用，未提供引用',docs),'');
});
