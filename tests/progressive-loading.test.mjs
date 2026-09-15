import {t as tr,ui} from '../static/i18n.js';
import {threadTitle} from '../static/thread-ui.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext as runVM} from 'node:vm';
const runInNewContext=(code,context)=>runVM(code,Object.assign(context,{tr,ui,threadTitle}));
const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const section=(start,end)=>app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start)));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const dom=()=>{const nodes={};return id=>nodes[id]??={innerHTML:'',hidden:false,setAttribute(k,v){this[k]=v;}};};

test('source reads share an in-flight request and an older document cannot overwrite the new one',async()=>{
 const calls=[],$=dom();
 const context={$,epoch:1,sourceEpoch:0,sourceRequest:null,source:null,sourceRendered:false,tid:'thread',state:{documents:[]},viewRequests:new AbortController(),sourceNavigation:{setDocument(){}},quotes:{hide(){}},loadingHTML:s=>s,esc:s=>s,renderDocs(){},renderSource:async()=>{},api:()=>{const gate=deferred();calls.push(gate);return gate.promise;}};
 runInNewContext(section('async function loadSource(','\nasync function renderSource'),context);
 const a=context.loadSource('a'),duplicate=context.loadSource('a');assert.equal(calls.length,1);
 const b=context.loadSource('b');assert.equal(calls.length,2);
 calls[1].resolve({id:'b'});await b;assert.equal(context.source.id,'b');assert.equal($('sourceContent')['aria-busy'],'false');
 calls[0].resolve({id:'a'});await Promise.all([a,duplicate]);assert.equal(context.source.id,'b');
 const failed=context.loadSource('c');calls[2].reject(new Error('offline'));await assert.rejects(failed,/offline/);
 assert.match($('sourceContent').innerHTML,/data-source-retry="c"/);assert.equal($('sourceContent')['aria-busy'],'false');
 const retry=context.loadSource('c');calls[3].resolve({id:'c'});await retry;assert.equal(context.source.id,'c');
});

test('restoring history completes even while source, artifacts, and seen acknowledgement remain pending',async()=>{
 const pending=new Promise(()=>{}),jobs=[],$=dom();
 const context={$,epoch:1,restoring:false,restoreEpoch:0,buffer:[],state:{},tid:'t',source:null,sourceRequest:null,sourceRendered:false,viewRequests:new AbortController(),workspace:{threads:[{id:'t'}]},threadFilter:'active',
  api:async()=>({title:'ready',documents:[{id:'doc',thread_id:null}],messages:[]}),updateControls(){},reconcilePending(){},renderSkills(){},messageIssue(){},renderQueue(){},renderMessages(){},renderRequests(){},renderDocs(){},notice(){},refreshWorkspace:()=>pending,markThreadSeen:()=>pending,refreshThreadActivity(){},threadScope:()=> 'active',loadSource:()=>pending,background:job=>jobs.push(job)};
 runInNewContext(section('async function restore(','\nfunction receive'),context);
 await context.restore();assert.equal(context.state.loaded,true);assert.equal(context.restoring,false);assert.equal(jobs.length,3);
});

test('Word preview starts without opening a document, shares its pending load, and retries failure',async()=>{
 const source=readFileSync(new URL('../static/word-preview.js',import.meta.url),'utf8').replace(/^import .*$/gm,'').replaceAll('export ','');
 const nodes=[],renders=[],window={};const context={window,document:{createElement:()=>({remove(){}}),head:{append:n=>nodes.push(n)}}};
 runInNewContext(source,context);
 const first=context.prepareWordPreview();assert.match(nodes[0].src,/jszip/);assert.equal(renders.length,0);nodes[0].onerror();await assert.rejects(first,/组件加载失败/);
 const preparing=context.prepareWordPreview();const a=context.renderWord('a',{}),b=context.renderWord('b',{});assert.equal(nodes.length,2);
 window.JSZip={};nodes[1].onload();await new Promise(setImmediate);assert.equal(nodes.length,3);assert.match(nodes[2].src,/docx-preview/);
 window.docx={renderAsync:async blob=>renders.push(blob)};nodes[2].onload();await Promise.all([preparing,a,b]);assert.deepEqual(renders,['a','b']);
});
