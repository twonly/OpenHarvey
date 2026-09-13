import {setupAuth,accountReady} from './account-ui.js?v=20260913-header-2';
import {previewCitation} from './preview-citations.js';
import {threadScope,scopeLabels,threadListHTML} from './thread-ui.js?v=20260912-21';
import {queueHTML,restoreDraft,reconcilePending,pendingRequest,preparationLabel,loadingStateHTML} from './message-queue.js?v=20260912-21';
import {setupSettings} from './settings-ui.js?v=20260913-2';
import {settingsTab,savedWorkbenchURL} from './settings-routes.js';
import {api,upload} from './api.js';
import {connectEvents,applyEvent,messageIssue,runIssue,unchangedEvent} from './events.js?v=20260913-1';
import {esc} from './markdown.js';
import {riskBoard} from './risk-ui.js';
import {todosHTML,requestsHTML,orderedDocuments,icon,executionPhase} from './agent-ui.js?v=20260913-2';
import {conversationHTML,artifactHTML,matchingSkills,welcomeHTML,skillInput} from './ui-utils.js?v=20260913-accounts-1';
import {setupReading,setupArtifactStrip,setupQuotes,pdfMarkup,fitPdfText} from './reading.js?v=20260912-3';
import {setupDocumentNavigation} from './document-navigation.js?v=20260911-18';

const $=id=>document.getElementById(id);
let workspace=null,tid=null,state={messages:[],status:{type:'idle'},documents:[]},selectedSkill=null;
let stopStream=()=>{},epoch=0,renderTimer=null,source=null,sourceMode='original',artifactId=null;
let restoring=false,restoreEpoch=0,buffer=[],sourceEpoch=0,sourceRenderEpoch=0,artifactEpoch=0;
let comparing=false,compareId=null,compareEpoch=0,skillIndex=0;
let skillCatalog=[],workspaces=[],switching=false,requestSignature='',modelCatalog=null,selectedModel=null,modelSaving=false;
let threadManaging=false,threadFilter='active',creatingThread=false,viewRequests=new AbortController();
let permissionSaving=false,permissionTarget=null,permissionSpinner=false,riskSchemeOptions=null;
let sourceRendered=false,sending=false,submission=null,queuePolling=false,stoppingThread=null;
const artifactData=new Map();
const reading=setupReading();
const artifactStrip=setupArtifactStrip();
const sourceNavigation=setupDocumentNavigation(navigateOutline,notice);
const quotes=setupQuotes(()=>({source,tid}),()=>saveDraft(),notice,()=>reading.reset());
new ResizeObserver(()=>fitPdfText($('sourceContent'))).observe($('sourceContent'));

const settingsUI=setupSettings({notice,onClose:async()=>{
  await Promise.all([loadModels(),loadRiskSchemes()]);
  if(tid&&!state.permission_override&&state.status?.type==='idle'){const preferences=await api('/api/settings');state.permission_mode=preferences.effective.permission_mode;updateControls();}
  if(tid&&state.status?.type==='idle'){
    const skills=await api(`/api/threads/${tid}/skills/refresh`,{method:'POST',body:{}});renderSkills(skills);
  }
}});
$('openSettings').onclick=protect(()=>settingsUI.open());

let noticeTimer;
function notice(text='',kind='info'){clearTimeout(noticeTimer);$('notice').hidden=!text;$('notice').textContent=text;$('notice').dataset.kind=kind;if(text&&kind==='info')noticeTimer=setTimeout(()=>notice(),3200);}
function protect(fn){return async(...args)=>{try{await fn(...args);}catch(e){if(e.name!=='AbortError')notice(e.message,'error');}};}
function loggedOut(){
  document.body.dataset.auth='logged-out';$('authLoading').hidden=true;
  artifactData.clear();
  stopStream();epoch++;sourceEpoch++;artifactEpoch++;restoring=false;buffer=[];
  $('loginView').hidden=false;workspace=null;tid=null;source=null;artifactId=null;workspaces=[];requestSignature='';switching=false;$('workspaceSwitcher').open=false;$('attachmentCount').textContent='0';
  state={messages:[],status:{type:'idle'},documents:[]};modelCatalog=null;selectedModel=null;$('modelSelect').replaceChildren();
  renderSkills([]);hideSkillPicker();
  for(const id of ['workspaceList','threadList','workspaceArtifacts','artifactTabs','messageHistory','sourceContent','artBody','pendingRequests','attachmentList','todos','messageQueue','savedDrafts'])$(id).replaceChildren();
  for(const id of ['fname','username','threadTitle'])$(id).textContent='';
  $('workspaceName').textContent='合同工作区';$('input').value='';setSkill(null);notice();
  $('artifactDownloads').replaceChildren();$('originalLink').hidden=true;
  $('documentTitle').textContent='选择文档';$('documentTitle').hidden=false;$('documentSelect').hidden=true;$('artifactSelect').replaceChildren();$('artifactSelect').hidden=true;$('artifactTitle').hidden=false;$('artifactTitle').textContent='产出物';$('artifactInfo').hidden=true;clearComparison();quotes.set([]);reading.reset();$('documentSelect').replaceChildren();
  sourceNavigation.setDocument(null);
  sessionStorage.clear();history.replaceState(null,'',location.pathname);updateControls();
}
document.addEventListener('session-expired',loggedOut);

