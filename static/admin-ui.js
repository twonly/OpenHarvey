import {api} from './api.js';
import {esc} from './markdown.js';
import {addDiscoveredModel,waitForOperation} from './provider-utils.js';
const stateLabel=r=>!r?'尚未开通':r.status==='disabled'?'已停用':r.status==='failed'?'开通失败':r.status==='provisioning'?'开通中':r.error?'生效失败':r.desired_revision!==r.applied_revision?'待生效':'可用';
const time=v=>v?new Date(v*1000).toLocaleString():'';
export async function renderAdmin(host,{mode,identity,notice,dirty,leave}){
 const $=s=>host.querySelector(s),run=fn=>async(...args)=>{try{await fn(...args);}catch(e){notice(e.message);}};
 const input=(label,name,value='',extra='')=>`<label>${label}<input name="${name}" value="${esc(value??'')}" ${extra}></label>`;
 const admin=mode==='providers'||identity.role==='admin';let items=[],selected=null,currentModels=[],pending=false,catalog=[];
 function managementButtons(){
  for(const button of host.querySelectorAll('[data-save-provider],[data-save-member],[data-apply-models],[data-retry-member]')){
   button.dataset.idleLabel ||= button.textContent;button.disabled=pending;
   button.textContent=pending?(mode==='providers'?'正在验证并应用…':'正在处理…'):button.dataset.idleLabel;
  }
 }
 async function operation(value){
  if(!value.operation_id)return;const id=value.operation_id;pending=true;managementButtons();
  const slot=$('#adminOperation');slot.innerHTML='<span>正在处理… 可以继续使用工作台。</span>';
  try{
   const result=await waitForOperation(id,{read:id=>api('/api/operations/'+id),active:()=>host.isConnected});
   if(result&&host.isConnected){
    pending=false;slot.innerHTML=`<span class="${result.status==='failed'?'trace-error-label':''}">${result.status==='completed'?esc(result.result.message||(result.result.users?.some(u=>!u.applied)?'已保存，将在当前任务结束后生效。':'操作已完成')):esc(result.result.message||'操作失败')}</span><small>${time(result.updated)}</small>`;
    await loadList();if(mode==='members'&&selected){const item=items.find(m=>m.id===selected.id);const tag=$('#memberForm .settings-tag');if(item&&tag)tag.textContent=item.active?stateLabel(item.runtime):'已停用';}return result;
   }
  }catch(e){if(slot.isConnected)resultText(slot,e.message,true);throw e;}finally{pending=false;managementButtons();}
 }
 function frame(title,caption,action){
  host.innerHTML=`<div class="settings-heading"><div><h2>${title}</h2><p>${caption}</p></div>${action||''}</div><div id="adminOperation" class="admin-operation" role="status"></div><div class="settings-split"><div class="settings-list-panel"><input id="adminSearch" type="search" placeholder="搜索${mode==='members'?'成员':'供应商'}" aria-label="搜索${mode==='members'?'成员':'供应商'}"><div id="adminList"></div></div><div id="adminEditor"><p class="settings-empty">选择一项查看${admin?'或编辑':''}。</p></div></div>${mode==='providers'&&admin?'<div id="modelApplyNotice" class="admin-operation" role="status" hidden></div>':''}`;
  $('#adminSearch').oninput=list;
 }
 async function loadList(){
  if(mode==='members'){items=await api('/api/admin/members');list();}
  else{
   const data=await api('/api/providers');items=data.providers;list();
   const slot=$('#modelApplyNotice');
   if(slot){
    const waiting=[{username:'我的运行环境',runtime:data.runtime}].filter(m=>m.runtime&&m.runtime.status!=='disabled'&&(m.runtime.error||m.runtime.desired_revision!==m.runtime.applied_revision));
    slot.hidden=!waiting.length;
    slot.innerHTML=waiting.map(m=>`<p><b>${esc(m.username)}</b> · ${m.runtime.error?`<span class="trace-error-label">配置未生效：${esc(m.runtime.error)}</span>`:'新配置将在当前任务结束后生效。'}</p>`).join('')+(waiting.length?'<button data-apply-models>重新验证并应用</button>':'');
   }
  }
 }
 function list(){
  const q=$('#adminSearch').value.toLowerCase();
  $('#adminList').innerHTML=items.filter(x=>(mode==='members'?x.username:x.label+' '+x.id).toLowerCase().includes(q)).map(x=>`<button data-admin-item="${esc(x.id)}" class="settings-list-item ${selected?.id===x.id?'active':''}"><b>${esc(mode==='members'?x.username:x.label)}</b><span>${mode==='members'?(x.role==='admin'?'管理员':'成员')+' · '+(x.active?stateLabel(x.runtime):'已停用'):(x.enabled?'启用':'已停用')+' · '+x.models.length+' 个模型'}</span>${mode==='members'&&x.runtime?.error?`<p>${esc(x.runtime.error)}</p>`:''}</button>`).join('')||'<p class="settings-empty">暂无匹配记录。</p>';
 }
 function memberEditor(item){
  selected=item;list();
  $('#adminEditor').innerHTML=`<form id="memberForm" class="settings-form"><div class="settings-editor-head"><h3>${item?'成员设置':'创建成员'}</h3>${item?`<span class="settings-tag">${item.active?stateLabel(item.runtime):'已停用'}</span>`:''}</div>${input('账号','username',item?.username,'required pattern="[a-z][a-z0-9_-]{1,31}" maxlength="32" '+(item?'readonly':'autocomplete="off" placeholder="例如 chen-li"'))}<label>角色<select name="role"><option value="member" ${item?.role!=='admin'?'selected':''}>普通成员</option><option value="admin" ${item?.role==='admin'?'selected':''}>管理员</option></select></label>${item?`<label class="settings-check"><input type="checkbox" name="active" ${item.active?'checked':''}>账号启用</label><p class="settings-note">停用将撤销登录并停止运行环境，合同、历史和产出物仍保留。</p>`:`${input('初始密码','password','Contract1','minlength="8" maxlength="200" autocomplete="new-password" type="password"')}<p class="settings-note">创建后自动准备独立运行环境。状态变为“可用”后即可登录使用。</p>`}<div class="settings-form-actions"><button type="submit" class="primary">${item?'保存成员设置':'创建并开通'}</button>${item?.active?'<button type="button" data-retry-member>重新开通 / 恢复运行</button>':''}</div>${item?`<details><summary>重置密码</summary>${input('新的登录密码','reset_password','Contract1','type="password" minlength="8" autocomplete="new-password"')}<button type="button" data-reset-password>重置密码并撤销登录</button></details>`:''}</form>`;
  $('#memberForm button[type=submit]').setAttribute('data-save-member','');managementButtons();
  $('#memberForm').onsubmit=run(async e=>{e.preventDefault();if(pending)return;pending=true;managementButtons();try{const d=Object.fromEntries(new FormData(e.target));const result=await api('/api/admin/members'+(item?'/'+item.id:''),{method:item?'PUT':'POST',body:{username:d.username,password:d.password,role:d.role,active:d.active==='on',revision:item?.revision}});dirty(false);await loadList();memberEditor(result.member);if(result.existing)notice('该账号已经存在，未重复创建。');else await operation(result);}finally{pending=false;managementButtons();}});
 }
 function providerEditor(item){
  if(item?.id==='trial'){selected=item;list();$('#adminEditor').innerHTML='<h3>平台试用模型</h3><p>由平台提供，只能在已计入额度的任务中调用。额度用完后，可以添加自己的模型服务。</p><span class="settings-tag">公开只读配置</span>';return;}

  selected=item;catalog=[];currentModels=structuredClone(item?.models||[{id:'',label:'',context:128000,output:8192,enabled:true}]);list();
  $('#adminEditor').innerHTML=`<form id="providerForm" class="settings-form"><div class="settings-editor-head"><h3>${item?'模型接入':'添加供应商'}</h3>${item&&admin?`<span class="settings-tag">v${item.revision}</span>`:''}</div>${admin?`<fieldset>${!item?'<label>接入预设<select id="providerPreset"><option value="compatible">OpenAI 兼容</option><option value="deepseek">DeepSeek</option><option value="glm">智谱 GLM</option></select></label>':''}${input('供应商名称','label',item?.label,'required maxlength="100"')}${input('服务地址','base_url',item?.base_url,'required type="url" placeholder="https://api.example.com/v1"')}<label>API 密钥<input name="key" type="password" autocomplete="new-password" placeholder="${item?.key_configured?'已配置，留空保留现有密钥':'填写 API Key'}" maxlength="10000"></label>${item?.key_configured?'<label class="settings-check"><input name="clear_key" type="checkbox">清除密钥并停用此供应商</label>':''}<details><summary>高级选项</summary>${input('供应商标识','id',item?.id||'provider-'+Math.random().toString(16).slice(2,8),'required pattern="[a-z0-9]+(-[a-z0-9]+)*" maxlength="48" '+(item?'readonly':'placeholder="例如 company-models"'))}<label class="settings-check"><input name="enabled" type="checkbox" ${!item||item.enabled?'checked':''}>启用此供应商</label></details></fieldset>`:`<p>${esc(item?.label)}</p>`}<div class="settings-reference-head"><b>模型</b>${admin?'<div class="provider-model-actions"><button type="button" data-fetch-models>获取模型列表</button><button type="button" data-add-model>＋ 手动添加</button></div>':''}</div><div id="modelCatalogStatus" class="provider-result" role="status"></div><div id="modelCatalog" hidden></div><div id="providerModels"></div>${admin?'<div class="settings-form-actions"><button type="submit" class="primary" data-save-provider>保存并应用</button></div><p class="settings-note">连接测试会在没有合同材料的临时环境中进行一次真实调用。运行中的任务结束后，新配置才会生效。</p>':''}</form>`;
  modelForms();managementButtons();
  if($('#providerPreset'))$('#providerPreset').onchange=e=>{const f=$('#providerForm'),v=e.target.value;const values=v==='deepseek'?{id:'deepseek',label:'DeepSeek',url:'https://api.deepseek.com/v1',model:'deepseek-chat'}:v==='glm'?{id:'glm',label:'智谱 GLM',url:'https://open.bigmodel.cn/api/paas/v4',model:'glm-5.3'}:{id:'provider-'+Math.random().toString(16).slice(2,8),label:'',url:'',model:''};f.elements.id.value=values.id;f.elements.label.value=values.label;f.elements.base_url.value=values.url;currentModels=[{id:values.model,label:values.model,context:128000,output:8192,enabled:true}];modelForms();dirty(true);};
  $('#providerForm').onsubmit=run(async e=>{
   e.preventDefault();if(pending)return;pending=true;managementButtons();
   const form=e.target,data=providerBody(),before=JSON.stringify(data);
   try{
    const result=await api('/api/providers',{method:'POST',body:data});
    if(form.isConnected){
     const unchanged=JSON.stringify(providerBody())===before;
     selected=result.provider;
     const tag=form.querySelector('.settings-editor-head .settings-tag');if(tag)tag.textContent='v'+selected.revision;
     if(form.elements.key.value===data.key)form.elements.key.value='';
     form.elements.key.placeholder=selected.key_configured?'已配置，留空保留现有密钥':'填写 API Key';
     form.elements.id.readOnly=true;
     if(unchanged)dirty(false);
    }
    await loadList();await operation(result);
   }finally{pending=false;managementButtons();}
  });
 }
 function modelForms(){
  $('#providerModels').innerHTML=currentModels.map((m,i)=>`<fieldset class="provider-model" data-model-index="${i}" ${!admin?'disabled':''}><div class="settings-fields">${input('模型 ID','model_id',m.id,'required maxlength="180"')}${input('显示名称','model_label',m.label,'required maxlength="100"')}</div><details class="provider-model-limits"><summary>高级参数</summary><div class="settings-fields">${input('上下文上限','model_context',m.context,'type="number" required min="1" max="10000000"')}${input('输出上限','model_output',m.output,'type="number" required min="1" max="10000000"')}</div></details><div class="provider-model-footer"><label class="settings-check"><input type="checkbox" name="model_enabled" ${m.enabled?'checked':''}>启用模型</label>${admin?`<div class="provider-model-actions"><button type="button" data-test-model="${i}">测试连接</button><button type="button" data-remove-model="${i}">移除</button></div>`:''}</div><div data-test-result class="provider-result" role="status"></div></fieldset>`).join('');
 }
 function connectionBody(){
  const d=Object.fromEntries(new FormData($('#providerForm')));
  return {id:d.id,label:d.label||d.id,base_url:d.base_url,key:d.key||undefined,clear_key:d.clear_key==='on'};
 }
 function resultText(slot,text,error=false){slot.textContent=text;slot.classList.toggle('is-error',error);}
 function renderCatalog(){
  const root=$('#modelCatalog');root.hidden=false;
  root.innerHTML=`<div class="provider-catalog-head">${catalog.length} 个模型，点击添加到配置</div><input type="search" id="modelFilter" aria-label="筛选模型列表" placeholder="搜索模型 ID"><div class="provider-catalog-items"></div><p class="settings-note">列表来自当前服务；加入后仍需保存并应用。模型上限可在高级参数中调整。</p>`;
  catalogList();$('#modelFilter').oninput=catalogList;
 }
 function catalogList(){
  const q=$('#modelFilter').value.trim().toLowerCase(),ids=new Set(currentModels.map(m=>m.id));
  $('#modelCatalog .provider-catalog-items').innerHTML=catalog.filter(id=>id.toLowerCase().includes(q)).map(id=>`<button type="button" data-catalog-model="${esc(id)}" ${ids.has(id)?'disabled':''}>${esc(id)}${ids.has(id)?'<small>已添加</small>':''}</button>`).join('')||'<p class="settings-empty">暂无匹配模型。</p>';
 }
 async function fetchModels(button){
  if(button.disabled)return;
  const form=$('#providerForm');if(!form.elements.base_url.reportValidity())return;
  const body=connectionBody(),stamp=JSON.stringify(body),slot=$('#modelCatalogStatus');
  button.disabled=true;button.textContent='获取中…';resultText(slot,'正在获取模型列表…');$('#modelCatalog').hidden=true;
  try{
   const data=await api('/api/providers/models',{method:'POST',body});
   if(!form.isConnected)return;
   if(JSON.stringify(connectionBody())!==stamp){resultText(slot,'接入配置已修改，请重新获取模型列表。');return;}
   catalog=data.models;resultText(slot,'');collectModels();renderCatalog();
  }catch(e){if(form.isConnected)resultText(slot,e.message,true);}
  finally{button.disabled=false;button.textContent='获取模型列表';}
 }
 async function testModel(button){
  if(button.disabled)return;
  const form=$('#providerForm'),row=button.closest('[data-model-index]');
  if(!form.elements.base_url.reportValidity()||!row.querySelector('[name=model_id]').reportValidity())return;
  collectModels();const model=currentModels[Number(button.dataset.testModel)],slot=row.querySelector('[data-test-result]');
  const body={...connectionBody(),enabled:true,models:[{...model,label:model.label||model.id,enabled:true}]};
  const revision=form.dataset.editRevision||'0';button.disabled=true;button.textContent='测试中…';resultText(slot,'正在测试当前模型…');
  try{
   const value=await api('/api/providers/test',{method:'POST',body});
   const result=await waitForOperation(value.operation_id,{read:id=>api('/api/operations/'+id),active:()=>row.isConnected});
   if(!result||!row.isConnected)return;
   if((form.dataset.editRevision||'0')!==revision){resultText(slot,'配置已修改，请重新测试。');return;}
   if(result.status==='failed'){resultText(slot,result.result.message||'连接测试失败',true);return;}
   const ms=result.result.models?.[0]?.latency_ms;
   resultText(slot,'连接成功'+(ms!=null?' · '+(ms/1000).toFixed(2)+' 秒':'')+' · '+model.id);
  }catch(e){if(row.isConnected)resultText(slot,e.message,true);}
  finally{button.disabled=false;button.textContent='测试连接';}
 }
 function collectModels(){
  currentModels=[...host.querySelectorAll('[data-model-index]')].map(f=>{const get=n=>f.querySelector(`[name="${n}"]`);return {...currentModels[Number(f.dataset.modelIndex)],id:get('model_id').value,label:get('model_label').value,context:Number(get('model_context').value),output:Number(get('model_output').value),enabled:get('model_enabled').checked};});
 }
 function providerBody(){collectModels();const d=Object.fromEntries(new FormData($('#providerForm')));return {id:d.id,label:d.label,base_url:d.base_url,key:d.key||undefined,clear_key:d.clear_key==='on',enabled:d.enabled==='on',revision:selected?.revision||0,models:currentModels};}
 frame(mode==='members'?'成员管理':'模型与服务',mode==='members'?'管理账号、角色与独立运行环境。':'配置自己的模型服务、API 密钥和可用模型，仅对本人账号生效。',admin?`<button class="primary" data-admin-new>${mode==='members'?'创建成员':'添加供应商'}</button>`:'');
 const edited=e=>{
  if(['adminSearch','modelFilter'].includes(e.target.id))return;
  dirty(true);const form=$('#providerForm');if(form){form.dataset.editRevision=String(Number(form.dataset.editRevision||0)+1);for(const slot of form.querySelectorAll('[data-test-result]'))slot.textContent='';}
  if(['base_url','key','clear_key','id'].includes(e.target.name)&&$('#modelCatalog')){$('#modelCatalog').hidden=true;resultText($('#modelCatalogStatus'),'');}
 };
 host.addEventListener('input',edited);host.addEventListener('change',edited);
 host.addEventListener('click',run(async e=>{const b=e.target.closest('button');if(!b)return;
  if(b.dataset.adminItem&&leave()){dirty(false);(mode==='members'?memberEditor:providerEditor)(items.find(x=>x.id===b.dataset.adminItem));}
  if(b.hasAttribute('data-admin-new')&&leave()){dirty(false);(mode==='members'?memberEditor:providerEditor)(null);}
  if(b.hasAttribute('data-retry-member'))await operation(await api(`/api/admin/members/${selected.id}/retry`,{method:'POST',body:{}}));
  if(b.hasAttribute('data-reset-password')){if(!confirm(`重置 ${selected.username} 的密码并撤销其现有登录？`))return;await api(`/api/admin/members/${selected.id}/password`,{method:'POST',body:{password:$('#memberForm').elements.reset_password.value}});dirty(false);notice('密码已重置，现有登录已撤销。');}
  if(b.hasAttribute('data-add-model')){collectModels();if(currentModels.length>=40)throw Error('每个供应商最多配置 40 个模型');currentModels.push({id:'',label:'',context:128000,output:8192,enabled:true});modelForms();dirty(true);}
  if(b.dataset.removeModel!==undefined){collectModels();currentModels.splice(Number(b.dataset.removeModel),1);modelForms();if($('#modelFilter'))catalogList();dirty(true);}
  if(b.hasAttribute('data-fetch-models'))await fetchModels(b);
  if(b.dataset.catalogModel){collectModels();if(currentModels.length>=40&&!currentModels.some(m=>!m.id.trim()))throw Error('每个供应商最多配置 40 个模型');currentModels=addDiscoveredModel(currentModels,b.dataset.catalogModel);modelForms();catalogList();dirty(true);}
  if(b.dataset.testModel!==undefined)await testModel(b);
  if(b.hasAttribute('data-apply-models')&&!pending){pending=true;managementButtons();try{await operation(await api('/api/providers/apply',{method:'POST',body:{}}));}finally{pending=false;managementButtons();}}
 }));
 await loadList();
}
