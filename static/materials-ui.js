import {api,upload} from './api.js';
import {esc,citations} from './markdown.js';
import {t as tr} from './i18n.js';
import {loadingHTML} from './loading-ui.js';

export const activeDocuments=documents=>documents.filter(d=>!d.removed_at&&!d.historical_only);

export function sourceReferencesHTML(text,documents){
  const refs=new Map();
  for(const match of String(text||'').matchAll(/【D([a-f0-9]{12}):B(\d+)(?:-B(\d+))?】/g)){
    const doc=documents.find(d=>d.id===match[1]);
    if(doc?.locations?.['B'+match[2]]&&doc.locations['B'+(match[3]||match[2])]){
      if(!refs.has(doc.id))refs.set(doc.id,match[0]);
    }
  }
  if(!refs.size)return '';
  return `<details class="material-references"><summary>${tr('引用来源')} · ${refs.size}</summary>${[...refs].map(([id,ref])=>{
    const doc=documents.find(d=>d.id===id);
    return `<div>${esc(doc.filename)}${doc.removed_at?' · '+tr('已移除'):''} ${citations(ref,documents)}</div>`;
  }).join('')}</details>`;
}

export function setupMaterials({context,notice,refresh,openSource,onBusy}){
  const dialog=document.createElement('dialog');dialog.className='materials-dialog';dialog.setAttribute('aria-labelledby','materialsTitle');
  dialog.innerHTML=`<header><div><h2 id="materialsTitle">${tr('合同资料')}</h2><p>${tr('本合同空间内所有对话可用；助手按问题查找相关资料。')}</p></div><button type="button" data-close aria-label="${tr('关闭')}">×</button></header>
    <div class="materials-toolbar"><input type="search" data-search placeholder="${tr('搜索文件名')}" aria-label="${tr('搜索文件名')}"><select data-type aria-label="${tr('文件格式')}"><option value="">${tr('全部格式')}</option>${['docx','pdf','md','txt'].map(s=>`<option value=".${s}">${s.toUpperCase()}</option>`).join('')}</select><select data-scope aria-label="${tr('资料范围')}"><option value="active">${tr('当前资料')}</option><option value="removed">${tr('已移除')}</option></select><button type="button" data-add>${tr('添加资料')}</button></div>
    <input type="file" data-files accept=".docx,.pdf,.md,.txt" multiple hidden>
    <div class="materials-drop" data-drop>${tr('可拖入多份文件，支持 Word、文字版 PDF、Markdown 和 TXT。')}</div>
    <p class="materials-status" data-status role="status"></p><div data-jobs aria-live="polite"></div><div class="materials-table" data-table></div>`;
  document.body.append(dialog);
  const $=s=>dialog.querySelector(s),jobs=new Map();
  let wid=null,rows=[],busy=false,generation=0,lastRemoved=null,session=0,errorMessage='',loading=false;
  const writable=()=>context().enabled&&context().wid===wid&&!!context().tid&&!context().readOnly&&!context().busy&&!busy;
  function setBusy(value){busy=value;onBusy();render();}
  function render(){
    const q=$('[data-search]').value.trim().toLowerCase(),suffix=$('[data-type]').value,removed=$('[data-scope]').value==='removed';
    const visible=rows.filter(d=>!!d.removed_at===removed&&(!suffix||d.suffix===suffix)&&d.filename.toLowerCase().includes(q));
    $('[data-add]').disabled=!writable();
    $('[data-status]').replaceChildren();
    if(errorMessage)$('[data-status]').textContent=errorMessage;
    else if(lastRemoved){
      $('[data-status]').textContent=tr('已移出资料区，历史引用保留。')+' ';
      const undo=document.createElement('button');undo.textContent=tr('撤销');undo.disabled=!writable();undo.onclick=()=>void change(lastRemoved,'restore');$('[data-status]').append(undo);
    }else if(context().busy)$('[data-status]').textContent=tr('空间内任务结束后可修改资料。');
    $('[data-table]').innerHTML=visible.length?`<table><thead><tr><th>${tr('名称')}</th><th>${tr('格式')}</th><th>${tr('操作')}</th></tr></thead><tbody>${visible.map(d=>`<tr><td><button type="button" data-open="${esc(d.id)}">${esc(d.filename)}</button><small>${tr(d.primary?'主合同':d.removed_at?'已移除':'可用')}</small></td><td>${esc(d.suffix.slice(1).toUpperCase())}</td><td>${!d.primary?`<button type="button" data-action="${d.removed_at?'restore':'remove'}" data-id="${esc(d.id)}" ${writable()?'':'disabled'}>${tr(d.removed_at?'恢复':'移除')}</button>`:''}</td></tr>`).join('')}</tbody></table>`:`<p class="materials-empty">${tr(removed?'没有已移除资料':'没有匹配的资料')}</p>`;
    $('[data-jobs]').innerHTML=(jobs.get(wid)||[]).map((job,index)=>`<div class="material-upload"><span>${esc(job.name)}</span><span>${esc(tr(job.status))}${job.error?`：${esc(job.error)}`:''}</span>${job.status==='失败'?`<button type="button" data-retry="${index}" ${writable()?'':'disabled'}>${tr('重试')}</button>`:''}</div>`).join('');
    if(loading&&!rows.length)$('[data-table]').innerHTML=loadingHTML(tr('正在读取资料…'));
  }
  async function reload(){
    const target=wid,version=++generation;
    loading=true;render();
    try{
      const data=await api(`/api/workspaces/${target}/documents`);
      if(version!==generation||wid!==target)return;
      rows=data.documents;
    }finally{if(version===generation&&wid===target){loading=false;render();}}
  }
  async function open(){
    const c=context();if(!c.enabled||!c.wid)return;
    if(wid!==c.wid){wid=c.wid;rows=[];lastRemoved=null;errorMessage='';}
    if(!dialog.open)dialog.showModal();
    render();
    try{await reload();}catch(e){$('[data-status]').textContent=e.message;}
  }
  async function change(id,action){
    if(!writable())return;
    const target=wid,account=session;errorMessage='';setBusy(true);
    try{
      await api(`/api/workspaces/${target}/documents/${id}`,{method:'PATCH',body:{action}});
      if(account!==session)return;
      lastRemoved=action==='remove'?id:null;
      if(context().wid===target)await refresh(action==='remove'?id:null);
      await reload();
    }catch(e){errorMessage=e.message;notice(e.message,'error');}
    finally{if(account===session)setBusy(false);}
  }
  async function run(items){
    if(!writable())return;
    const target=wid,thread=context().tid,account=session;errorMessage='';setBusy(true);
    try{
      // ponytail: sequential uploads suit contract-sized batches; add bounded
      // concurrency only when measured upload latency calls for it.
      for(const job of items){
        if(account!==session)break;
        job.status='处理中';job.error='';render();
        try{
          const result=await upload(`/api/workspaces/${target}/attachments?thread_id=${thread}`,job.file);
          job.status=result.reused?'已存在':'可用';job.file=null;
        }catch(e){job.status='失败';job.error=e.message;}
        if(account!==session)return;
        render();
      }
      if(context().wid===target)await refresh();
      if(wid===target)await reload();
    }catch(e){errorMessage=e.message;notice(e.message,'error');}
    finally{if(account===session)setBusy(false);}
  }
  async function add(files){
    if(busy||!files.length)return;
    await open();if(!writable())return;
    const items=Array.from(files,file=>({file,name:file.name,status:'待上传',error:''}));
    jobs.set(wid,[...(jobs.get(wid)||[]),...items]);await run(items);
  }
  for(const selector of ['[data-search]','[data-type]','[data-scope]'])$(selector).addEventListener('input',render);
  $('[data-close]').onclick=()=>dialog.close();
  $('[data-add]').onclick=()=>$('[data-files]').click();
  $('[data-files]').onchange=e=>{const files=Array.from(e.target.files);e.target.value='';void add(files);};
  dialog.onclick=async e=>{
    const button=e.target.closest('button');if(!button||button.disabled)return;
    if(button.dataset.open){dialog.close();try{await openSource(button.dataset.open);}catch(error){notice(error.message,'error');}}
    if(button.dataset.action)await change(button.dataset.id,button.dataset.action);
    if(button.dataset.retry!=null)await run([jobs.get(wid)[Number(button.dataset.retry)]]);
  };
  dialog.ondragover=e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();$('[data-drop]').classList.add('dragging');}};
  dialog.ondragleave=()=>$('[data-drop]').classList.remove('dragging');
  dialog.ondrop=e=>{e.preventDefault();$('[data-drop]').classList.remove('dragging');void add(Array.from(e.dataTransfer.files));};
  return {open,add,get busy(){return busy;},close(){dialog.close();generation++;},reset(){dialog.close();generation++;session++;jobs.clear();rows=[];wid=null;busy=false;}};
}