function updateControls(){
  const busy=state.status?.type!=='idle'||!!state.queue?.active;
  const loading=restoring||switching;
  const selected=workspace?.threads.find(t=>t.id===tid),readOnly=!!selected&&threadScope(selected)!=='active';
  $('threadReadOnly').hidden=!readOnly;
  $('threadReadOnly').querySelector('span').textContent=readOnly?`${scopeLabels[threadScope(selected)]} · 恢复后可继续对话`:'';
  $('restoreCurrentThread').disabled=threadManaging||loading;
  $('threadList').inert=threadManaging;
  $('composer').inert=readOnly;
  $('composer').classList.toggle('read-only',readOnly);
  $('input').placeholder=readOnly?'此对话只读，恢复后可继续':'询问条款、圈选原文提问，或输入 / 选择 Skill…';
  for(const id of ['messageHistory','pendingRequests','sourceContent'])$(id).inert=loading;
  $('chatPane').setAttribute('aria-busy',String(loading));
  $('modelSelect').disabled=readOnly||!modelCatalog||loading||modelSaving;
  $('permissionMode').disabled=readOnly||!tid||loading||permissionSaving||(!state.full_execution_available&&(busy||!!state.permissions?.length||!!state.questions?.length));
  for(const option of $('permissionMode').options)option.disabled=option.value==='full'?!state.full_execution_available:busy;
  $('permissionMode').value=(permissionSaving&&permissionTarget?.tid===tid?permissionTarget.mode:state.permission_mode)||'auto';
  $('permissionLoading').hidden=!(permissionSpinner&&permissionTarget?.tid===tid);
  $('permissionMode').setAttribute('aria-busy',String(permissionSaving&&permissionTarget?.tid===tid));
  $('riskSchemeSelect').disabled=readOnly||!tid||loading;
  if(riskSchemeOptions&&!loading)$('riskSchemeSelect').value=state.risk_scheme||riskSchemeOptions.selected||'';
  $('input').disabled=!tid||switching||!state.loaded||readOnly;$('sendBtn').disabled=!tid||readOnly||sending||loading||!modelCatalog?.available||modelSaving||permissionSaving;
  const waiting=busy||!!(state.queue?.paused&&!state.queue?.resume_on_send)||!!state.queue?.items?.length;
  $('sendLabel').hidden=!waiting;
  $('sendLabel').textContent=(state.queue?.paused&&!state.queue?.resume_on_send)?'加入待发送':'排队';
  $('sendBtn').classList.toggle('queue',waiting);
  $('sendBtn').setAttribute('aria-label',(state.queue?.paused&&!state.queue?.resume_on_send)?'加入待发送':waiting?'排队发送':'发送给 Agent');
  $('sendBtn').title=(state.queue?.paused&&!state.queue?.resume_on_send)?'加入待发送列表；点击上方“发送”开始':waiting?'加入队列，当前任务结束后依次发送':'发送给 Agent';
  $('attachButton').disabled=readOnly||!tid||busy||loading;
  const stopping=stoppingThread===tid;
  $('stopButton').hidden=!tid||(!busy&&!stopping)||switching;
  $('stopButton').disabled=stopping;
  $('stopButton').querySelector('span').textContent=stopping?'正在取消…':state.status?.type==='retry'?'取消重试':'取消任务';
  $('artifactToolbar').inert=loading;$('compareSelect').disabled=loading;$('documentSelect').disabled=loading;$('documentToolbar').inert=loading;$('sourceTools').inert=loading;$('sourceOutline').inert=loading;
  $('newThread').disabled=!workspace||creatingThread;
  $('railAttachButton').disabled=!tid||busy||loading||readOnly;
  document.querySelectorAll('[data-skill]').forEach(b=>b.disabled=readOnly||!tid||loading);
  document.querySelectorAll('[data-delete-attachment]').forEach(b=>b.disabled=busy||loading||readOnly);
  const phase=executionPhase(state);
  $('generationStatus').hidden=loading||phase.kind!=='generating';
  const statusLabel=switching?'正在切换':restoring?'正在同步':busy?(state.queue?.current?.status==='dispatching'?preparationLabel(state.queue.current):state.status.type==='retry'?'正在重试':state.status.type==='idle'?'正在同步执行结果':phase.kind==='generating'?'':phase.label):state.queue?.paused&&state.queue?.items?.length?'等待发送确认':(state.error||runIssue(state))?'运行未完成':'就绪';
  const statusHTML=!switching&&!restoring&&state.queue?.current?.status==='dispatching'?loadingStateHTML(statusLabel):esc(statusLabel);
  if($('runStatus').innerHTML!==statusHTML)$('runStatus').innerHTML=statusHTML;
}

async function loadList(){
  workspaces=await api('/api/workspaces');renderWorkspaceOptions();
}
function renderWorkspaceOptions(){
  const query=$('workspaceSearch').value.trim().toLowerCase();
  const list=workspaces.filter(w=>w.title.toLowerCase().includes(query));
  $('workspaceList').innerHTML=list.map(w=>`<button class="thread-item ${workspace?.id===w.id?'active':''}" data-workspace="${w.id}"><span class="thread-icon">文</span><span class="thread-copy"><b>${esc(w.title)}</b><small>${new Date(w.created*1000).toLocaleDateString()}</small></span></button>`).join('')||'<p class="placeholder">'+(query?'没有匹配的合同':'还没有上传合同')+'</p>';
}

function renderWorkspace(){
  $('fname').textContent=workspace.title;$('workspaceName').textContent=workspace.title;
  const threadHTML=threadListHTML(visibleThreads(),tid);
  if($('threadList').dataset.rendered!==threadHTML||!$('threadList').childElementCount){$('threadList').innerHTML=threadHTML;$('threadList').dataset.rendered=threadHTML;}
  $('threadScope').innerHTML=Object.entries(scopeLabels).map(([value,label])=>`<option value="${value}">${label} (${workspace.threads.filter(t=>threadScope(t)===value).length})</option>`).join('');
  $('threadScope').value=threadFilter;
  $('workspaceArtifacts').innerHTML=workspace.artifacts.map(a=>`<button class="rail-file" data-artifact="${a.id}"><span class="file-icon">${esc((a.format||'md').toUpperCase())}</span><span class="file-copy"><b>${esc(a.title)}</b><small>${new Date(a.created*1000).toLocaleString()}${a.thread_deleted_at?' · 来源对话已删除':a.thread_archived_at?' · 来源对话已归档':''}</small></span></button>`).join('');
  renderArtifactPicker();
  updateControls();
}

async function refreshWorkspace(){
  if(!workspace)return;
  const wid=workspace.id,view=epoch;
  const fresh=await api(`/api/workspaces/${wid}`);
  if(view!==epoch)return;
  for(const t of fresh.threads){const old=workspace.threads.find(row=>row.id===t.id);if(old){t.activity=old.activity;t.completion_id=old.completion_id;}}
  workspace=fresh;renderWorkspace();
  if(!artifactId&&workspace.artifacts.length&&document.activeElement!==$('input')){
    try{await openArtifact(workspace.artifacts[0].id,false,false);}
    catch(e){if(view===epoch)notice(e.message,'error');}
  }
}

let activityPolling=false;
async function refreshThreadActivity(){
  if(!workspace||activityPolling||document.hidden||switching||threadManaging)return;
  activityPolling=true;const wid=workspace.id,view=epoch;
  try{
    const rows=await api(`/api/workspaces/${wid}/thread-status`);
    if(view!==epoch||workspace?.id!==wid)return;
    for(const row of rows){const t=workspace.threads.find(t=>t.id===row.id);if(t)Object.assign(t,row);}
    if(!$('threadList').querySelector('details[open]')&&!$('renameThreadDialog').open)renderWorkspace();
    const current=rows.find(t=>t.id===tid);
    if(current?.activity==='completed'&&!restoring){
      if(current.completion_id!==state.completion_id)await restore(view);
      else await markThreadSeen(view);
    }
  }catch{/* The next poll will reconcile local activity. */}
  finally{activityPolling=false;}
}
setInterval(refreshThreadActivity,3000);
async function markThreadSeen(view){
  const token=state.completion_id,target=tid;
  if(!token||document.hidden||view!==epoch)return;
  await api(`/api/threads/${target}/seen`,{method:'POST',body:{completion_id:token}});
  if(view!==epoch)return;
  const current=workspace.threads.find(t=>t.id===target);if(current&&current.completion_id===token){current.activity='idle';renderWorkspace();}
}

async function selectWorkspace(wid,requestedTid){
  saveDraft();stopStream();viewRequests.abort();viewRequests=new AbortController();const view=++epoch;notice();
  tid=null;source=null;sourceEpoch++;artifactId=null;artifactEpoch++;quotes.set([]);clearComparison();$('artifactTitle').textContent='';
  sourceNavigation.setDocument(null);
  $('sourceContent').innerHTML='<p class="placeholder">正在读取合同…</p>';
  $('artBody').innerHTML='<p class="placeholder">摘要、报告及其他文件保存后会出现在这里。</p>';
  $('artifactDownloads').replaceChildren();
  let fresh=await api(`/api/workspaces/${wid}`,{signal:viewRequests.signal});
  if(view!==epoch)return;
  workspace=fresh;
  if(!fresh.threads.length){
    try{await api(`/api/workspaces/${wid}/threads`,{method:'POST',body:{}});fresh=await api(`/api/workspaces/${wid}`);}
    catch(e){if(view===epoch){renderWorkspace();notice('合同已上传。'+e.message+'，可稍后点击“新建对话”重试。');}return;}
    if(view!==epoch)return;workspace=fresh;
  }
  threadFilter=requestedTid?threadScope(workspace.threads.find(t=>t.id===requestedTid)||{}):'active';
  const target=requestedTid||visibleThreads()[0]?.id;
  if(!target){clearThreadSelection();renderWorkspace();await refreshWorkspace();await loadList();return;}
  if(!workspace.threads.some(t=>t.id===target))throw new Error('指定的对话不存在');
  await selectThread(target);await loadList();
}

