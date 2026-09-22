import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {webcrypto} from 'node:crypto';
const code=fs.readFileSync(new URL('../static/redline.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,'').replace('export class RedlineEditor','class RedlineEditor')+'\nthis.RedlineEditor=RedlineEditor;';
function editor(api){
 const frames=new Map();let frameId=0;const document={hidden:false};const context={document,console,api,esc:s=>s,crypto:webcrypto,Blob,window:{addEventListener(){}},requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),setTimeout,clearTimeout,setInterval,clearInterval};vm.createContext(context);vm.runInContext(code,context);
 const r=new context.RedlineEditor({onError(){}});Object.assign(r,{documentId:'doc',threadId:'thread',version:'v1',ready:true,owned:true,editor:{export:async()=>new Blob(['docx'])},status(){},render(){},testDocument:document,loadFile:async()=>new Blob(),runFrames(){const pending=[...frames.values()];frames.clear();pending.forEach(f=>f());}});return r;
}
test('uncertain save retries exactly the same blob, operation ID and base version',async()=>{
 const requests=[];let fail=true;
 const r=editor(async(path,o)=>{if(!o)return {version:{id:'v2'}};requests.push(o);if(fail){fail=false;throw Error('connection lost');}return {saved:true,version_id:'v2'};});
 r.generation++;await assert.rejects(r.flush(),/connection lost/);assert.equal(r.dirty,true);assert.ok(r.pending);
 await r.flush();assert.equal(r.dirty,false);assert.equal(requests[0].body,requests[1].body);assert.deepEqual(requests[0].headers,requests[1].headers);assert.equal(r.version,'v2');
});
test('edits during save are flushed as a second version, never marked saved by first receipt',async()=>{
 let release;const gate=new Promise(resolve=>release=resolve);let calls=0;const bases=[];
 const r=editor(async(path,o)=>{if(!o)return {version:{id:'v3'}};calls++;bases.push(o.headers['X-Document-Version']);if(calls===1)await gate;return {saved:true,version_id:calls===1?'v2':'v3'};});
 r.generation++;const saving=r.flush();await new Promise(resolve=>setImmediate(resolve));r.generation++;release();await saving;
 assert.equal(calls,2);assert.deepEqual(bases,['v1','v2']);assert.equal(r.savedGeneration,2);assert.equal(r.dirty,false);
});
test('version conflict keeps browser edits and the failed save request',async()=>{
 const r=editor(async()=>{throw Object.assign(Error('version changed'),{status:409});});r.generation++;
 await assert.rejects(r.flush(),/version changed/);assert.equal(r.version,'v1');assert.ok(r.pending);assert.equal(r.dirty,true);
});

test('image, collapsed and table selections clear a previous clause target',()=>{
 const r=editor(()=>{});let reads=0;
 const active={state:{selection:{empty:false}},doc:{selection:{current:()=>{reads++;return {empty:false,text:'付款期限',target:{id:'clause'}};}}}};
 r.editor.activeEditor=active;r.selectionChanged();assert.equal(r.selection.text,'付款期限');
 for(const selection of [{empty:false,node:{}},{empty:true},{empty:false,$anchorCell:{}}]){
  active.state.selection=selection;r.selectionChanged();assert.equal(r.selection,null);
 }
 assert.equal(reads,1);
});
test('occupied document remains read-only and retries without stealing a lease',async()=>{
 const r=editor(async()=>{throw Object.assign(Error('another editor'),{status:409});});r.owned=false;
 await r.heartbeat();assert.equal(r.owned,false);assert.equal(r.lockMessage,'another editor');
});
test('reacquiring a changed remote version never discards unsaved local edits',async()=>{
 const r=editor(async(path,o)=>o?{}:{version:{id:'remote-v2'}});r.owned=false;r.generation++;let mounted=false;
 r.mount=async()=>{mounted=true;};r.editor.setDocumentMode=()=>{};
 await assert.rejects(r.heartbeat(),/本地改动保留/);assert.equal(mounted,false);assert.equal(r.version,'v1');assert.equal(r.dirty,true);assert.equal(r.owned,false);
});
test('reacquiring the same version saves pending edits before reporting saved',async()=>{
 const events=[];let version='v1';
 const r=editor(async(path,o)=>{if(o?.method==='PUT'){events.push('receipt');version='v2';return {saved:true,version_id:version};}return o?{}:{version:{id:version}};});
 r.owned=false;r.generation++;r.editor.setDocumentMode=()=>{};r.status=t=>events.push(t);
 await r.heartbeat();assert.equal(r.dirty,false);assert.ok(events.indexOf('receipt')<events.indexOf('已保存'));
});
test('hidden editor flushes before releasing its lease',async()=>{
 const events=[];const r=editor(async(path,o)=>{if(o?.method==='PUT'){events.push('save');return {saved:true,version_id:'v2'};}if(o?.body?.release)events.push('release');return {version:{id:'v2'}};});
 r.testDocument.hidden=true;r.editor.setDocumentMode=()=>{};r.generation++;
 await r.visibilityChanged();assert.deepEqual(events,['save','release']);assert.equal(r.owned,false);
});
test('failed background save retains the lease and local edits',async()=>{
 const r=editor(async()=>{throw Error('offline');});r.testDocument.hidden=true;r.editor.setDocumentMode=()=>{};r.generation++;
 await assert.rejects(r.visibilityChanged(),/offline/);assert.equal(r.owned,true);assert.equal(r.dirty,true);assert.ok(r.pending);
});
test('source search highlights stay scoped away from SuperDoc image selection',()=>{
 const css=fs.readFileSync(new URL('../static/app.css',import.meta.url),'utf8');
 assert.doesNotMatch(css,/(?:^|[},])\s*::highlight\(/m);
 assert.match(css,/#sourceContent::highlight\(source-search\)/);
});

test('read-only mode and selection transactions never start a document save',()=>{
 const r=editor(()=>{});let changes=0;r.changed=()=>changes++;
 r.editorTransaction({transaction:{docChanged:false}});r.editorTransaction({});
 assert.equal(changes,0);
 r.editorTransaction({transaction:{docChanged:true}});assert.equal(changes,1);
});

test('saved DOCX links render only scoped immutable download URLs',async()=>{
 const {markdown}=await import('../static/markdown.js');
 const did='a'.repeat(12),tid='b'.repeat(24),vid='c'.repeat(24),url=`/api/redline/${did}/file?thread_id=${tid}&version_id=${vid}`;
 assert.match(markdown(`[合同.docx](${url})`,[{id:did}]),/<a href=/);
 assert.doesNotMatch(markdown(`[合同.docx](${url})`,[]),/<a href=/);
 assert.doesNotMatch(markdown('[点击](javascript:alert(1))',[{id:did}]),/<a href=/);
 assert.doesNotMatch(markdown(`[合同](${url}&extra=bad)`,[{id:did}]),/<a href=/);
});

test('review navigation checks engine success and never starts a save',async()=>{
 const r=editor(()=>{});let success=false,active=0;r.showReview=()=>{};r.scrollReviewCard=()=>{};
 r.ui={trackChanges:{scrollTo:async()=>({success}),setActive:()=>{active++;return true;}}};
 await assert.rejects(r.locateReview('changes','change-a'),/无法定位/);assert.equal(active,0);assert.equal(r.dirty,false);
 success=true;await r.locateReview('changes','change-a');assert.equal(r.reviewFocus.id,'change-a');assert.equal(active,1);assert.equal(r.dirty,false);
});
test('late comment navigation cannot replace a newer selected card',async()=>{
 const r=editor(()=>{});let finish;const activated=[];r.showReview=()=>{};r.scrollReviewCard=()=>{};
 r.ui={comments:{scrollTo:id=>id==='a'?new Promise(resolve=>finish=resolve):Promise.resolve({success:true}),setActive:id=>{activated.push(id);return true;}}};
 const old=r.locateReview('comments','a');await r.locateReview('comments','b');finish({success:true});await old;
 assert.equal(r.reviewFocus.id,'b');assert.deepEqual(activated,['b']);
 r.reviewChanged('comments',null);assert.equal(r.reviewFocus.id,'b');
 r.reviewPinned=false;r.reviewChanged('comments',null);assert.equal(r.reviewFocus,null);
});
test('document review selection follows a card once without repeatedly reopening the panel',()=>{
 const r=editor(()=>{});let opens=0,scrolls=0;r.showReview=()=>opens++;r.scrollReviewCard=()=>scrolls++;
 r.reviewChanged('changes','a');r.reviewChanged('changes','a');r.reviewChanged('comments',null);
 r.runFrames();assert.equal(opens,1);assert.equal(scrolls,1);assert.equal(r.reviewFocus.id,'a');
 r.reviewChanged('changes',null);assert.equal(r.reviewFocus,null);assert.equal(r.dirty,false);
});
test('Agent handoff locates only a newly saved operation using native author association',async()=>{
 const state={version:{id:'v2'},operations:[{operation_id:'new',author_email:'agent-new'},{operation_id:'old',author_email:'agent-old'}]};
 const r=editor(async(path,o)=>o?{}:state);r.owned=false;r.state={operations:[{operation_id:'old'}]};
 r.mount=async()=>{};r.list=()=>[{id:'old-revision',authorEmail:'agent-old'},{id:'new-revision',authorEmail:'agent-new'}];
 const located=[];r.locateReview=async(kind,id)=>located.push([kind,id]);
 await r.heartbeat();assert.deepEqual(located,[['changes','new-revision']]);assert.equal(r.dirty,false);
});
test('revision context is shown only for an unambiguous matching Agent operation',()=>{
 const r=editor(()=>{});r.state={operations:[{author_email:'agent-a',changes:[{quote:'付款期限为30天',replacement:'付款期限为60天'}]}]};
 const change={authorEmail:'agent-a',deletedText:'30',insertedText:'60'};
 assert.equal(r.changeContext(change),'付款期限为30天');assert.equal(r.changeContext({...change,authorEmail:'other'}),'');
 r.state.operations[0].changes.push({quote:'第二处付款30天',replacement:'第二处付款60天'});assert.equal(r.changeContext(change),'');
});

test('imported and synthetic review notifications do not save; authored comments do',()=>{
 const r=editor(()=>{});
 for(const event of [{type:'add',comment:{commentId:'imported',docxCommentJSON:[{}]}},{type:'add',comment:{trackedChange:true}},{type:'update',comment:{trackedChange:true}},{type:'comments-list'},{type:'selected'}])r.commentsUpdated(event);
 assert.equal(r.dirty,false);assert.equal(r.saveTimer,undefined);
 for(const event of [{type:'add',comment:{commentId:'new'}},{type:'update',comment:{docxCommentJSON:[{}]}},{type:'resolved'},{type:'deleted'},{type:'add',comment:{commentId:'imported',docxCommentJSON:[{}]}}])r.commentsUpdated(event);
 assert.equal(r.generation,5);clearTimeout(r.saveTimer);
});
test('review updates coalesce per frame and never rebuild unchanged or hidden lists',()=>{
 const r=editor(()=>{});delete r.render;r.state={operations:[]};let writes=0,reads=0,open=false;
 const node={textContent:'',setAttribute(){},classList:{toggle(){}},hidden:false};
 const target={set innerHTML(value){writes++;},append(){}};
 r.host={classList:{contains:()=>open},querySelector:s=>s==='[data-redline-list]'?target:node,querySelectorAll:()=>[]};
 r.ui={trackChanges:{getSnapshot:()=>{reads++;return {items:[]};}}};
 for(let i=0;i<20;i++)r.reviewChanged('changes',null);
 r.runFrames();assert.equal(writes,0);assert.equal(reads,1);
 open=true;r.render();assert.equal(writes,1);
 for(let i=0;i<20;i++){r.reviewChanged('changes',null);r.runFrames();}
 assert.equal(writes,1);assert.equal(reads,1);
 r.changed();r.runFrames();assert.equal(writes,2);assert.equal(reads,2);clearTimeout(r.saveTimer);
});
test('composition defers automatic export while explicit flush still persists',async()=>{
 let saves=0;const r=editor(async(path,o)=>{if(o?.method==='PUT'){saves++;return {saved:true,version_id:'v2'};}return {version:{id:'v2'}};});
 r.composing=true;r.changed();assert.equal(r.saveTimer,undefined);assert.equal(r.dirty,true);
 await r.flush();assert.equal(saves,1);assert.equal(r.dirty,false);
});
test('failed Agent version download retains the current editor and version',async()=>{
 const r=editor(async(path,o)=>o?{}:{version:{id:'v2'},operations:[]});r.state={operations:[]};r.owned=false;r.editor.setDocumentMode=()=>{};
 r.loadFile=async()=>{throw Error('download interrupted');};let mounts=0;r.mount=async()=>mounts++;
 await assert.rejects(r.heartbeat(),/download interrupted/);assert.equal(r.version,'v1');assert.equal(mounts,0);
});
test('Agent handoff waits until an active composition finishes',async()=>{
 let requests=0;const r=editor(async()=>{requests++;return {};});r.composing=true;
 await r.heartbeat();assert.equal(requests,0);assert.equal(r.owned,true);
});
test('prefetching a replacement makes the old editor read-only and blocks review writes',async()=>{
 const r=editor(()=>{});let finish,mode;
 r.editor.setDocumentMode=value=>mode=value;r.mountDocument=()=>new Promise(resolve=>finish=resolve);
 const mounting=r.mount(new Blob());assert.equal(mode,'viewing');assert.equal(r.loading,true);
 await assert.rejects(r.click({dataset:{rAccept:'revision'}}),/正在加载/);
 finish();await mounting;assert.equal(r.loading,false);
});
