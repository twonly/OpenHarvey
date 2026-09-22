import {api} from './api.js';
import {esc} from './markdown.js';
import {t as tr,getLanguage} from './i18n.js';

export function memoryItemHTML(item,{historical=false}={}){
  const deleted=historical&&item.current_revision==null,changed=historical&&item.current_revision!==item.revision&&!deleted;
  return `<article class="memory-item"><p>${esc(item.content)}</p><footer><small>${tr(item.source==='conversation'?'来自对话':'手动添加')} · ${esc(new Date(item.updated*1000).toLocaleString(getLanguage()))} · v${item.revision}${deleted?' · '+tr('已删除'):changed?' · '+tr('已有新版本'):''}</small>${!deleted?`<span><button type="button" data-memory-edit="${esc(item.id)}">${tr('编辑')}</button><button type="button" data-memory-delete="${esc(item.id)}">${tr('删除')}</button></span>`:''}</footer></article>`;
}
export function memoryReferencesHTML(parts,open=new Set(),key=''){
  const items=[...new Map(parts.flatMap(p=>p.memory_references||[]).map(i=>[i.id+':'+i.revision,i])).values()];
  if(!items.length)return '';
  const id='memory-'+key;
  return `<details class="memory-references" data-key="${esc(id)}" ${open.has(id)?'open':''}><summary>${tr('参考记忆')} · ${items.length}</summary>${items.map(i=>memoryItemHTML(i,{historical:true})).join('')}</details>`;
}
export function memoryReceiptHTML(part){
  const r=part.memory_receipt;
  if(!r)return `<div class="memory-receipt" role="status">${tr(part.memory_failed||part.state?.status==='error'?'记忆未保存':'记忆结果尚未确认')} · <a href="/labs">${tr('管理记忆')}</a></div>`;
  if(!r.saved)return `<div class="memory-receipt" role="status">${tr('记忆未保存')} · ${esc(tr(r.error||'记忆结果尚未确认'))}</div>`;
  return `<aside class="memory-receipt"><strong>${tr(({create:'已记住',update:'已更新记忆',delete:'已删除记忆'})[r.action])}</strong>${memoryItemHTML(r.action==='delete'?{...r.item,current_revision:null}:r.item,{historical:true})}</aside>`;
}

export function announceMemoryChange(){
  document.dispatchEvent(new Event('memory-changed'));
  try{localStorage.setItem('memory-change',String(Date.now()));}catch{}
}

let activeEditor=null;
export function editMemory(item=null,{dirty=()=>{}}={}){
  if(activeEditor){activeEditor.focus();return;}
  const dialog=document.createElement('dialog');activeEditor=dialog;dialog.className='memory-dialog';
  dialog.innerHTML=`<form class="settings-form"><h3>${tr(item?'编辑记忆':'添加记忆')}</h3><label>${tr('记忆内容')}<textarea name="content" rows="5" maxlength="500" required>${esc(item?.content||'')}</textarea></label><p class="settings-note">${tr('只记录长期工作偏好，合同事实请留在项目中。')}</p><p role="alert" class="memory-error"></p><div class="settings-form-actions"><button class="primary" type="submit">${tr('保存')}</button><button type="button" data-reload hidden>${tr('重新载入')}</button><button type="button" data-cancel>${tr('取消')}</button></div></form>`;
  let changed=false,busy=false;
  const form=dialog.querySelector('form'),text=form.elements.content,error=dialog.querySelector('[role=alert]'),reload=dialog.querySelector('[data-reload]');
  const changedTo=value=>{changed=value;dirty(value);};
  const cleanup=()=>{changedTo(false);activeEditor=null;dialog.remove();window.removeEventListener('beforeunload',unload);document.removeEventListener('session-expired',expired);};
  const close=()=>{if(busy)return;if(changed&&!confirm(tr('有尚未保存的修改，确定离开？')))return;dialog.close();cleanup();};
  const unload=e=>{if(changed){e.preventDefault();e.returnValue='';}};
  const expired=()=>{dialog.close();cleanup();};
  window.addEventListener('beforeunload',unload);document.addEventListener('session-expired',expired,{once:true});
  text.oninput=()=>changedTo(true);
  dialog.oncancel=e=>{e.preventDefault();close();};dialog.querySelector('[data-cancel]').onclick=close;
  reload.onclick=async()=>{
    if(changed&&!confirm(tr('重新载入会替换尚未保存的输入，确定继续？')))return;
    try{const data=await api('/api/memories'),latest=data.items.find(i=>i.id===item.id);if(!latest)throw new Error(tr('记忆已删除或不存在'));item=latest;text.value=item.content;changedTo(false);error.textContent='';reload.hidden=true;}catch(e){error.textContent=e.message;}
  };
  form.onsubmit=async e=>{
    e.preventDefault();if(busy)return;busy=true;form.querySelector('[type=submit]').disabled=true;error.textContent='';
    try{
      await api('/api/memories'+(item?'/'+item.id:''),{method:item?'PATCH':'POST',body:{content:text.value,...(item?{revision:item.revision}:{})}});
      dialog.close();cleanup();announceMemoryChange();
    }catch(e){error.textContent=e.message;reload.hidden=!(item&&e.status===409);}
    finally{busy=false;if(dialog.isConnected)form.querySelector('[type=submit]').disabled=false;}
  };
  document.body.append(dialog);dialog.showModal();text.focus();
}