function visibleThreads(){return (workspace?.threads||[]).filter(t=>threadScope(t)===threadFilter);}
function clearThreadSelection(){
  saveDraft();stopStream();epoch++;sourceEpoch++;artifactEpoch++;clearTimeout(renderTimer);
  tid=null;source=null;switching=false;restoring=false;buffer=[];
  state={messages:[],documents:[],status:{type:'idle'}};
  quotes.set([]);sourceNavigation.setDocument(null);clearComparison();
  $('input').value='';setSkill(null);hideSkillPicker();
  for(const id of ['pendingRequests','attachmentList','messageQueue','sourceContent','savedDrafts'])$(id).replaceChildren();
  $('messageQueue').hidden=true;$('attachmentCount').textContent='0';
  $('sourceContent').innerHTML='<p class="placeholder">选择对话后阅读合同原文。</p>';
  $('documentSelect').hidden=true;$('documentTitle').hidden=false;$('documentTitle').textContent='合同文档';
  $('threadTitle').textContent='选择或新建对话';
  $('messageHistory').innerHTML='<div class="welcome"><h2>此范围暂无对话</h2><p>可切换查看范围，或点击左侧 ＋ 新建对话。</p></div>';
  $('todos').hidden=true;$('originalLink').hidden=true;
  history.replaceState(null,'',`/agent#${workspace.id}`);sessionStorage.removeItem('workbench-location');
  updateControls();
}
async function changeThreadScope(value){
  threadFilter=value;
  const next=visibleThreads()[0];
  if(next)await selectThread(next.id);else clearThreadSelection();
  renderWorkspace();
}
async function manageThread(id,action){
  if(threadManaging)return;
  let title;
  if(action==='rename'){
    const dialog=$('renameThreadDialog'),input=$('renameThreadInput');input.value=workspace.threads.find(t=>t.id===id)?.title||'';
    dialog.returnValue='cancel';const saved=await new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='save');dialog.showModal();input.focus();input.select();});
    if(!saved)return;title=input.value.trim();if(!title){notice('请输入对话名称。');return;}
  }
  if(action==='delete'){
    const dialog=$('deleteThreadDialog');dialog.returnValue='cancel';
    const confirmed=await new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='delete');dialog.showModal();});
    if(!confirmed)return;
  }
  const view=epoch,wid=workspace.id,rows=visibleThreads(),index=rows.findIndex(t=>t.id===id);
  threadManaging=true;updateControls();
  try{
    await api(`/api/threads/${id}`,{method:'PATCH',body:{action,title}});
    if(view!==epoch||workspace?.id!==wid)return;
    await refreshWorkspace();
    if(view!==epoch)return;
    if(id===tid&&!visibleThreads().some(t=>t.id===id)){
      const next=visibleThreads()[Math.min(index,visibleThreads().length-1)];
      if(next)await selectThread(next.id);else clearThreadSelection();
    }
    renderWorkspace();
    if(action==='rename'&&id===tid){state.title=title;$('threadTitle').textContent=title;}
    notice({rename:'对话已重命名。',archive:'已归档，可在“已归档”中查看和恢复。',delete:'已移入“最近删除”，可随时恢复。',restore:'对话已恢复。',up:'对话已上移。',down:'对话已下移。'}[action]);
  }finally{threadManaging=false;updateControls();}
}
$('threadScope').onchange=protect(e=>changeThreadScope(e.target.value));
$('restoreCurrentThread').onclick=protect(()=>manageThread(tid,'restore'));
document.addEventListener('click',e=>document.querySelectorAll('.thread-menu[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;}));
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const menu=document.querySelector('.thread-menu[open]');if(menu){menu.open=false;menu.querySelector('summary').focus();e.preventDefault();}}},true);

function saveDraft(){if(tid){sessionStorage.setItem('skill:'+tid,selectedSkill||'');sessionStorage.setItem('draft:'+tid,$('input').value);sessionStorage.setItem('quotes:'+tid,JSON.stringify(quotes.get()));}}
function clearComparison(){comparing=false;compareId=null;compareEpoch++;$('compareColumn').hidden=true;$('compareBody').replaceChildren();$('compareSelect').replaceChildren();$('primaryCompareTitle').hidden=true;$('compareArtifacts').textContent='两份对照';$('artifactMore').open=false;}
function renderArtifactPicker(){
  const items=workspace?.artifacts||[],current=items.find(a=>a.id===artifactId);
  const option=a=>`<option value="${esc(a.id)}">${esc(a.title)} · ${esc((a.format||'md').toUpperCase())} · ${new Date(a.created*1000).toLocaleString()}</option>`;
  $('artifactSelect').innerHTML=(current?'':'<option value="" disabled selected>选择产出物</option>')+items.map(option).join('');
  if(current)$('artifactSelect').value=current.id;
  $('artifactSelect').hidden=items.length<2;
  $('artifactTitle').hidden=!!items.length;
  $('artifactTitle').textContent='产出物';
  $('artifactSelect').title='查看全部产出物';
  $('artifactTabs').innerHTML=items.map(a=>`<button class="artifact-tab" data-artifact-tab="${esc(a.id)}" aria-pressed="${a.id===artifactId}" title="${esc(a.title)} · ${esc((a.format||'md').toUpperCase())} · ${new Date(a.created*1000).toLocaleString()}">${esc(a.title)}</button>`).join('');
  artifactStrip.update(artifactId);
  $('artifactInfo').hidden=!current;
  $('artifactInfo').textContent=current?`${(current.format||'md').toUpperCase()} · ${new Date(current.created*1000).toLocaleString()}${current.thread_id===tid?' · 本次对话':''}`:'';
  $('primaryCompareTitle').hidden=!comparing;
  $('primaryCompareTitle').textContent=current?.title||'';
  $('compareSelect').innerHTML=items.filter(a=>a.id!==artifactId).map(option).join('');
  if(compareId)$('compareSelect').value=compareId;
  $('compareSelect').title=items.find(a=>a.id===compareId)?.title||'选择对照产出物';
  $('compareArtifacts').disabled=items.length<2;
}

async function selectThread(id){
  if(id===tid&&!switching&&state.loaded)return;
  saveDraft();stopStream();viewRequests.abort();viewRequests=new AbortController();clearTimeout(renderTimer);const view=++epoch;tid=id;sourceEpoch++;notice();
  modelCatalog=null;selectedModel=null;$('modelSelect').replaceChildren();
  restoring=false;switching=true;buffer=[];requestSignature='';updateControls();
  state.queue=null;renderQueue();
  $('input').value=sessionStorage.getItem('draft:'+tid)||'';
  const savedSkill=sessionStorage.getItem('skill:'+tid)||null;
  let savedQuotes=[];try{savedQuotes=JSON.parse(sessionStorage.getItem('quotes:'+tid)||'[]');}catch{}
  quotes.set(savedQuotes);setSkill(savedSkill);if(savedSkill&&!$('input').value.startsWith('/'))$('input').value=skillInput($('input').value,savedSkill);saveDraft();hideSkillPicker();
  const workbenchURL=`/agent#${workspace.id}/thread/${tid}`;sessionStorage.setItem('workbench-location',workbenchURL);
  if(!settingsUI.isOpen())history.replaceState(null,'',workbenchURL);
  renderWorkspace();
  // Switching is read-only. Skills/configuration are prepared at dispatch.
  state={id,messages:[],status:{type:'idle'},documents:[],questions:[],permissions:[],queue:null};
  $('messageHistory').replaceChildren();$('pendingRequests').replaceChildren();
  $('threadTitle').textContent=workspace.threads.find(t=>t.id===id)?.title||'正在打开对话';
  stopStream=connectEvents(tid,event=>{
    if(view!==epoch)return;
    if(restoring||switching){buffer.push(event);return;}
    receive(event);
  },()=>restore(view),()=>{if(view===epoch)notice('连接已中断，正在重新连接。已保存的内容仍然保留。');});
  await Promise.all([restore(view),loadModels()]);
}

