import {threadListHTML} from '../static/thread-ui.js';
import {accountLabel,accountIdentityHTML} from '../static/account-identity.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {applyEvent,runIssue,unchangedEvent} from '../static/events.js';
import {markdown} from '../static/markdown.js';
import {addDiscoveredModel,waitForOperation} from '../static/provider-utils.js';

test('reading toolbar keeps modes left and ordered actions at the right',()=>{
 const html=readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
 const doc=html.split('id="documentToolbar"')[1].split('id="sourceTools"')[0];
 const art=html.split('class="artifact-actions"')[1].split('id="artifactPair"')[0];
 const ordered=(text,tokens)=>{const positions=tokens.map(x=>text.indexOf(x));assert.ok(positions.every(x=>x>=0));assert.deepEqual([...positions].sort((a,b)=>a-b),positions);};
 ordered(doc,['class="source-mode"','class="document-actions"','id="sourceOutlineToggle"','id="sourceSearchToggle"','id="documentMore"','data-close-pane="source"','aria-label="放大合同文档"']);
 ordered(art,['id="artifactMore"','data-close-pane="artifact"','aria-label="放大产出物"']);
});

test('registered identity shows email safely and never sends it to an avatar service',()=>{
 const user={account_kind:'personal',username:'user-b2bab2208ca70844',email:'sample@example.com'};
 assert.equal(accountLabel(user),user.email);
 const html=accountIdentityHTML({...user,email:'<script>@example.com'});
 assert.ok(html.includes('&lt;script&gt;@example.com'));assert.ok(!html.includes('<script>'));
 assert.ok(html.includes('/static/brand/avatar-lucide.svg'));assert.ok(!html.includes('https://'));
 assert.equal(accountLabel({account_kind:'demo',username:'demo-hidden'}),'访客');
 assert.equal(accountLabel({username:'admin'}),'admin');
});

test('demo spinner remains visible during both loading stages and stops on failure or captcha',async()=>{
 const {runInNewContext}=await import('node:vm');
 const source=readFileSync(new URL('../static/demo.js',import.meta.url),'utf8').replace(/^import .*;\n/,'');
 const elements={status:{textContent:''},startDemo:{hidden:true},demoSpinner:{hidden:false}};
 const calls=[];let destination;
 const context={document:{getElementById:id=>elements[id]},location:{replace:url=>destination=url},api:path=>new Promise((resolve,reject)=>calls.push({path,resolve,reject}))};
 const tick=()=>new Promise(resolve=>setImmediate(resolve));
 runInNewContext(source,context);
 assert.equal(elements.demoSpinner.hidden,false);assert.equal(calls[0].path,'/api/demo/start');
 calls[0].resolve({});await tick();assert.equal(calls[1].path,'/api/demo/workspace');assert.equal(elements.demoSpinner.hidden,false);
 calls[1].reject(Object.assign(new Error('请先完成人机验证'),{status:403}));await tick();
 assert.equal(elements.demoSpinner.hidden,true);assert.equal(elements.startDemo.hidden,false);assert.equal(calls[2].path,'/api/auth/config');
 calls[2].resolve({});await tick();
 const retry=elements.startDemo.onclick();assert.equal(elements.demoSpinner.hidden,false);assert.equal(elements.startDemo.hidden,true);
 calls[3].resolve({});await tick();calls[4].resolve({workspace_id:'demo-test'});await retry;
 assert.equal(destination,'/agent#demo-test');assert.equal(elements.demoSpinner.hidden,false);
 const css=readFileSync(new URL('../static/account-ui.css',import.meta.url),'utf8');
 assert.ok(css.includes('@media(prefers-reduced-motion:reduce){.demo-spinner{animation:none}}'));
});

test('discovered models fill a blank row, preserve manual configuration and do not duplicate IDs',()=>{
 const existing=[{id:'custom/one',label:'业务模型',context:200000,output:16000,enabled:false,native:{reasoning:true}},
  {id:'',label:'我的模型',context:96000,output:4096,enabled:true}];
 const next=addDiscoveredModel(existing,'vendor/two');
 assert.deepEqual(next[0],existing[0]);assert.equal(next[1].id,'vendor/two');assert.equal(next[1].label,'我的模型');assert.equal(next[1].context,96000);
 assert.equal(existing[1].id,'');assert.deepEqual(addDiscoveredModel(next,'vendor/two'),next);
 assert.equal(addDiscoveredModel(next,'vendor/three').length,3);
});

test('a connection test completes independently while configuration application is still running',async()=>{
 let release;const gate=new Promise(resolve=>release=resolve);
 const applying=waitForOperation('apply',{read:()=>gate});
 let reads=0;
 const test=await waitForOperation('test',{read:async()=>++reads===1?{status:'running'}:{status:'completed',result:{message:'ok'}},pause:async()=>{}});
 assert.equal(test.status,'completed');release({status:'completed'});await applying;
});

test('operation polling surfaces failure and timeout, and stops when its editor is gone',async()=>{
 assert.equal((await waitForOperation('failed',{read:async()=>({status:'failed',result:{message:'认证失败'}})})).result.message,'认证失败');
 await assert.rejects(waitForOperation('stalled',{read:async()=>({status:'running'}),pause:async()=>{},limit:2}),/查询超时/);
 await assert.rejects(waitForOperation('network',{read:async()=>{throw Error('网络断开')}}),/网络断开/);
 assert.equal(await waitForOperation('closed',{read:()=>{throw Error('不应读取')},active:()=>false}),null);
});

