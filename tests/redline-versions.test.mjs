import test from 'node:test';
import assert from 'node:assert/strict';
import {groupVersions,groupTitle,versionHistoryHTML} from '../static/redline-versions.js';
const base={kind:'edit',actor_id:'alice',thread_id:'thread',author:'Alice',summary:'编辑合同正文',details:{},label:'',label_revision:0};
const history=()=>[0,1,2].map(i=>({...base,id:String(3-i),parent_id:String(2-i),created:1790057762-i*60}));
test('continuous saves fold without losing a snapshot or mutating history',()=>{
 const input=history(),copy=structuredClone(input),groups=groupVersions(input);
 assert.equal(groups.length,1);assert.equal(groups[0].length,3);assert.deepEqual(input,copy);assert.equal(groupTitle(groups[0]),'连续编辑合同');
});
test('important versions, actors, threads, Agent operations, restores and missing lineage split groups',()=>{
 for(const patch of [{label:'初审稿'},{actor_id:'bob'},{thread_id:'other'},{kind:'agent'},{kind:'restore'},{kind:'legacy'},{thread_id:null},{id:'unrelated'},{created:1790050000}]){
  const input=history();Object.assign(input[1],patch);assert.equal(groupVersions(input)[0].length,1,JSON.stringify(patch));
 }
});
test('review summaries use decision counts and remain separate from text edits',()=>{
 const input=history().map(v=>({...v,kind:'review',details:{accept:2,reject:1}}));
 assert.equal(groupTitle(groupVersions(input)[0]),'接受 6 处修订，拒绝 3 处修订');
 input[1].kind='edit';assert.equal(groupVersions(input).length,3);
});
test('history escapes names, retains all downloads and filters only marked versions',()=>{
 const versions=history();versions[1].label='<img src=x onerror=alert(1)>';
 const options={current:'3',fileURL:id=>'/file?version='+id};
 const html=versionHistoryHTML(versions,options);
 assert.doesNotMatch(html,/<img/);for(const v of versions)assert.ok(html.includes('/file?version='+v.id));
 const marked=versionHistoryHTML(versions,{...options,important:true});assert.ok(marked.includes('/file?version=2'));assert.ok(!marked.includes('/file?version=3'));
 assert.ok(html.includes('恢复为当前工作稿'));assert.ok(html.includes('data-label-revision="0"'));
});
test('preview opens its folded group and large histories initially show twenty groups',()=>{
 const input=history(),options={current:'3',preview:'2',fileURL:id=>'/file?version='+id};
 const html=versionHistoryHTML(input,options);assert.match(html,/redline-version-saves" open/);assert.ok(html.includes('正在查看'));
 const many=Array.from({length:30},(_,i)=>({...base,id:String(i),created:1790057762-i*300}));
 const page=versionHistoryHTML(many,{...options,preview:null});assert.ok(page.includes('显示更多记录'));assert.ok(!page.includes('/file?version=29'));
});