async function restore(view=epoch){
  if(view!==epoch||restoring)return;
  restoring=true;const refresh=++restoreEpoch;buffer=[];updateControls();
  try{
    const fresh=await api(`/api/threads/${tid}`,{signal:viewRequests.signal});
    if(view!==epoch)return;
    state={...fresh,loaded:true,pendingSend:state.pendingSend};reconcilePending(state);renderSkills(fresh.skills||[]);if(source&&!state.documents.some(d=>d.id===source.id)){source=null;sourceEpoch++;sourceNavigation.setDocument(null);$('sourceContent').replaceChildren();}
    const last=state.messages.at(-1);
    state.error=messageIssue(last?.info);
    // Snapshot already includes deltas; replay full updates only to avoid duplicate text.
    for(const event of buffer)if(event.type!=='message.part.delta')applyEvent(state,event);
    buffer=[];restoring=false;switching=false;updateControls();
    $('threadTitle').textContent=state.title;renderQueue();renderMessages();renderRequests();renderDocs();notice();
    const wthread=workspace.threads.find(t=>t.id===tid);if(wthread)wthread.title=state.title;
    await refreshWorkspace();
    if(view!==epoch)return;
    await markThreadSeen(view);
    refreshThreadActivity();
    const selected=workspace.threads.find(t=>t.id===tid);
    if(selected&&threadScope(selected)!==threadFilter){threadFilter=threadScope(selected);renderWorkspace();}
    if(source)$('originalLink').href=`/api/documents/${source.id}/file?thread_id=${tid}`;
    if(!source&&state.documents.length)await loadSource(state.documents.find(d=>d.thread_id===null)?.id||state.documents[0].id);
    else if(source&&!sourceRendered)await renderSource();
  }catch(e){if(view===epoch&&e.name!=='AbortError')notice(e.message+' 点击当前对话可重新加载。','error');}
  finally{if(restoreEpoch===refresh&&view===epoch&&restoring){restoring=false;switching=false;buffer=[];updateControls();}}
}

function receive(event){
  if(unchangedEvent(state,event))return;
  applyEvent(state,event);reconcilePending(state);updateControls();
  if(event.type==='workbench.queue')renderQueue();
  if(event.type.startsWith('question.')||event.type.startsWith('permission.'))renderRequests();
  clearTimeout(renderTimer);renderTimer=setTimeout(renderMessages,50);
  if(event.type.startsWith('question.')||event.type.startsWith('permission.')||
    (event.type==='session.status'&&event.properties.status.type==='idle')){
    restore().catch(e=>notice(e.message,'error'));
  }
  if(event.type==='session.error')notice(state.error,'error');
}

function renderDocs(){
  const documents=orderedDocuments(state.documents),selected=source?.id||documents[0]?.id;
  const attachments=documents.filter(d=>d.thread_id);
  const label=d=>`${d.thread_id?'附件':'主合同'} · ${d.filename}`;
  const current=documents.find(d=>d.id===selected);
  $('documentSelect').innerHTML=documents.map(d=>`<option value="${d.id}">${esc(label(d))}</option>`).join('');
  if(selected)$('documentSelect').value=selected;
  $('documentSelect').hidden=documents.length<2;
  $('documentTitle').hidden=documents.length>1;
  $('documentTitle').textContent=current?label(current):'选择文档';
  $('documentTitle').title=$('documentSelect').title=current?label(current):'';
  $('attachmentCount').textContent=attachments.length;
  $('attachmentList').innerHTML=attachments.map(d=>`<div class="rail-attachment"><button data-open-attachment="${d.id}" title="${esc(d.filename)}">${icon('read')}<span><b>${esc(d.filename)}</b><small>${esc(d.suffix?.slice(1).toUpperCase()||'附件')}</small></span></button><button data-delete-attachment="${d.id}" aria-label="删除附件 ${esc(d.filename)}" ${state.status.type!=='idle'||restoring?'disabled':''}>${icon('close')}</button></div>`).join('')||'<p class="rail-empty">暂无附件，可点击 ＋ 上传补充材料</p>';
}

function renderMessages(){
  const host=$('messageHistory'),scroll=$('msgs'),atBottom=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;
  const open=new Set([...host.querySelectorAll('details[open]')].map(d=>d.dataset.key));
  const html=conversationHTML(state,open)||welcomeHTML(state.documents);
  if(host.innerHTML!==html)host.innerHTML=html;
  const tasks=$('todos').querySelector('details'),todo=todosHTML(state,tasks?.open);
  $('todos').hidden=!todo;
  if($('todos').innerHTML!==todo)$('todos').innerHTML=todo;
  if(atBottom)scroll.scrollTop=scroll.scrollHeight;
}

function renderRequests(){
  const signature=JSON.stringify([state.questions,state.permissions]);
  if(signature===requestSignature)return;
  const scroll=$('msgs'),atBottom=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;
  requestSignature=signature;$('pendingRequests').innerHTML=requestsHTML(state);
  if(atBottom)requestAnimationFrame(()=>scroll.scrollTop=scroll.scrollHeight);
}

async function loadSource(docid){
  const view=epoch,load=++sourceEpoch;
  const mapped=await api(`/api/documents/${docid}?thread_id=${tid}`);
  if(view!==epoch||load!==sourceEpoch)return;
  source=mapped;sourceNavigation.setDocument(source);renderDocs();quotes.hide();$('sourceNavigationStatus').hidden=true;$('documentSelect').value=docid;
  $('originalLink').href=`/api/documents/${docid}/file?thread_id=${tid}`;$('originalLink').hidden=false;
  await renderSource();
}

