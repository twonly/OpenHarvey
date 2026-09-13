import {setupAuth,exchangeCallback,accountReady} from './account-ui.js?v=20260913-header-2';
import {accountIdentityHTML} from './account-identity.js';
import {api,upload} from './api.js';
import {filteredWorkspaces,workspaceRows} from './spaces-ui.js';

const $=id=>document.getElementById(id);
let items=[],scope='active',busy=false;
function notice(text=''){$('notice').hidden=!text;$('notice').textContent=text;}
function render(){
  const active=items.filter(item=>!item.deleted_at),deleted=items.filter(item=>item.deleted_at);
  $('activeCount').textContent=active.length;$('starredCount').textContent=active.filter(item=>item.starred).length;$('deletedCount').textContent=deleted.length;
  $('summary').innerHTML=`<article><span>有效合同</span><b>${active.length}</b><small>独立合同空间</small></article><article><span>重点关注</span><b>${active.filter(item=>item.starred).length}</b><small>置顶优先处理</small></article><article><span>全部会话</span><b>${active.reduce((sum,item)=>sum+Number(item.thread_count),0)}</b><small>保留完整上下文</small></article><article><span>已存产出</span><b>${active.reduce((sum,item)=>sum+Number(item.artifact_count),0)}</b><small>摘要与审查报告</small></article>`;
  document.querySelectorAll('[data-scope]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.scope===scope)));
  $('spaceList').innerHTML=workspaceRows(filteredWorkspaces(items,{scope,query:$('searchInput').value,sort:$('sortSelect').value}));
}
async function load(){items=await api('/api/workspaces?scope=all');render();}
function loggedOut(){document.body.dataset.auth='logged-out';$('authLoading').hidden=true;$('spacesApp').hidden=true;$('loginView').hidden=false;}
document.addEventListener('session-expired',loggedOut);

function confirmAction(item,action){
  const dialog=$('confirmDialog'),purge=action==='purge';dialog.returnValue='cancel';
  $('confirmHeading').textContent=purge?'永久删除这个合同空间？':'删除这个合同空间？';
  $('confirmCopy').innerHTML=purge?`“<b></b>”的合同、全部会话、附件和产出物将被永久清除，无法恢复。`:`“<b></b>”将移入最近删除。合同、对话、附件和产出物都会保留。`;
  $('confirmCopy').querySelector('b').textContent=item.title;$('confirmAction').textContent=purge?'永久删除':'确认删除';
  return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='confirm');dialog.showModal();});
}
function renameAction(item){
  const dialog=$('renameDialog'),input=$('renameInput');dialog.returnValue='cancel';input.value=item.title;dialog.showModal();input.select();
  return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='save'?input.value.trim():'');});
}

$('loginForm').onsubmit=async event=>{event.preventDefault();$('loginError').textContent='';try{const form=new FormData(event.target);await api('/api/login',{method:'POST',body:Object.fromEntries(form)});event.target.password.value='';await initialize();}catch(error){$('loginError').textContent=error.message;}};
$('logout').onclick=async()=>{await api('/api/logout',{method:'POST',body:{}});loggedOut();};
$('searchInput').oninput=render;$('sortSelect').onchange=render;
document.querySelector('.scope-tabs').onclick=event=>{const button=event.target.closest('[data-scope]');if(button){scope=button.dataset.scope;render();}};
$('uploadButton').onclick=()=>$('uploadInput').click();
$('uploadInput').onchange=async event=>{const file=event.target.files[0];if(!file)return;notice('正在解析并建立合同空间…');$('uploadButton').disabled=true;try{const item=await upload('/api/workspaces',file);location.href=`/agent#${item.id}`;}catch(error){notice(error.message);}finally{event.target.value='';$('uploadButton').disabled=false;}};
$('spaceList').onclick=async event=>{
  const button=event.target.closest('[data-space-action]');if(!button||busy)return;
  const id=button.dataset.spaceId,item=items.find(row=>row.id===id);if(!item)return;
  const action=button.dataset.spaceAction,body={action};
  if((action==='delete'||action==='purge')&&!await confirmAction(item,action))return;
  if(action==='delete'||action==='purge')body.confirmed=true;
  if(action==='rename'){body.title=await renameAction(item);if(!body.title)return;}
  busy=true;$('spaceList').inert=true;
  try{
    const result=await api(`/api/workspaces/${id}`,{method:'PATCH',body});
    if(result.purged)items=items.filter(row=>row.id!==id);else Object.assign(item,result);
    render();notice({star:'已加入重点关注。',unstar:'已取消重点关注。',rename:'合同空间已重命名。',delete:'已移入最近删除。',restore:'合同空间已恢复。',purge:'合同空间已永久删除。'}[action]);
  }catch(error){await load();notice(error.message);}finally{busy=false;$('spaceList').inert=false;}
};

async function initialize(){
  await setupAuth();if(await exchangeCallback())return;
  document.body.dataset.auth='loading';$('authLoading').hidden=false;$('loginView').hidden=true;
  if(location.pathname==='/login'){loggedOut();return;}
  try{const me=await api('/api/me');$('username').innerHTML=accountIdentityHTML(me);await load();document.body.dataset.auth='ready';$('authLoading').hidden=true;$('spacesApp').hidden=false;void accountReady(me);const message=new URLSearchParams(location.search).get('notice');if(message==='missing'){notice('该合同空间已删除、不存在，或不属于当前账号。');history.replaceState(null,'','/spaces');}}
  catch(error){if(error.status!==401){$('authLoading').textContent='暂时无法连接工作台';notice(error.message);}}
}
initialize();