test('native updates and deltas rebuild a message without duplicate parts',()=>{
  const s={messages:[]};
  applyEvent(s,{type:'message.updated',properties:{info:{id:'m1',role:'assistant'}}});
  applyEvent(s,{type:'message.part.updated',properties:{part:{id:'p1',messageID:'m1',type:'text',text:'合同'}}});
  applyEvent(s,{type:'message.part.delta',properties:{messageID:'m1',partID:'p1',field:'text',delta:'总价'}});
  assert.equal(s.messages[0].parts[0].text,'合同总价');
  applyEvent(s,{type:'message.part.updated',properties:{part:{id:'p1',messageID:'m1',type:'text',text:'合同总价128000元'}}});
  assert.equal(s.messages[0].parts.length,1);
  assert.equal(s.messages[0].parts[0].text,'合同总价128000元');
});

test('native compaction summary remains unchanged in frontend state and conversation',()=>{
  const s={messages:[],documents:[],status:{type:'busy'}};
  applyEvent(s,{type:'message.updated',properties:{info:{id:'summary-1',role:'assistant',summary:true,mode:'compaction'}}});
  applyEvent(s,{type:'message.part.updated',properties:{part:{id:'part-1',messageID:'summary-1',type:'text',text:'## Goal\n- 保留原生压缩信息'}}});
  assert.equal(s.messages[0].parts[0].text,'## Goal\n- 保留原生压缩信息');
  assert.match(conversationHTML(s),/保留原生压缩信息/);
});

test('idle does not erase an error',()=>{
  const s={messages:[]};
  applyEvent(s,{type:'session.error',properties:{error:{data:{message:'模型不可用'}}}});
  applyEvent(s,{type:'session.status',properties:{status:{type:'idle'}}});
  assert.equal(s.error,'模型不可用');
});

test('native output limit is incomplete even without an API error',()=>{
  const s={messages:[]};
  applyEvent(s,{type:'message.updated',properties:{info:{id:'m1',role:'assistant',finish:'length'}}});
  applyEvent(s,{type:'session.status',properties:{status:{type:'idle'}}});
  assert.ok(s.error.includes('任务尚未完成'));
});

test('a process crash leaves an incomplete native turn, never a completed task',()=>{
  const s={status:{type:'idle'},messages:[{info:{role:'assistant',time:{created:100}},parts:[]}]};
  assert.ok(runIssue(s).includes('已中断'));
  s.messages[0].info.time.completed=101;assert.equal(runIssue(s),null);
});

test('pending native requests survive a snapshot overlap and are removed after reply',()=>{
  const s={messages:[],questions:[],permissions:[]};
  applyEvent(s,{type:'permission.asked',properties:{id:'p1',sessionID:'s1',permission:'bash'}});
  applyEvent(s,{type:'permission.asked',properties:{id:'p1',sessionID:'s1',permission:'bash'}});
  assert.equal(s.permissions.length,1);
  applyEvent(s,{type:'question.asked',properties:{id:'q1',sessionID:'s1',questions:[]}});
  assert.equal(s.questions[0].id,'q1');
  applyEvent(s,{type:'permission.replied',properties:{requestID:'p1'}});
  applyEvent(s,{type:'question.replied',properties:{requestID:'q1'}});
  assert.equal(s.questions.length,0);assert.equal(s.permissions.length,0);
});

test('untrusted markdown cannot execute HTML and citations remain scoped',()=>{
  const html=markdown('<script>alert(1)</script>\n【Daaaaaaaaaaaa:B1】\n【Dbbbbbbbbbbbb:B1】',[
    {id:'aaaaaaaaaaaa',source_hash:'v1'}]);
  assert.ok(!html.includes('<script>'));
  assert.equal((html.match(/class="citation"/g)||[]).length,1);
  assert.ok(html.includes('data-hash="v1"'));
  assert.ok(html.includes('invalid-citation'));
});