async function renderSource(){
  if(!source)return;
  const host=$('sourceContent'),doc=source,view=epoch,load=sourceEpoch,render=++sourceRenderEpoch;
  sourceRendered=false;
  sourceNavigation.loading();
  const url=`/api/documents/${doc.id}/file?thread_id=${tid}`;
  for(const mode of ['text','original']){const button=$(mode==='text'?'viewText':'viewOriginal');button.disabled=false;button.setAttribute('aria-pressed',String(sourceMode===mode));}
  host.classList.toggle('source-original-text',sourceMode==='original'&&doc.kind==='text');
  if(sourceMode==='text'||doc.kind==='text'){
    host.innerHTML=doc.segments.map((s,i)=>`<div class="source-block" ${s.skip?'data-search-skip':''}><small>${i+1}</small><span data-block="B${i}">${esc(s.text)}</span></div>`).join('');
    sourceRendered=true;sourceNavigation.refresh();return;
  }
  if(doc.kind==='pdf'){
    host.innerHTML=pdfMarkup(doc,tid);fitPdfText(host);
  }else{
    host.innerHTML='<p class="placeholder">正在渲染 Word 原件…</p>';
    try{
      const response=await fetch(url);if(!response.ok)throw new Error('Word 原件加载失败');
      const renderHost=document.createElement('div');
      await window.docx.renderAsync(await response.blob(),renderHost,null,{inWrapper:true,useBase64URL:true,breakPages:true,ignoreLastRenderedPageBreak:false});
      if(view!==epoch||load!==sourceEpoch||render!==sourceRenderEpoch||sourceMode!=='original')return;
      host.replaceChildren(renderHost);
      const nodes=[...host.querySelectorAll('section.docx article p, section.docx article tr')].filter(n=>n.tagName==='TR'||!n.closest('tr'));
      let cursor=0;
      for(const s of doc.segments){
        if(s.skip)continue;
        const normalize=t=>t.replace(/[\s|#*]/g,'');
        const needle=normalize(s.text);
        const found=nodes.findIndex((n,i)=>i>=cursor&&normalize(n.textContent).includes(needle));
        if(found>=0){nodes[found].dataset.block=s.id;cursor=found+1;}
      }
    }catch(e){if(view!==epoch||load!==sourceEpoch||render!==sourceRenderEpoch)return;sourceMode='text';await renderSource();notice('原件预览暂不可用，已显示可定位的原文文本。');return;}
  }
  sourceRendered=true;sourceNavigation.refresh();
}

async function navigateOutline(entry){
  if(!source)return;
  if(entry.block_id)return navigateCitation(source.id,entry.block_id,source.source_hash);
  const target=$('sourceContent').querySelector(`.pdf-page[data-page="${entry.page}"]`);
  if(target){
    const host=$('sourceContent');host.scrollTop+=target.getBoundingClientRect().top-host.getBoundingClientRect().top;
    $('sourceNavigationStatus').hidden=false;$('sourceNavigationStatus').textContent=`已定位：${source.filename} · 第 ${entry.page} 页`;
  }else{
    const segment=source.segments.find(s=>s.page===entry.page);
    if(segment)await navigateCitation(source.id,segment.id,source.source_hash);
    else notice('该页没有可定位文本，请切换到原件查看。');
  }
}

window.addEventListener('message',protect(async event=>{
  if(switching||!state.loaded)return;
  const ref=previewCitation(event,document.querySelectorAll('iframe[data-artifact-preview]'),state.documents);
  if(ref)await navigateCitation(ref.docid,ref.block,ref.hash,ref.end);
}));

async function navigateCitation(docid,block,hash,end=block){
  if(!state.documents.some(d=>d.id===docid&&d.source_hash===hash))throw new Error('该引用不属于当前对话或版本已改变');
  reading.showSource();document.body.classList.add('context-mobile');document.querySelector('main').classList.remove('context-closed');
  if(source?.id!==docid)await loadSource(docid);
  if(source.source_hash!==hash)throw new Error('原文版本已改变，请重新生成引用');
  const first=source.segments.findIndex(s=>s.id===block),last=source.segments.findIndex(s=>s.id===end);
  if(first<0||last<first)throw new Error('原文位置不存在');
  const segments=source.segments.slice(first,last+1),seg=segments[0];
  document.querySelectorAll('.highlight,.source-highlight').forEach(n=>n.classList.remove('highlight','source-highlight'));
  document.querySelectorAll('.pdf-highlight').forEach(n=>n.remove());
  const targets=()=>segments.map(s=>$('sourceContent').querySelector(`[data-block="${s.id}"]`));
  if(targets().some(t=>!t)){sourceMode='text';await renderSource();}
  targets().forEach(t=>t?.classList.add('highlight'));targets()[0]?.scrollIntoView({block:'center',behavior:'smooth'});
  const pages=seg.page?(seg.page===segments.at(-1).page?`第 ${seg.page} 页 · `:`第 ${seg.page}–${segments.at(-1).page} 页 · `):'';
  $('sourceNavigationStatus').hidden=false;$('sourceNavigationStatus').textContent=`已定位：${source.filename} · ${pages}${first===last?'第 '+(first+1)+' 段':'第 '+(first+1)+'–'+(last+1)+' 段（连续 '+segments.length+' 段）'}`;
}

async function openArtifact(id,asCompare=false,reveal=true){
  const view=epoch,load=asCompare?++compareEpoch:++artifactEpoch;
  const data=await api(`/api/artifacts/${id}`);
  if(view!==epoch||load!==(asCompare?compareEpoch:artifactEpoch))return;
  if(!asCompare&&id===compareId)clearComparison();
  artifactData.set(id,data);
  if(reveal)document.body.classList.remove('rail-mobile');
  if(asCompare){compareId=id;$('compareColumn').hidden=false;$('compareBody').innerHTML=artifactHTML(data,state.documents,tid);$('compareSelect').title=data.title;}
  else{artifactId=id;$('artBody').innerHTML=artifactHTML(data,state.documents,tid);$('artifactTitle').textContent=data.title;
    $('artifactDownloads').innerHTML=(data.formats||['md','docx']).map(f=>`<a href="/api/artifacts/${id}/file?format=${f}">下载 ${f==='docx'?'Word':f.toUpperCase()}</a>`).join('');}
  renderArtifactPicker();$('artifactMore').open=false;
  if(reveal){document.body.classList.add('context-mobile');document.querySelector('main').classList.remove('context-closed');}
}

async function removeAttachment(id){
  const view=epoch,current=tid;
  await api(`/api/threads/${current}/attachments/${id}`,{method:'DELETE'});
  if(view!==epoch)return;
  quotes.removeDocument(id);
  if(source?.id===id){source=null;sourceEpoch++;sourceNavigation.setDocument(null);$('sourceContent').replaceChildren();}
  await restore();notice('附件已删除。历史对话中的既有内容仍保留，后续分析不再使用该附件。');
}
function hideSkillPicker(){$('skillPicker').hidden=true;$('input').setAttribute('aria-expanded','false');$('input').removeAttribute('aria-activedescendant');}
function renderSkills(catalog){
  skillCatalog=catalog;
  $('skillActions').innerHTML=catalog.map(s=>`<button data-skill="${esc(s.name)}" title="${esc(s.description)}">${esc(s.label)}</button>`).join('');
  setSkill(catalog.some(s=>s.name===selectedSkill)?selectedSkill:null);
  if(!$('skillPicker').hidden)renderSkillPicker();
}
function renderSkillPicker(){
  const list=matchingSkills($('input').value,skillCatalog);
  if(!list)return hideSkillPicker();
  skillIndex=Math.min(skillIndex,Math.max(0,list.length-1));
  $('skillPicker').hidden=false;$('input').setAttribute('aria-expanded','true');
  $('skillPicker').innerHTML='<div class="picker-hint">SKILLS · ↑ ↓ 选择 · Tab / Enter 确认 · Esc 关闭</div>'+list.map((s,i)=>`<button id="skill-option-${i}" role="option" aria-selected="${i===skillIndex}" data-pick-skill="${esc(s.name)}"><b>/${esc(s.name)}</b><small>${esc(s.label)} · ${esc(s.description)}</small></button>`).join('')+(list.length?'':'<div class="picker-hint">没有匹配的 Skill，可点击“刷新 Skills”重新发现</div>');
  if(list.length)$('input').setAttribute('aria-activedescendant','skill-option-'+skillIndex);
}
function pickSkill(name){$('input').value=skillInput($('input').value,name);setSkill(name);hideSkillPicker();saveDraft();$('input').focus();}

async function send(){
  if(!tid||sending||restoring||switching||!selectedModel||modelSaving)return;
  let entered=$('input').value.trim();
  if(!entered){notice('请输入内容后再发送。');$('input').focus();return;}
  const command=entered.match(/^\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)/);
  setSkill(command&&skillCatalog.some(s=>s.name===command[1])?command[1]:null);
  if(selectedSkill)entered=entered.slice(command[0].length);
  const text=entered||(selectedSkill?`请使用 ${selectedSkill} 处理当前合同并保存结果。`:'');
  if(!text)return;
  const target=tid,view=epoch,original=$('input').value;
  const body={text,risk_scheme:$('riskSchemeSelect').value||undefined,skill:selectedSkill,quotes:quotes.get(),model:selectedModel};
  const stamp=JSON.stringify([target,body]);
  if(submission?.stamp!==stamp)submission={stamp,id:crypto.randomUUID()};
  const originalSkill=selectedSkill,originalQuotes=JSON.stringify(quotes.get());
  sending=true;state.pendingSend={request_id:submission.id,body,status:'sending'};notice();updateControls();renderMessages();
  try{
    const result=await api(`/api/threads/${target}/messages`,{method:'POST',body:{...body,request_id:submission.id}});
    submission=null;
    if(view!==epoch){
      if(sessionStorage.getItem('draft:'+target)===original){sessionStorage.removeItem('draft:'+target);sessionStorage.removeItem('skill:'+target);sessionStorage.removeItem('quotes:'+target);}
      return;
    }
    if($('input').value===original&&selectedSkill===originalSkill&&JSON.stringify(quotes.get())===originalQuotes){$('input').value='';setSkill(null);quotes.set([]);saveDraft();}
    state.queue=result.queue;
    if(state.pendingSend){state.pendingSend.id=result.id;state.pendingSend.status=result.status;}
    reconcilePending(state);
    if(result.status==='submitted'){state.status={type:'busy'};state.error=null;}
    renderQueue();renderMessages();
  }catch(e){
    if(view===epoch&&state.pendingSend){state.pendingSend.status='failed';renderMessages();}
    throw e;
  }finally{sending=false;updateControls();}
}

function draftValue(){return {text:$('input').value,skill:selectedSkill,quotes:quotes.get(),model:selectedModel,risk_scheme:$('riskSchemeSelect').value};}
function cachedDrafts(){try{return restoreDraft({}, {}, JSON.parse(sessionStorage.getItem('saved-drafts:'+tid)||'[]')).saved;}catch{return [];}}
function renderQueue(){
  const shown=pendingRequest(state),queue=state.queue;
  const html=queueHTML(queue?{...queue,items:(queue.items||[]).filter(i=>queue.paused||i.status==='failed'||i.id!==shown?.id)}:queue,modelCatalog?.models||[]),root=$('messageQueue');root.hidden=!html;
  if(root.innerHTML!==html)root.innerHTML=html;
  const drafts=cachedDrafts(),slot=$('savedDrafts');slot.hidden=!drafts.length;
  slot.innerHTML=drafts.map((d,i)=>`<button type="button" data-restore-draft="${i}" title="${esc(d.text)}">恢复草稿：${esc((d.text||d.skill||"引用内容").slice(0,24))}</button>`).join('');
}
function editDraft(body,saved=cachedDrafts()){
  const result=restoreDraft(body,draftValue(),saved);
  sessionStorage.setItem('saved-drafts:'+tid,JSON.stringify(result.saved));
  $('input').value=body.skill?skillInput(body.text||'',body.skill):body.text||'';setSkill(body.skill||null);quotes.set(body.quotes||[]);
  if(body.model&&modelCatalog?.models.some(m=>m.id===body.model)){selectedModel=body.model;$('modelSelect').value=body.model;modelCatalog.available=true;}
  if(body.risk_scheme){state.risk_scheme=body.risk_scheme;$('riskSchemeSelect').value=body.risk_scheme;}
  saveDraft();renderQueue();$('input').focus();
}
$('messageQueue').onclick=protect(async e=>{
  const button=e.target.closest('button');if(!button||button.disabled)return;
  const view=epoch,target=tid;button.disabled=true;
  try{
    if(button.dataset.withdrawMessage){
      button.textContent='正在撤回…';
      const result=await api(`/api/threads/${target}/queue/${button.dataset.withdrawMessage}`,{method:'DELETE'});
      if(view!==epoch){const saved=JSON.parse(sessionStorage.getItem('saved-drafts:'+target)||'[]');sessionStorage.setItem('saved-drafts:'+target,JSON.stringify(restoreDraft({},result.body,saved).saved));return;}
      state.queue=result.queue;reconcilePending(state);renderMessages();editDraft(result.body);notice('已撤回到输入框。'+(cachedDrafts().length?'原有的不同草稿已暂存。':''));
    }else if(button.hasAttribute('data-queue-resume')){
      const queue=await api(`/api/threads/${target}/queue/resume`,{method:'POST',body:{}});
      if(view===epoch){state.queue=queue;renderQueue();updateControls();}
    }
  }finally{button.disabled=false;if(button.dataset.withdrawMessage)button.textContent='撤回并重新编辑';}
});
$('savedDrafts').onclick=e=>{const button=e.target.closest('[data-restore-draft]');if(!button)return;const saved=cachedDrafts(),[body]=saved.splice(Number(button.dataset.restoreDraft),1);if(body)editDraft(body,saved);};
let lastQueuePoll=0;
setInterval(async()=>{
  if(!tid||queuePolling||switching||restoring||document.hidden)return;
  const active=state.status?.type!=='idle'||state.queue?.active||state.queue?.items?.length;
  if(Date.now()-lastQueuePoll<(active?1500:10000))return;
  lastQueuePoll=Date.now();
  const view=epoch,target=tid;queuePolling=true;
  try{const queue=await api(`/api/threads/${target}/queue`);if(view===epoch&&JSON.stringify(state.queue)!==JSON.stringify(queue)){state.queue=queue;reconcilePending(state);renderQueue();renderMessages();updateControls();}}
  catch{/* Reconnect and the next poll refresh the durable outbox. */}
  finally{queuePolling=false;}
},1500);

function setSkill(skill){selectedSkill=skill;$('selectedSkill').hidden=true;$('selectedSkill').replaceChildren();}


async function loadRiskSchemes(){
  riskSchemeOptions=await api('/api/risk-schemes/options');
  if(state.risk_scheme&&!riskSchemeOptions.schemes.some(s=>s.enabled&&s.id===state.risk_scheme))state.risk_scheme=null;
  $('riskSchemeSelect').innerHTML=riskSchemeOptions.schemes.filter(s=>s.enabled).map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join('');
  $('riskSchemeSelect').value=state.risk_scheme||riskSchemeOptions.selected||'';
}
$('riskSchemeSelect').onchange=()=>{state.risk_scheme=$('riskSchemeSelect').value;};
async function loadModels(){
  const view=epoch,target=tid;
  const catalog=await api('/api/models'+(target?'?thread_id='+encodeURIComponent(target):''),{signal:viewRequests.signal});
  if(view!==epoch)return;
  modelCatalog=catalog;selectedModel=modelCatalog.selected;
  $('modelSelect').innerHTML=modelCatalog.models.map(m=>`<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('');
  if(!modelCatalog.available)$('modelSelect').insertAdjacentHTML('afterbegin','<option value="">请选择可用模型</option>');
  $('modelSelect').value=modelCatalog.available?selectedModel:'';renderQueue();updateControls();
}
$('modelSelect').onchange=protect(async e=>{
  const view=epoch,target=tid,previous=selectedModel,next=e.target.value;modelSaving=true;updateControls();
  try{await api('/api/threads/'+target+'/model',{method:'PUT',body:{model:next}});if(view===epoch){selectedModel=next;modelCatalog.available=true;}}
  catch(error){if(view===epoch)e.target.value=previous;throw error;}
  finally{modelSaving=false;updateControls();}
});
$('permissionMode').onchange=protect(async e=>{
  const view=epoch,current=tid,next=e.target.value;permissionSaving=true;permissionTarget={tid:current,mode:next};permissionSpinner=false;updateControls();
  const timer=setTimeout(()=>{if(permissionSaving&&view===epoch){permissionSpinner=true;updateControls();}},300);
  try{const result=await api(`/api/threads/${current}/permission-mode`,{method:'PUT',body:{mode:next}});if(view===epoch){state.permission_mode=result.permission_mode;state.permission_override=true;}}
  finally{clearTimeout(timer);permissionSaving=false;permissionSpinner=false;permissionTarget=null;updateControls();}
});

$('loginForm').addEventListener('submit',async e=>{e.preventDefault();$('loginError').textContent='';try{const f=new FormData(e.target);await api('/api/login',{method:'POST',body:Object.fromEntries(f)});e.target.password.value='';await initialize();}catch(err){$('loginError').textContent=err.message;if(document.body.dataset.auth==='loading')initializationFailed(err);}});
$('logout').onclick=protect(async()=>{await api('/api/logout',{method:'POST',body:{}});sessionStorage.clear();loggedOut();});
$('uploadButton').onclick=()=>{$('workspaceSwitcher').open=false;$('uploadInput').click();};
$('workspaceSearch').oninput=renderWorkspaceOptions;
$('workspaceSwitcher').addEventListener('toggle',protect(async()=>{if($('workspaceSwitcher').open){$('workspaceSearch').value='';renderWorkspaceOptions();$('workspaceSearch').focus();await loadList();}}));
$('uploadInput').onchange=protect(async e=>{const file=e.target.files[0];if(!file)return;notice('正在解析合同…');const w=await upload('/api/workspaces',file);e.target.value='';document.body.classList.remove('rail-mobile');await selectWorkspace(w.id);});
$('newThread').onclick=protect(async()=>{
  if(!workspace||creatingThread)return;
  const wid=workspace.id,view=epoch;creatingThread=true;updateControls();
  try{
    const t=await api(`/api/workspaces/${wid}/threads`,{method:'POST',body:{}});
    if(view!==epoch||workspace?.id!==wid)return;
    threadFilter='active';await refreshWorkspace();
    if(view===epoch&&workspace?.id===wid)await selectThread(t.id);
  }finally{creatingThread=false;updateControls();}
});
$('attachButton').onclick=$('railAttachButton').onclick=()=>$('attachmentInput').click();
$('attachmentInput').onchange=protect(async e=>{const file=e.target.files[0];if(!file)return;await upload(`/api/threads/${tid}/attachments`,file);e.target.value='';await restore();});
$('sendBtn').onclick=protect(send);$('input').oninput=()=>{const command=$('input').value.match(/^\/([a-z0-9-]+)(?:\s|$)/);setSkill(command&&skillCatalog.some(s=>s.name===command[1])?command[1]:null);saveDraft();skillIndex=0;renderSkillPicker();};
$('input').onkeydown=e=>{
  if(e.isComposing)return;
  if(!$('skillPicker').hidden){
    const list=matchingSkills($('input').value,skillCatalog)||[];
    if(e.key==='Escape'){e.preventDefault();hideSkillPicker();return;}
    if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();skillIndex=(skillIndex+(e.key==='ArrowDown'?1:-1)+Math.max(1,list.length))%Math.max(1,list.length);renderSkillPicker();return;}
    if((e.key==='Tab'||e.key==='Enter')&&!e.shiftKey){e.preventDefault();if(list[skillIndex])pickSkill(list[skillIndex].name);return;}
  }
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();protect(send)();}
};
$('stopButton').onclick=protect(async()=>{
  const target=tid,view=epoch;
  if(!target||stoppingThread===target)return;
  stoppingThread=target;updateControls();
  try{
    await api(`/api/threads/${target}/abort`,{method:'POST',body:{}});
    if(view!==epoch)return;
    await restore();
    if(view===epoch)notice(state.queue?.items?.length?'已取消当前任务，已有排队消息保持暂停。':'已取消当前任务，可以直接发送新消息。');
  }finally{if(stoppingThread===target)stoppingThread=null;updateControls();}
});
$('documentSelect').onchange=protect(e=>loadSource(e.target.value));
$('artifactSelect').onchange=protect(async e=>{try{await openArtifact(e.target.value);}finally{renderArtifactPicker();}});
$('artifactTabs').onclick=protect(async e=>{const button=e.target.closest('[data-artifact-tab]');if(button)await openArtifact(button.dataset.artifactTab);});
$('compareSelect').onchange=protect(async e=>{try{await openArtifact(e.target.value,true);}finally{renderArtifactPicker();}});
$('closeArtifactComparison').onclick=()=>{clearComparison();renderArtifactPicker();};
$('compareArtifacts').onclick=protect(async()=>{
  if(comparing){clearComparison();renderArtifactPicker();return;}
  const other=workspace.artifacts.find(a=>a.id!==artifactId);if(!other)return;
  if(!artifactId)await openArtifact(workspace.artifacts[0].id);
  comparing=true;$('compareArtifacts').textContent='结束两份对照';
  reading.showArtifact();
  try{await openArtifact(workspace.artifacts.find(a=>a.id!==artifactId).id,true);}catch(error){clearComparison();renderArtifactPicker();throw error;}
});
$('viewText').onclick=protect(async()=>{sourceMode='text';await renderSource();});
$('viewOriginal').onclick=protect(async()=>{sourceMode='original';await renderSource();});
function syncPanelToggles(){
  const mobile=innerWidth<=1020;
  const states=[['toggleRail','工作区',mobile?document.body.classList.contains('rail-mobile'):!document.body.classList.contains('workspace-rail-collapsed')],['toggleContext','原文与产出物',mobile?document.body.classList.contains('context-mobile'):!document.querySelector('main').classList.contains('context-closed')]];
  for(const [id,label,expanded] of states){const button=$(id);button.setAttribute('aria-expanded',String(expanded));button.title=(expanded?'折叠':'显示')+label;button.setAttribute('aria-label',button.title);}
}
const panelStateObserver=new MutationObserver(syncPanelToggles);
for(const target of [document.body,document.querySelector('main')])panelStateObserver.observe(target,{attributes:true,attributeFilter:['class']});
window.matchMedia('(max-width:1020px)').addEventListener('change',syncPanelToggles);
syncPanelToggles();
$('toggleRail').onclick=()=>{if(innerWidth<=1020)document.body.classList.toggle('rail-mobile');else document.body.classList.toggle('workspace-rail-collapsed');};
$('toggleContext').onclick=()=>{if(innerWidth<=1020)document.body.classList.toggle('context-mobile');else document.querySelector('main').classList.toggle('context-closed');};
document.addEventListener('click',protect(async e=>{
  if(!e.target.closest('#workspaceSwitcher'))$('workspaceSwitcher').open=false;
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.welcomePrompt){
    if(!tid||restoring||switching||$('input').disabled)return;
    const draft=$('input').value;
    $('input').value=draft.trim()?`${draft}\n\n${b.dataset.welcomePrompt}`:b.dataset.welcomePrompt;
    setSkill(null);hideSkillPicker();saveDraft();$('input').focus();return;
  }
  if((restoring||switching)&&(b.dataset.doc||b.dataset.permission||b.dataset.quoteOpen!==undefined||b.dataset.openAttachment))return;
  if(b.id==='removeSkill'){setSkill(null);saveDraft();$('input').focus();}
  if(b.dataset.workspace){
    if(settingsUI.isOpen()&&!await settingsUI.close())return;
    $('workspaceSwitcher').open=false;document.body.classList.remove('rail-mobile');await selectWorkspace(b.dataset.workspace);
  }
  if(b.dataset.threadAction){await manageThread(b.dataset.tid,b.dataset.threadAction);return;}
  if(b.dataset.thread){document.body.classList.remove('rail-mobile');await selectThread(b.dataset.thread);}
  if(b.dataset.artifact)await openArtifact(b.dataset.artifact,!!(comparing&&artifactId&&b.dataset.artifact!==artifactId));
  if(b.dataset.skill)pickSkill(b.dataset.skill);
  if(b.dataset.pickSkill)pickSkill(b.dataset.pickSkill);
  if(b.dataset.deleteAttachment)await removeAttachment(b.dataset.deleteAttachment);
  if(b.dataset.openAttachment)await loadSource(b.dataset.openAttachment);
  if(b.dataset.quoteOpen!==undefined){const q=quotes.get()[Number(b.dataset.quoteOpen)];await navigateCitation(q.document_id,q.block_ids[0],q.source_hash);}
  if(b.dataset.doc)await navigateCitation(b.dataset.doc,b.dataset.block,b.dataset.hash,b.dataset.end||b.dataset.block);
  const board=b.closest('[data-risk-board]'),data=board&&artifactData.get(board.dataset.riskBoard);
  if(data&&b.dataset.riskFilterChoice){board.outerHTML=riskBoard(data,state.documents,b.dataset.riskFilterChoice);}
  if(b.dataset.permission)await submitRequest('permission',b.dataset.permission,{reply:b.dataset.reply},b.closest('.request-card'));
}));
document.addEventListener('submit',async e=>{
  const form=e.target;if(!form.matches('[data-risk-feedback]'))return;e.preventDefault();
  const board=form.closest('[data-risk-board]'),data=artifactData.get(board.dataset.riskBoard),rid=form.dataset.riskFeedback,view=epoch;
  const button=form.querySelector('[type="submit"]'),status=form.querySelector('.feedback-status');button.disabled=true;status.textContent='正在保存…';
  try{
    const feedback=await api(`/api/artifacts/${data.id}/risks/${encodeURIComponent(rid)}/feedback`,{method:'PUT',body:{decision:form.elements.decision.value,note:form.elements.note.value,revision:Number(form.dataset.revision),source_hash:data.source_hash}});
    if(view!==epoch)return;data.feedback={...data.feedback,[rid]:feedback};
    board.outerHTML=riskBoard(data,state.documents,board.dataset.riskFilter);notice('反馈已保存。');
  }catch(error){status.textContent=error.message;}
  finally{button.disabled=false;}
});
async function submitRequest(kind,rid,body,card){
  const target=tid,view=epoch;
  if(switching||restoring||state.id!==target||!card||card.dataset.submitting)return;
  const field=kind==='permission'?'permissions':'questions';
  if(!state[field]?.some(r=>r.id===rid))return;
  card.dataset.submitting='true';card.querySelectorAll('button,input').forEach(b=>b.disabled=true);
  const status=document.createElement('p');status.setAttribute('role','status');status.textContent='正在提交，请稍候…';card.append(status);
  try{
    await api(`/api/threads/${target}/requests/${kind}/${rid}`,{method:'POST',body});
    if(view!==epoch)return;
    state[field]=state[field].filter(r=>r.id!==rid);renderRequests();notice('已提交，助手将继续处理。');
  }catch(error){
    if(view!==epoch)return;
    if(error.status===404){await restore(view);if(view===epoch)notice('该请求已失效或已处理，已更新当前对话。');}
    else{delete card.dataset.submitting;card.querySelectorAll('button,input').forEach(b=>b.disabled=false);status.textContent=error.message;}
  }
}
$('pendingRequests').addEventListener('submit',protect(async e=>{
  e.preventDefault();if(restoring||switching)return;const q=state.questions.find(q=>q.id===e.target.dataset.question);const form=new FormData(e.target);
  if(!q)return;
  const answers=q.questions.map((_,i)=>{const free=String(form.get('free'+i)||'').trim();return free?[free]:form.getAll('q'+i);});
  if(answers.some(a=>!a.length))throw new Error('请回答每个问题');
  if(q)await submitRequest('question',q.id,{answers},e.target);
}));
let dragging=false;$('splitL').onpointerdown=e=>{dragging=true;e.target.setPointerCapture(e.pointerId);};
$('splitL').onpointermove=e=>{if(dragging){const main=document.querySelector('main');main.style.setProperty('--chat-w',Math.max(300,Math.min(e.clientX-main.getBoundingClientRect().left,main.clientWidth-300))+'px');}};
$('splitL').onpointerup=()=>dragging=false;$('splitL').onpointercancel=()=>dragging=false;
$('splitL').onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){const main=document.querySelector('main');main.style.setProperty('--chat-w',Math.max(300,$('chatPane').offsetWidth+(e.key==='ArrowRight'?20:-20))+'px');}};
window.addEventListener('hashchange',protect(async()=>{const m=location.hash.match(/^#([a-f0-9]+)(?:\/thread\/([a-f0-9]+))?$/);if(m&&(m[1]!==workspace?.id||m[2]!==tid)){try{await selectWorkspace(m[1],m[2]);}catch(error){if(error.status===404){location.replace('/spaces?notice=missing');return;}throw error;}}}));
window.addEventListener('beforeunload',saveDraft);

async function initialize(){
  await setupAuth();
  const route=settingsTab(location.pathname);
  document.body.dataset.auth='loading';$('authLoading').hidden=false;$('authLoadingText').textContent='正在打开工作台…';$('authRetry').hidden=true;$('loginView').hidden=true;
  const me=await api('/api/me');document.body.dataset.auth='ready';$('authLoading').hidden=true;$('username').textContent=me.account_kind==='demo'?'':me.username;
  if(route)await settingsUI.open(route,{historyMode:'replace',user:me});
  const results=await Promise.allSettled([loadList(),loadModels(),loadRiskSchemes()]);
  for(const result of results)if(result.status==='rejected')notice(result.reason.message,'error');
  const hash=location.hash||(route?new URL(savedWorkbenchURL(sessionStorage.getItem('workbench-location')),location.origin).hash:'');
  const m=hash.match(/^#([a-f0-9]+)(?:\/thread\/([a-f0-9]+))?$/);
  if(m){try{await selectWorkspace(m[1],m[2]);}catch(error){if(error.status===404){location.replace('/spaces?notice=missing');return;}throw error;}}
  else if(workspaces.length)await selectWorkspace(workspaces[0].id);else if(!route)location.replace('/spaces');updateControls();void accountReady(me);
}
function initializationFailed(e){
  if(e.status===401)return;
  if(document.body.dataset.auth==='ready')notice(e.message,'error');
  else{$('authLoadingText').textContent='暂时无法连接工作台。';$('authRetry').hidden=false;}
}
$('authRetry').onclick=()=>initialize().catch(initializationFailed);
initialize().catch(initializationFailed);
