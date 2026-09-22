import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
function setup(){
 const calls=[];
 const c={calls,document:{hidden:false},settingsUI:{isOpen:()=>c.settingsOpen},settingsOpen:false,settingsTab:p=>p==='/agent'?null:'settings',location:{pathname:'/agent'},
 workspace:{id:'w',threads:[{id:'t'}]},tid:'t',epoch:1,workbenchRevision:0,activityPolling:false,lastActivityPoll:0,activityWorkspace:null,queuePolling:false,switching:false,threadManaging:false,restoring:false,lastQueuePoll:0,lastTrialRefresh:Date.now(),modelSaving:false,
 state:{status:{type:'idle'},queue:{items:[]},completion_id:'done'},setInterval(){},$:()=>({querySelector:()=>null,open:false}),renderWorkspace(){calls.push('renderWorkspace');},restore:async()=>{calls.push('restore');},api:async path=>{calls.push(path);return path.endsWith('thread-status')?[]:{items:[]};},refreshTrialUsage:async()=>{},reconcilePending(){},renderQueue(){},renderMessages(){},updateControls(){}};
 runInNewContext(section('function workbenchVisible(',"document.addEventListener('visibilitychange'"),c);
 runInNewContext(section('async function refreshThreadActivity(','async function selectWorkspace('),c);
 runInNewContext(section('async function refreshQueue(','function setSkill('),c);
 return c;
}
test('settings routes and hidden tabs suppress both polls and seen writes',async()=>{
 for(const condition of ['settings','route','hidden']){
  const c=setup();if(condition==='settings')c.settingsOpen=true;if(condition==='route')c.location.pathname='/skills';if(condition==='hidden')c.document.hidden=true;
  await c.refreshQueue(true);await c.refreshThreadActivity();await c.markThreadSeen(1);assert.deepEqual(c.calls,[]);
 }
});
test('late responses cannot render or restore after a settings visit',async()=>{
 for(const kind of ['queue','activity']){
  const c=setup();let resolve;c.api=()=>new Promise(r=>{resolve=r;});
  const pending=kind==='queue'?c.refreshQueue(true):c.refreshThreadActivity();
  c.workbenchRevision++;resolve(kind==='queue'?{active:true,items:[]}:[{id:'t',activity:'completed',completion_id:'new'}]);await pending;
  assert.deepEqual(c.calls,[]);assert.equal(c.state.queue.active,undefined);assert.equal(c.workspace.threads[0].activity,undefined);
  assert.equal(c.queuePolling,false);assert.equal(c.activityPolling,false);
 }
});
test('returning restores immediately and bypasses idle polling delay',async()=>{
 const c=setup();c.lastQueuePoll=Date.now();await c.resumeWorkbench();
 assert.equal(c.calls[0],'restore');assert.ok(c.calls.includes('/api/threads/t/queue'));assert.ok(c.calls.includes('/api/workspaces/w/thread-status'));
});
test('completed visible thread still restores its latest result',async()=>{
 const c=setup();c.api=async()=>[{id:'t',activity:'completed',completion_id:'new'}];await c.refreshThreadActivity();assert.ok(c.calls.includes('restore'));
});
test('idle activity polling backs off and active work restores the short interval',async()=>{
 const c=setup();await c.refreshThreadActivity();await c.refreshThreadActivity();
 assert.equal(c.calls.filter(p=>p==='/api/workspaces/w/thread-status').length,1);
 c.lastActivityPoll=Date.now()-4000;c.state.status={type:'busy'};await c.refreshThreadActivity();
 assert.equal(c.calls.filter(p=>p==='/api/workspaces/w/thread-status').length,2);
 c.state.status={type:'idle'};c.lastActivityPoll=Date.now()-16000;await c.refreshThreadActivity();
 assert.equal(c.calls.filter(p=>p==='/api/workspaces/w/thread-status').length,3);
});