import {conversationHTML,matchingSkills,artifactHTML,csvRows} from '../static/ui-utils.js';
import {pdfMarkup} from '../static/reading.js';
import {searchIndex,searchMatches,outlineHTML} from '../static/document-navigation.js';
test('document search maps wrapped Chinese, case, Unicode and literal punctuation to source offsets',()=>{
  const text='付 款\n金额 Payment PAYMENT a.b [合同] 😀 İ';
  const index=searchIndex(text);
  assert.deepEqual(searchMatches(index,'付款金额').map(([a,b])=>text.slice(a,b)),['付 款\n金额']);
  assert.deepEqual(searchMatches(index,'payment').map(([a,b])=>text.slice(a,b)),['Payment','PAYMENT']);
  for(const query of ['a.b','[合同]','😀','İ'])assert.deepEqual(searchMatches(index,query).map(([a,b])=>text.slice(a,b)),[query]);
  assert.deepEqual(searchMatches(index,'\n  '),[]);assert.deepEqual(searchMatches(index,'absent'),[]);
  assert.equal(searchMatches(searchIndex('付款'.repeat(12000)),'付款').length,12000);
});
test('outline displays source hierarchy and escaped titles without guessing from inferred h fields',()=>{
  const html=outlineHTML({source:'pdf-bookmarks',entries:[{title:'<img src=x>',level:2,page:3}]});
  assert.match(html,/来自 PDF 书签/);assert.match(html,/--outline-depth:1/);assert.match(html,/3 页/);assert.doesNotMatch(html,/<img/);
  assert.match(outlineHTML({entries:[]}),/原文未提供可用目录/);
  assert.match(outlineHTML({unavailable:true}),/暂时无法读取/);
});
test('consecutive assistant tools share one compact byline but retain each receipt',()=>{
  const messages=[{info:{id:'u',role:'user'},parts:[{type:'text',text:'检查合同'}]},...['grep','read','read'].map((tool,i)=>({info:{id:'m'+i,role:'assistant',time:{completed:123}},parts:[{id:'p'+i,type:'tool',tool,state:{status:'completed',detail:'合同.pdf · 第 1–100 行'}}]}))];
  const html=conversationHTML({messages,documents:[],status:{type:'idle'}});
  assert.equal((html.match(/合同助手/g)||[]).length,1);
  assert.equal((html.match(/class="tool-action\b/g)||[]).length,3);
  assert.ok(html.includes('第 1–100 行'));
});
test('slash picker uses the native catalog including newly added skills',()=>{
  const catalog=[{name:'contract-summary',label:'合同摘要'}, {name:'contract-review',label:'风险审查'}, {name:'contract-change-risk',label:'合同变更风险',description:'补偿机制'}];
  assert.equal(matchingSkills('/',catalog).length,3);assert.equal(matchingSkills('/contract-r',catalog)[0].name,'contract-review');
  assert.equal(matchingSkills('/变更',catalog)[0].name,'contract-change-risk');
  assert.equal(matchingSkills('/补偿',catalog)[0].name,'contract-change-risk');
  assert.equal(matchingSkills('请解释 / 条款',catalog),null);assert.deepEqual(matchingSkills('/absent',catalog),[]);
  assert.deepEqual(matchingSkills('/'),[]);
});
test('HTML is framed with an opaque origin; structured text stays escaped',()=>{
  const html=artifactHTML({id:'abc',format:'html',title:'看板',content:'<script>attack()</script>'},[]);
  assert.ok(html.includes('sandbox="allow-scripts"'));assert.ok(!html.includes('allow-same-origin'));assert.ok(!html.includes('attack()'));
  assert.ok(artifactHTML({format:'json',content:'{"v":"<script>"}'},[]).includes('&lt;script&gt;'));
  assert.deepEqual(csvRows('名称,备注\r\n"服务,一期","a""b"'),[['名称','备注'],['服务,一期','a"b']]);
});
test('PDF original has real selectable text and stable page geometry before PNG load',()=>{
  const html=pdfMarkup({id:'d',pages:[{w:600,h:800}],segments:[{id:'B0',text:'条款 <test>',page:1,bbox:[20,40,100,50]}]},'t');
  assert.ok(html.includes('aspect-ratio:600/800'));assert.ok(html.includes('data-block="B0"'));assert.ok(html.includes('条款 &lt;test&gt;'));
});

import {todosHTML,thinkingHTML,requestsHTML,orderedDocuments,executionPhase} from '../static/agent-ui.js';
test('native todos retain completion, cancellation and interrupted state without inventing success',()=>{
  const s={status:{type:'idle'},todos:[{content:'读取原文',status:'completed'},{content:'保存报告',status:'in_progress'},{content:'等待材料',status:'pending'},{content:'取消的项',status:'cancelled'}]};
  const html=todosHTML(s,false);assert.match(html,/1 \/ 4 项/);assert.match(html,/data-status="interrupted"/);assert.match(html,/已取消/);assert.doesNotMatch(html,/<details[^>]*open/);
  s.status.type='busy';assert.match(todosHTML(s),/class="bui-spin"/);assert.match(todosHTML(s),/进行中/);
});
test('thinking follows runtime state and yields to actual pending approvals',()=>{
  const s={messages:[],status:{type:'idle'}};assert.equal(thinkingHTML(s),'');
  s.status.type='busy';assert.match(thinkingHTML(s),/正在处理/);
  s.permissions=[{id:'permission-1'}];assert.equal(thinkingHTML(s),'');assert.equal(executionPhase(s).label,'等待你的许可');
  s.permissions=[];s.questions=[{id:'q1'}];assert.equal(thinkingHTML(s),'');assert.equal(executionPhase(s).label,'等待你的答复');
});
test('approval cards preserve native request ids and escape document-controlled text',()=>{
  const html=requestsHTML({questions:[{id:'q1',questions:[{question:'<img src=x>',options:[{label:'" onclick="attack',description:'<script>bad</script>'}],multiple:true}]}],permissions:[{id:'p1',permission:'bash',patterns:['<script>bad</script>']}]});
  assert.match(html,/data-question="q1"/);assert.match(html,/type="checkbox"/);assert.match(html,/data-permission="p1" data-reply="once"/);assert.match(html,/data-reply="reject"/);
  assert.doesNotMatch(html,/<script>|<img/);assert.match(html,/&lt;script&gt;/);
});
test('reading tabs pin primary document and keep conversation attachment order',()=>{
  const docs=[{id:'a1',thread_id:'one'},{id:'primary',thread_id:null},{id:'a2',thread_id:'one'}];
  assert.deepEqual(orderedDocuments(docs).map(d=>d.id),['primary','a1','a2']);assert.equal(docs[0].id,'a1');
});

test('citations show page/paragraph labels while preserving scoped navigation keys',()=>{
  const docs=[{id:'5f4ae2b9c6ad',filename:'采购合同.pdf',source_hash:'version',locations:{B1582:{page:43,ordinal:1583}}},
    {id:'aaaaaaaaaaaa',thread_id:'t',filename:'补充条款.txt',source_hash:'v2',locations:{B1:{ordinal:2}}}];
  const html=markdown('【D5f4ae2b9c6ad:B1582】 【Daaaaaaaaaaaa:B1】 【D5f4ae2b9c6ad:B99999】',docs);
  const visible=html.replace(/<[^>]+>/g,'');
  assert.match(visible,/查看原文.*第 43 页/);assert.match(visible,/补充条款.txt.*第 2 段/);assert.match(visible,/引用暂不可用/);
  assert.doesNotMatch(visible,/5f4ae2b9c6ad|B1582/);assert.match(html,/data-block="B1582"/);assert.match(html,/data-hash="version"/);
});
test('user messages preserve literal text without oversized markdown headings',()=>{
  const html=conversationHTML({messages:[{info:{role:'user'},parts:[{type:'text',text:'# 请看这段\n\n<script>alert(1)</script>'}]}],documents:[],status:{type:'idle'}});
  assert.match(html,/class="user-text"/);assert.match(html,/# 请看这段\n\n/);assert.doesNotMatch(html,/<h1>|<script>/);
});

import {connectEvents} from '../static/events.js';
test('intentional conversation switch closes SSE without a reconnect warning',t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const streams=[];
  const previous=globalThis.EventSource;
  globalThis.EventSource=class {constructor(){streams.push(this)}close(){this.closed=true}};
  try{
    let disconnected=0,connected=0;
    const stop=connectEvents('first',()=>{},()=>connected++,()=>disconnected++);
    streams[0].onerror();stop();t.mock.timers.tick(2000);assert.equal(disconnected,0);
    streams[0].onmessage({data:JSON.stringify({type:'workbench.connected'})});assert.equal(connected,0);
    let events=0;const stop2=connectEvents('second',()=>events++,()=>connected++,()=>disconnected++);
    streams[1].onmessage({data:JSON.stringify({type:'workbench.connected'})});assert.equal(connected,0);
    streams[1].onmessage({data:JSON.stringify({type:'workbench.heartbeat'})});assert.equal(events,0);
    streams[1].onerror();t.mock.timers.tick(800);
    streams[1].onmessage({data:JSON.stringify({type:'workbench.connected'})});t.mock.timers.tick(2000);
    assert.equal(disconnected,0);assert.equal(connected,1);
    streams[1].onerror();t.mock.timers.tick(5100);assert.equal(disconnected,1);
    streams[1].onmessage({data:JSON.stringify({type:"workbench.heartbeat"})});assert.equal(connected,2);stop2();
  }finally{globalThis.EventSource=previous;}
});

test('explicit skill stays visible in the user bubble without implying execution succeeded',()=>{
  const html=conversationHTML({messages:[{info:{role:'user'},parts:[{type:'text',text:'/contract-review\n全面审查下。'}]}],documents:[],status:{type:'idle'}});
  assert.match(html,/class="message-skill"[^>]*>\/contract-review<\/span>/);
  assert.match(html,/class="user-text">全面审查下。<\/div>/);
  assert.doesNotMatch(html,/完成|成功/);
});

import {riskBoard,riskCounts} from '../static/risk-ui.js';
test('merged citations keep full range and cross-page labels, rejecting holes',()=>{
  const doc={id:'aaaaaaaaaaaa',source_hash:'v1',locations:{B1:{page:2},B2:{page:2},B3:{page:3}}};
  const html=markdown('【Daaaaaaaaaaaa:B1-B3】',[doc]);
  assert.equal((html.match(/class="citation"/g)||[]).length,1);assert.ok(html.includes('第 2–3 页'));
  assert.ok(html.includes('data-end="B3"'));assert.ok(html.includes('连续 3 段'));
  delete doc.locations.B2;assert.ok(markdown('【Daaaaaaaaaaaa:B1-B3】',[doc]).includes('invalid-citation'));
});
test('risk cards distinguish dispositions and render reason citations with readable labels',()=>{
  const findings=[{risk_id:'R1',risk_name:'间接损失',verdict:'命中',reason:'赔偿【Daaaaaaaaaaaa:B1-B2】'},
    {risk_id:'R2',verdict:'未命中',reason:'未触发'}, {risk_id:'R3',verdict:'信息不足',reason:'缺附件'},
    {risk_id:'R4',verdict:'未命中',applicable:false,reason:'不适用'}];
  assert.deepEqual(riskCounts(findings),{'命中':1,'未命中':1,'信息不足':1,'不适用':1});
  const data={id:'a',kind:'review',content:'正文',findings,feedback:{R1:{decision:'接受风险',note:'<script>x</script>',revision:1,history:[],created:1}}};
  const html=riskBoard(data,[{id:'aaaaaaaaaaaa',source_hash:'v',locations:{B1:{page:2},B2:{page:2}}}]);
  assert.ok(html.includes('间接损失'));assert.ok(html.includes('class="citation"'));assert.ok(!html.includes('【D'));
  assert.ok(html.includes('接受风险'));assert.ok(html.includes('判断有误'));assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('data-risk-id="R4"'));assert.ok(riskBoard(data,[],'all').includes('data-risk-id="R4"'));
  assert.ok(artifactHTML(data,[]).includes('查看完整报告'));
});
test('native approvals expose once, always and reject',()=>{
  const html=requestsHTML({permissions:[{id:'p',permission:'edit',patterns:['draft.md']}],questions:[]});
  for(const action of ['once','always','reject'])assert.ok(html.includes(`data-reply="${action}"`));
});

import {settingsPaths,settingsTab,savedWorkbenchURL} from '../static/settings-routes.js';
import {traceTimeline,traceTurnSummary} from '../static/trace-view.js';
test('settings deep links resolve their own tabs and return only to local workspaces',()=>{
 for(const [tab,path] of Object.entries(settingsPaths)){assert.equal(settingsTab(path),tab);assert.equal(settingsTab(path+'/'),tab);}
 assert.equal(settingsTab('/'),null);assert.equal(settingsTab('/models'),null);
 assert.equal(savedWorkbenchURL('/agent#abc123/thread/456def'),'/agent#abc123/thread/456def');
 for(const path of ['/#abc123/thread/456def','https://example.com','//example.com','/model',null])assert.equal(savedWorkbenchURL(path),'/spaces');
});

import {filteredWorkspaces,workspaceRows} from '../static/spaces-ui.js';
test('contract spaces filter, sort and escape untrusted titles',()=>{
 const rows=[
  {id:'one',title:'普通合同',starred:0,created:2,last_activity_at:5,thread_count:1,artifact_count:0,deleted_at:null},
  {id:'two',title:'<重点采购>',starred:1,created:1,last_activity_at:3,thread_count:2,artifact_count:1,deleted_at:null},
  {id:'three',title:'已删除合同',starred:1,created:3,last_activity_at:4,thread_count:1,artifact_count:0,deleted_at:10}
 ];
 assert.deepEqual(filteredWorkspaces(rows).map(row=>row.id),['two','one']);
 assert.deepEqual(filteredWorkspaces(rows,{scope:'starred'}).map(row=>row.id),['two']);
 assert.deepEqual(filteredWorkspaces(rows,{scope:'deleted'}).map(row=>row.id),['three']);
 assert.deepEqual(filteredWorkspaces(rows,{query:'普通',sort:'name'}).map(row=>row.id),['one']);
 const html=workspaceRows([rows[1]]);assert.ok(html.includes('&lt;重点采购&gt;'));assert.ok(!html.includes('<重点采购>'));
 for(const action of ['unstar','rename','delete'])assert.ok(html.includes(`data-space-action="${action}"`));
 const deleted=workspaceRows([rows[2]]);assert.ok(deleted.includes('data-space-action="restore"'));assert.ok(deleted.includes('data-space-action="purge"'));assert.ok(!deleted.includes('/agent#three'));
});
test('trace turn rendering includes native tool errors and escapes user content',()=>{
 const summary=traceTurnSummary({id:'r2',created:1,summary:{turn:2,prompt:'<img src=x>',status:'completed',tokens:null,tool_count:1}},1);
 assert.ok(summary.startsWith('<td'));assert.equal((summary.match(/<td/g)||[]).length,5);assert.ok(summary.includes('aria-controls="trace-detail-r2"'));
 assert.ok(traceTurnSummary({id:'r2',created:1,summary:{}},2,true).includes('aria-expanded="true"'));
 assert.ok(summary.includes('第 2 轮'));assert.ok(summary.includes('&lt;img'));assert.ok(summary.includes('未提供 Tokens'));assert.ok(summary.includes('1 次工具调用'));
 const timeline=traceTimeline({summary:{status:'completed',duration:1,cost:null},configuration:null,artifacts:[],messages:[{info:{role:'user'},parts:[{type:'text',text:'提问'}]},{info:{role:'assistant'},parts:[{type:'tool',tool:'read',state:{status:'error',input:{filePath:'contract.txt'},error:'missing <file>',output:'<script>bad</script>'}}]}]});
 assert.ok(timeline.indexOf('用户消息')<timeline.indexOf('trace-tool'));assert.ok(timeline.includes('contract.txt'));assert.ok(timeline.includes('missing &lt;file&gt;'));assert.ok(!timeline.includes('<script>'));assert.ok(timeline.includes('历史版本未记录'));
});

test('queue preserves separate ordered messages and escapes their content',async()=>{
 const {queueHTML}=await import('../static/message-queue.js');
 const html=queueHTML({paused:true,reason:'前一条已停止',items:[{id:'a',status:'queued',body:{text:'<script>bad</script>',model:'glm/one'}},{id:'b',status:'queued',body:{text:'第二条',model:'other/two'}}]});
 assert.ok(html.indexOf('data-withdraw-message="a"')<html.indexOf('data-withdraw-message="b"'));
 assert.ok(html.includes('data-queue-resume>发送</button>'));assert.ok(!html.includes('<script>'));assert.ok(html.includes('模型：two'));assert.ok(!html.includes('other/two'));
});
test('withdrawing for editing preserves an existing draft including its model and quotes',async()=>{
 const {restoreDraft}=await import('../static/message-queue.js');
 const current={text:'未发送草稿',model:'one',quotes:[{text:'原文'}]},recovered={text:'撤回消息',model:'two',skill:'contract-summary'};
 const result=restoreDraft(recovered,current);assert.deepEqual(result,{draft:recovered,saved:[current]});
 assert.deepEqual(restoreDraft(recovered,{text:''}).saved,[]);
});


test('unchanged status and todos do not refresh the conversation but real transitions do',()=>{
 const state={status:{type:'idle'},todos:[]};
 assert.equal(unchangedEvent(state,{type:'session.status',properties:{status:{type:'idle'}}}),true);
 assert.equal(unchangedEvent(state,{type:'todo.updated',properties:{todos:[]}}),true);
 const busy={type:'session.status',properties:{status:{type:'busy'}}};
 assert.equal(unchangedEvent(state,busy),false);applyEvent(state,busy);
 assert.equal(unchangedEvent(state,{type:'session.status',properties:{status:{type:'idle'}}}),false);
 assert.equal(unchangedEvent(state,{type:'todo.updated',properties:{todos:[{id:'one'}]}}),false);
 assert.equal(unchangedEvent(state,{type:'message.updated',properties:{}}),false);
});


test('pending user query appears before model activity and becomes one native message',async()=>{
 const {pendingRequest,reconcilePending}=await import('../static/message-queue.js');
 const {conversationHTML}=await import('../static/ui-utils.js');
 const state={messages:[],documents:[],status:{type:'busy'},pendingSend:{id:'q1',request_id:'req1',status:'sending',body:{text:'金额是多少？'}}};
 let html=conversationHTML(state);assert.match(html,/金额是多少/);assert.match(html,/正在发送/);assert.doesNotMatch(html,/正在思考/);
 state.queue={current:{id:'q1',request_id:'req1',message_id:'native1',status:'dispatching',body:{text:'金额是多少？'}}};
 reconcilePending(state);html=conversationHTML(state);assert.ok(html.includes('连接 Agent 环境中...(准备环境)'));assert.doesNotMatch(html,/正在思考/);
 state.messages=[{info:{id:'native1',role:'user'},parts:[]}];assert.ok(pendingRequest(state));
 state.messages[0].parts=[{type:'text',text:'金额是多少？'}];reconcilePending(state);
 assert.equal(pendingRequest(state),null);assert.equal(state.pendingSend,null);
 html=conversationHTML(state);assert.equal((html.match(/金额是多少/g)||[]).length,1);
 assert.ok(html.indexOf('金额是多少')<html.indexOf('正在处理'));
 const reloaded={...state,messages:[],pendingSend:null};assert.match(conversationHTML(reloaded),/金额是多少/);
});


test('failed or withdrawn pending sends never remain marked as waiting',async()=>{
 const {reconcilePending,pendingRequest}=await import('../static/message-queue.js');
 const state={messages:[],pendingSend:{id:'q1',request_id:'r1',status:'queued',body:{text:'原消息'}},queue:{paused:true,items:[{id:'q1',request_id:'r1',status:'failed',body:{text:'原消息'}}]}};
 reconcilePending(state);assert.equal(state.pendingSend.status,'failed');assert.equal(pendingRequest(state),null);
 state.queue.items=[];reconcilePending(state);assert.equal(pendingRequest(state),null);
});

 test('sandbox preparation labels distinguish cold start and resume',async()=>{
 const {preparationLabel}=await import('../static/message-queue.js');
 assert.match(preparationLabel({stage:'creating'}),/创建/);
 assert.match(preparationLabel({stage:'resuming'}),/恢复/);
 assert.match(preparationLabel({stage:'syncing'}),/同步合同/);
 });

test('Skill deployment UI distinguishes saved from applied and escapes errors',async()=>{
 const {skillEnvironmentsHTML}=await import('../static/skill-environments.js');
 const html=skillEnvironmentsHTML(['applied','waiting','on_start','failed'].map(status=>({title:'合同',status,error:status==='failed'?'<script>':''})));
 assert.match(html,/已生效/);assert.match(html,/当前任务结束后生效/);assert.match(html,/环境下次启动时生效/);assert.match(html,/重试环境更新/);assert.ok(!html.includes('<script>'));
});

test('paused outbox shows an explicit send action and no duplicate pending bubble',async()=>{
 const {queueHTML,pendingRequest}=await import('../static/message-queue.js');
 const item={id:'q',status:'queued',body:{text:'新消息'}};
 const queue={paused:true,reason:'有消息未能发送，后续消息已暂停。',items:[item]};
 const html=queueHTML(queue);assert.ok(html.includes('data-queue-resume>发送</button>'));assert.match(html,/尚未发送/);assert.ok(!html.includes('排队中'));assert.ok(!html.includes('有消息未能发送'));
 assert.equal(pendingRequest({queue,pendingSend:item}),null);
 assert.ok(!queueHTML({...queue,items:[{...item,status:'failed',error:'环境不可用'}]}).includes('data-queue-resume'));
});

test('recovered and saved drafts are deduplicated without losing different text',async()=>{
 const {restoreDraft}=await import('../static/message-queue.js');
 const a={text:'a',model:'one'},b={text:'b'};
 assert.deepEqual(restoreDraft(a,a,[a,b,b]).saved,[b]);
 assert.deepEqual(restoreDraft(a,{...a,model:'two'}).saved,[{...a,model:'two'}]);
});

test('queue shows model name without provider and omits redundant hint',async()=>{
 const {queueHTML}=await import('../static/message-queue.js');
 const q={paused:true,items:[{id:'q',status:'queued',body:{text:'test',model:'provider-private/z-ai/glm-5.3'}}]};
 const html=queueHTML(q,[{id:'provider-private/z-ai/glm-5.3',label:'GLM 5.3'}]);
 assert.ok(html.includes('GLM 5.3'));assert.ok(!html.includes('provider-private'));
 assert.ok(!html.includes('queue-reason'));assert.ok(html.includes('data-queue-resume>发送</button>'));
 assert.ok(queueHTML(q).includes('glm-5.3'));
});

test('environment loader preserves status safely without time UI',async()=>{
 const {loadingStateHTML,preparationLabel}=await import('../static/message-queue.js');
 const html=loadingStateHTML(preparationLabel({stage:'syncing'}));
 assert.ok(html.includes('连接 Agent 环境中...(同步合同和配置)'));
 assert.equal((html.match(/<i /g)||[]).length,9);
 assert.ok(!html.includes('elapsed'));assert.ok(!loadingStateHTML('<script>').includes('<script>'));
});

test('skill insertion preserves entered instructions and replaces slash selection',async()=>{
 const {skillInput}=await import('../static/ui-utils.js');
 assert.equal(skillInput('重点看付款','contract-summary'),'/contract-summary 重点看付款');
 assert.equal(skillInput('/','contract-summary'),'/contract-summary ');
 assert.equal(skillInput('/contract-review 重点看付款','contract-summary'),'/contract-summary 重点看付款');
});
test('selected source has a separate escaped quote style before and after native delivery',async()=>{
 const {userMessageHTML}=await import('../static/ui-utils.js');
 const pending=userMessageHTML('解释这条',[],[{filename:'合同.txt',text:'付款<30天'}]);
 const native=userMessageHTML('解释这条\n\n选中原文（合同.txt）：\n付款<30天');
 for(const html of [pending,native]){
  assert.ok(html.includes('message-source-quote'));assert.ok(html.includes('引用原文 · 合同.txt'));
  assert.ok(html.includes('付款&lt;30天'));assert.ok(html.indexOf('解释这条')<html.indexOf('<blockquote'));
 }
});

 test('thread activity indicators and rename remain distinct from title text',()=>{
  const html=threadListHTML(['running','waiting','completed','failed'].map((activity,i)=>({id:String(i),title:'合同',activity})),null);
  assert.match(html,/thread-state running/);
  assert.match(html,/已完成，尚未查看/);
  assert.match(html,/data-thread-action="rename"/);
  assert.doesNotMatch(threadListHTML([{id:'idle',title:'合同'}],null),/thread-state/);
});

test('completed task list stays hidden across idle, new prompt, retry and restore',()=>{
  const state={status:{type:'busy'},todos:Array.from({length:5},(_,i)=>({content:`任务 ${i+1}`,status:'completed'}))};
  assert.equal(todosHTML(state),'');
  state.status.type='idle';
  assert.equal(todosHTML(state,true),'');
  assert.equal(todosHTML(JSON.parse(JSON.stringify(state))), '');
  for(const type of ['busy','retry','idle']){
    state.status.type=type;
    assert.equal(todosHTML(state,true),'');
    assert.equal(todosHTML(JSON.parse(JSON.stringify(state))), '');
  }
  applyEvent(state,{type:'todo.updated',properties:{todos:[{content:'新请求的任务',status:'in_progress'}]}});
  state.status.type='busy';
  assert.match(todosHTML(state),/新请求的任务/);
  assert.match(todosHTML(state),/0 \/ 1 项/);
});

test('failed snapshot releases navigation and a stale failure cannot unlock a newer switch',async()=>{
  const {readFile}=await import('node:fs/promises');const {runInNewContext}=await import('node:vm');
  const source=await readFile(new URL('../static/app.js',import.meta.url),'utf8');
  const restore=source.slice(source.indexOf('async function restore(view='),source.indexOf('\nfunction receive(event)'));
  let reject;const notices=[];
  const context={epoch:1,restoring:false,switching:true,restoreEpoch:0,buffer:[],tid:'one',viewRequests:new AbortController(),updateControls(){},notice:(...args)=>notices.push(args),api:()=>new Promise((_,no)=>reject=no)};
  runInNewContext(restore,context);
  const first=context.restore();reject(new Error('offline'));await first;
  assert.equal(context.restoring,false);assert.equal(context.switching,false);assert.match(notices[0][0],/重新加载/);
  context.switching=true;
  const old=context.restore();context.epoch=2;context.restoreEpoch++;context.restoring=true;
  reject(new Error('old offline'));await old;
  assert.equal(context.restoring,true);assert.equal(context.switching,true);assert.equal(notices.length,1);
});

test('abandoned reads abort while upload failures are explicit and never silently retried',async t=>{
  const {api,upload}=await import('../static/api.js');
  const originalFile=globalThis.File;if(!globalThis.File)globalThis.File=class extends Blob{};
  try{
    let calls=0;
    t.mock.method(globalThis,'fetch',async(_path,options)=>{
      calls++;
      return await new Promise((_,reject)=>{if(options.signal.aborted)reject(options.signal.reason);else options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});});
    });
    const controller=new AbortController();const pending=api('/read',{signal:controller.signal});controller.abort();
    await assert.rejects(pending,{name:'AbortError'});
    await assert.rejects(api('/read',{timeout:5}),/读取超时/);
    t.mock.method(globalThis,'fetch',async()=>{calls++;throw new TypeError('Failed to fetch');});
    const file=new Blob(['test']);file.name='test.txt';
    await assert.rejects(upload('/api/workspaces',file),/结果尚未确认/);
    assert.equal(calls,3);
  }finally{globalThis.File=originalFile;}
});