export async function handleMemoryAction(event,{notice=()=>{},dirty=()=>{}}={}){
  const b=event.target.closest('[data-memory-edit],[data-memory-delete]');if(!b)return false;
  event.preventDefault();
  try{
    const {items}=await api('/api/memories'),item=items.find(i=>i.id===(b.dataset.memoryEdit||b.dataset.memoryDelete));
    if(!item)throw new Error(tr('记忆已删除或不存在'));
    if(b.dataset.memoryEdit)editMemory(item,{dirty});
    else if(confirm(tr('删除这条记忆？旧对话仍保留历史内容。'))){await api(`/api/memories/${item.id}?revision=${item.revision}`,{method:'DELETE'});announceMemoryChange();}
  }catch(e){notice(e.message);}
  return true;
}

export async function renderLabs(root,{notice,dirty,isCurrent=()=>true}){
  const [status,data]=await Promise.all([api('/api/settings/labs'),api('/api/memories')]);if(!isCurrent())return;
  root.innerHTML=`<div class="settings-heading"><div><h2>Labs</h2><p>${tr('尝试工作台的实验功能。')}</p></div></div><section class="memory-labs"><header><div><h3>${tr('个人记忆')}</h3><p>${tr('记住你的工作偏好，供后续对话使用。')}</p></div><label class="settings-check"><input type="checkbox" data-memory-toggle ${status.memory_enabled?'checked':''} ${!status.available?'disabled':''}>${tr('开启')}</label></header><p class="settings-note" role="status">${tr(!status.available?'当前账号暂不可开启个人记忆':status.effective?'已开启：助手可以主动保存长期偏好。':'已暂停使用和自动保存，已有记忆保留。')}</p>${status.requires_login?`<a href="/login">${tr('登录正式账号')}</a>`:''}<p class="settings-note">${tr('关闭或删除不移除旧聊天，正在生成的答复可能已使用记忆。')}</p><div class="memory-toolbar"><input type="search" data-memory-search placeholder="${tr('搜索记忆')}" aria-label="${tr('搜索记忆')}"><button type="button" data-memory-add>${tr('添加记忆')}</button></div><p class="settings-note">${data.used.toLocaleString()} / ${data.limit.toLocaleString()} ${tr('字符')}</p><div data-memory-list></div></section>`;
  const list=root.querySelector('[data-memory-list]'),search=root.querySelector('[data-memory-search]');
  const render=()=>{const q=search.value.toLowerCase();list.innerHTML=data.items.filter(i=>i.content.toLowerCase().includes(q)).map(i=>memoryItemHTML(i)).join('')||`<p class="settings-empty">${tr('暂无匹配记忆。可手动添加，或开启后在对话中说“记住……”。')}</p>`;};
  search.oninput=render;render();root.querySelector('[data-memory-add]').onclick=()=>editMemory(null,{dirty});
  list.onclick=e=>handleMemoryAction(e,{notice,dirty});
  root.querySelector('[data-memory-toggle]').onchange=async e=>{
    e.target.disabled=true;
    try{await api('/api/settings/labs',{method:'PATCH',body:{memory_enabled:e.target.checked,revision:status.revision}});announceMemoryChange();}
    catch(error){e.target.checked=status.memory_enabled;notice(error.message);}
    finally{e.target.disabled=!status.available;}
  };
}