test('generation status follows only the current turn and resumes tool/retry/wait states',()=>{
 const state={status:{type:'busy'},messages:[{info:{role:'user'},parts:[]},{info:{role:'assistant'},parts:[{type:'text',text:'开始答复'}]}]};
 assert.equal(executionPhase(state).kind,'generating');assert.equal(thinkingHTML(state),'');
 state.messages[1].parts.push({type:'tool',tool:'read',state:{status:'running'}});
 assert.equal(executionPhase(state).label,'读取原文');assert.equal(thinkingHTML(state),'');
 state.messages[1].parts[1].state.status='completed';
 assert.equal(executionPhase(state).kind,'generating');
 state.status={type:'retry',message:'稍后重试'};assert.match(thinkingHTML(state),/稍后重试/);
 state.status={type:'idle'};assert.equal(executionPhase(state).kind,'idle');assert.equal(thinkingHTML(state),'');
 state.status.type='busy';state.messages.push({info:{role:'user'},parts:[{type:'text',text:'新的问题'}]});
 assert.equal(executionPhase(state).kind,'processing');assert.match(thinkingHTML(state),/正在处理/);
 state.permissions=[{id:'p'}];assert.equal(executionPhase(state).kind,'permission');
});

test('bare references become verified page links only for a single known source',()=>{
 const doc={id:'a9a82a6840e2',filename:'招标文件.pdf',source_hash:'v1',locations:Object.fromEntries(Array.from({length:13},(_,i)=>['B'+(3101+i),{page:79,ordinal:3102+i,preview:i===0?'投标报价 <原文>':''}]))};
 const text='一、投标报价 【B3101-B3104】 二、付款方式 【B3105-B3113】';
 const html=markdown(text,[doc]);
 assert.equal((html.match(/class="citation"/g)||[]).length,2);
 assert.match(html,/data-block="B3101" data-end="B3104"/);assert.match(html,/data-block="B3105" data-end="B3113"/);
 assert.match(html,/第 79 页/);assert.match(html,/投标报价 &lt;原文&gt;/);
 assert.doesNotMatch(html.replace(/<[^>]+>/g,''),/B3101|B3113/);
 const removed=markdown('旧附件【Dbbbbbbbbbbbb:B3101】\n后续【B3101】',[doc]);
 assert.doesNotMatch(removed,/class="citation"/);assert.match(removed,/来源待核对/);
 const ambiguous=markdown(text,[doc,{...doc,id:'bbbbbbbbbbbb'}]);
 assert.doesNotMatch(ambiguous,/class="citation"/);assert.match(ambiguous,/来源待核对/);
 delete doc.locations.B3103;assert.match(markdown('【B3101-B3104】',[doc]),/引用暂不可用/);
 assert.match(markdown('【B99999】',[doc]),/引用暂不可用/);
});

test('permission purpose is readable and technical command details stay collapsed',()=>{
 const html=requestsHTML({permissions:[{id:'p',permission:'bash',description:'生成 Word 报告',patterns:['python convert.py <secret>']}],questions:[]});
 assert.match(html,/<h3>生成 Word 报告<\/h3>/);
 assert.match(html,/<details class="approval-technical"><summary>技术详情/);
 assert.match(html,/python convert.py &lt;secret&gt;/);assert.doesNotMatch(html,/<details[^>]*open/);
});

test('background completion sync preserves input focus, selection and draft',async()=>{
 const {readFile}=await import('node:fs/promises'),{runInNewContext}=await import('node:vm');
 const source=await readFile(new URL('../static/app.js',import.meta.url),'utf8');
 const fn=source.slice(source.indexOf('function updateControls(){'),source.indexOf('\nasync function loadList()'));
 const nodes=new Map(),document={querySelectorAll:()=>[],activeElement:null};
 const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'正在输入下一条',selectionStart:4,selectionEnd:6,options:[],classList:{toggle(){}},setAttribute(){},querySelector(){return {textContent:''}},set disabled(value){this._disabled=value;if(value&&document.activeElement===this)document.activeElement=null},get disabled(){return this._disabled}});return nodes.get(id)};
 document.activeElement=$('input');
 const ctx={$,document,state:{loaded:true,status:{type:'idle'},messages:[]},tid:'t',restoring:true,switching:false,workspace:{threads:[]},threadScope:()=> 'active',scopeLabels:{},threadManaging:false,modelCatalog:{available:true},modelSaving:false,permissionSaving:false,permissionTarget:null,permissionSpinner:false,riskSchemeOptions:null,sending:false,stoppingThread:null,creatingThread:false,executionPhase,runIssue:()=>false,esc:x=>x};
 runInNewContext(fn,ctx);ctx.updateControls();
 assert.equal(document.activeElement,$('input'));assert.equal($('input').disabled,false);assert.equal($('input').value,'正在输入下一条');assert.equal($('input').selectionStart,4);assert.equal($('input').selectionEnd,6);
 ctx.restoring=false;ctx.updateControls();assert.equal(document.activeElement,$('input'));
 ctx.switching=true;ctx.updateControls();assert.equal($('input').disabled,true);
});

test('only the current opaque report frame can request verified source navigation',async()=>{
 const {previewCitation}=await import('../static/preview-citations.js');
 const source={},frames=[{contentWindow:source,dataset:{artifactPreview:'report'}}],docs=[{id:'doc',source_hash:'v1',locations:{B1:{},B2:{}}}];
 const event={origin:'null',source,data:{type:'workbench.citation',artifactId:'report',docid:'doc',hash:'v1',block:'B1',end:'B2'}};
 assert.deepEqual(previewCitation(event,frames,docs),{docid:'doc',hash:'v1',block:'B1',end:'B2'});
 for(const change of [{source:{}},{origin:'https://evil.example'},{data:{...event.data,artifactId:'other'}},{data:{...event.data,hash:'old'}},{data:{...event.data,end:'B3'}},{data:{...event.data,type:'execute'}}])assert.equal(previewCitation({...event,...change},frames,docs),null);
});
