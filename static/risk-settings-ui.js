import {api} from './api.js';
import {esc} from './markdown.js';

const scopeLabels={public:'公开示例',personal:'我的'};
export async function renderRiskSettings(host,{identity,notice,dirty,leave}){
  let items=await api('/api/risk-schemes'),selection=await api('/api/risk-schemes/options'),current=null,draft=null,index=null;
  let versionRequest=0,saving=false,deleting=false;const checked=new Set(),modified=new Set();
  const $=s=>host.querySelector(s),run=fn=>async(...args)=>{try{await fn(...args);}catch(e){notice(e.message);}};
  host.innerHTML=`<div class="settings-heading"><div><h2>风险库</h2><p>每次审查使用一套方案；个人副本独立维护，历史报告保留原依据。</p></div><div class="scheme-actions"><button data-inherit-risk>使用默认</button>${identity.role==='admin'?'<select id="newSchemeScope" aria-label="新方案归属"><option value="personal">我的方案</option><option value="public">公开示例方案</option></select>':''}<button data-new-scheme class="primary">新建方案</button></div></div><div class="settings-split risk-settings-split"><div class="settings-list-panel"><input id="schemeSearch" type="search" aria-label="搜索审查方案" placeholder="搜索审查方案"><div id="schemeList"></div><label class="settings-file-add">↑ 导入 JSON 方案<input id="schemeImport" type="file" accept=".json" hidden></label></div><div id="schemeEditor"><p class="settings-empty">选择方案查看风险点，或复制公开示例方案进行调整。</p></div></div>`;
  function list(){
    const q=$('#schemeSearch').value.trim().toLowerCase();
    $('#schemeList').innerHTML=items.filter(s=>s.content.label.toLowerCase().includes(q)).map(s=>`<button data-scheme="${s.id}" class="settings-list-item ${current?.id===s.id?'active':''}"><b>${esc(s.content.label)}</b><span>${scopeLabels[s.scope]} · v${s.revision}${!s.enabled?' · 已停用':''}</span><p>${s.content.rules.filter(r=>r.enabled!==false).length} / ${s.content.rules.length} 项启用${selection.default===s.id?' · 默认':''}${selection.selected===s.id?' · 我的默认':''}</p></button>`).join('')||'<p class="settings-empty">没有匹配的方案。</p>';
  }
  const input=(label,key,value='',extra='')=>`<label>${label}<input data-rule-field="${key}" value="${esc(value??'')}" ${extra}></label>`;
  const area=(label,key,value='',rows=3)=>`<label>${label}<textarea data-rule-field="${key}" rows="${rows}">${esc(Array.isArray(value)?value.join('\n'):value??'')}</textarea></label>`;
  function editor(item,{openId=null,q='',category=''}={}){
    versionRequest++;current=item;draft=structuredClone(item.content);index=openId?draft.rules.findIndex(r=>r.id===openId):null;if(index===-1)index=null;checked.clear();modified.clear();
    const readonly=!item.editable;
    $('#schemeEditor').innerHTML=`<div class="settings-form"><div class="settings-editor-head"><h3>${esc(draft.label)}</h3><span class="settings-tag">${scopeLabels[item.scope]} · v${item.revision}</span></div><div class="scheme-actions"><button data-use-scheme ${!item.enabled?'disabled':''}>${selection.selected===item.id?'我的默认方案':'设为我的默认'}</button><button data-copy-scheme>复制为个人方案</button><a href="/api/risk-schemes/${item.id}/export" download>导出</a>${identity.role==='admin'&&item.scope==='public'?'<button data-default-scheme>设为默认</button>':''}${!readonly?`<button data-delete-scheme class="settings-danger" ${selection.default===item.id?'disabled title="请先将其他方案设为默认"':''}>删除方案</button>`:''}</div>${!readonly&&selection.default===item.id?'<p class="settings-note">删除此方案前，请先将其他方案设为默认。</p>':''}<form id="schemeForm"><fieldset ${readonly?'disabled':''}><label>方案名称<input name="label" value="${esc(draft.label)}" required maxlength="100"></label><label>方案说明<textarea name="description" rows="2">${esc(draft.description||'')}</textarea></label><label class="settings-check"><input name="enabled" type="checkbox" ${item.enabled?'checked':''}>启用此方案</label></fieldset>${readonly?'<p class="settings-note">公开示例方案由管理员维护，你可以复制后调整。</p>':''}</form><div class="risk-rules-controls"><div class="risk-rules-toolbar"><input id="riskRuleSearch" type="search" placeholder="搜索名称、基线或风险编号" aria-label="搜索风险点"><select id="riskRuleCategory" aria-label="按分类筛选"><option value="">全部分类</option></select></div><div class="risk-editing-bar"><span id="riskEditingStatus" role="status"></span><div class="risk-editor-actions"><button type="button" data-collapse-risk hidden>收起当前项</button>${!readonly?'<button type="button" data-add-risk>＋ 增加风险点</button><button class="primary" type="submit" form="schemeForm" data-save-scheme>保存方案</button>':''}</div></div>${!readonly?'<div class="risk-bulk"><button type="button" data-bulk="enable">启用选中</button><button type="button" data-bulk="disable">停用选中</button><small id="riskSelectionCount"></small></div>':''}<p id="riskFilterStatus" class="settings-note"></p></div><div id="schemeRules"></div><div id="schemeVersions"></div></div>`;
    categories();$('#riskRuleSearch').value=q;$('#riskRuleCategory').value=category;ruleList();list();
    $('#schemeForm').onsubmit=run(async e=>{
      e.preventDefault();if(saving)return;applyExtra();
      const target=current,f=e.target,content={...draft,label:f.elements.label.value,description:f.elements.description.value};
      const signature=()=>JSON.stringify([draft,f.elements.label.value,f.elements.description.value,f.elements.enabled.checked,$('#riskExtra')?.value]);
      const stamp=signature(),openId=index===null?null:draft.rules[index].id,filter=$('#riskRuleSearch').value,category=$('#riskRuleCategory').value;
      const scroller=host.closest('.settings-content'),scroll=scroller?.scrollTop;
      saving=true;const button=$('[data-save-scheme]');button.disabled=true;
      try{
        const saved=await api('/api/risk-schemes/'+target.id,{method:'PUT',body:{revision:target.revision,content,enabled:f.elements.enabled.checked}});
        items=await api('/api/risk-schemes');selection=await api('/api/risk-schemes/options');
        if(!host.isConnected)return;
        if(current?.id!==target.id){list();return;}
        if(signature()!==stamp){current=saved;list();notice('先前修改已保存，当前新增改动尚未保存。');return;}
        dirty(false);editor(saved,{openId,q:filter,category});if(scroller)scroller.scrollTop=scroll;
        notice('审查方案已保存，下次执行使用新版本。');
      }finally{saving=false;if(button.isConnected)button.disabled=false;}
    });
    const request=versionRequest;
    api(`/api/risk-schemes/${item.id}/versions`).then(versions=>{if(request!==versionRequest)return;$('#schemeVersions').innerHTML=`<details><summary>历史版本（${versions.length}）</summary><div class="settings-history">${versions.map(v=>`<button data-scheme-version="${v.revision}" ${readonly?'disabled':''}>载入 v${v.revision} · ${new Date(v.created*1000).toLocaleString()}</button>`).join('')}</div></details>`;}).catch(e=>notice(e.message));
  }
  function categories(){
    const value=$('#riskRuleCategory').value;
    $('#riskRuleCategory').innerHTML='<option value="">全部分类</option>'+[...new Set(draft.rules.map(r=>r.category||'其他'))].sort().map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');$('#riskRuleCategory').value=value;
  }
  function updateEditingStatus(){
    const rule=index===null?null:draft.rules[index];
    $('#riskEditingStatus').textContent=rule?`${current.editable?'正在编辑':'正在查看'}：${rule.name} · ${rule.id}${modified.has(index)?' · 未保存':''}`:modified.size?`${modified.size} 个风险点有未保存修改`:'点击风险点，在本行展开详情';
    $('[data-collapse-risk]').hidden=index===null;
    if($('#riskSelectionCount'))$('#riskSelectionCount').textContent=`已选 ${checked.size} 项${modified.size?` · ${modified.size} 项未保存`:''}`;
  }
  function rowHeading(i){
    const r=draft.rules[i];
    return `<b>${esc(r.name)}</b><span>${esc(r.id)} · ${esc(r.category||'其他')} · ${esc(r.severity||'未设置严重程度')}${modified.has(i)?' · 未保存':''}</span>`;
  }
  function updateRow(i){
    const row=$(`[data-rule-index="${i}"]`);if(!row)return;
    const button=row.querySelector('[data-edit-risk]'),html=rowHeading(i);if(button.innerHTML!==html)button.innerHTML=html;
    button.setAttribute('aria-expanded',String(i===index));
    row.classList.toggle('is-expanded',i===index);row.querySelector('.risk-rule-row').classList.toggle('active',i===index);
    const badge=row.querySelector('.risk-rule-state'),enabled=draft.rules[i].enabled!==false;
    badge.textContent=i===index?(current.editable?'编辑中':'查看中'):enabled?'已启用':'已停用';badge.classList.toggle('disabled',!enabled);
    if(row.querySelector('[data-risk-check]')){row.querySelector('[data-risk-check]').checked=checked.has(i);row.querySelector('[data-risk-check]').setAttribute('aria-label','选择 '+draft.rules[i].name);}
    row.querySelector('fieldset')?.setAttribute('aria-label',draft.rules[i].name+' · '+draft.rules[i].id);
  }
  function ruleList(){
    const q=$('#riskRuleSearch').value.toLowerCase(),category=$('#riskRuleCategory').value;
    const visible=draft.rules.map((r,i)=>({r,i})).filter(({r})=>(!category||(r.category||'其他')===category)&&`${r.id} ${r.name} ${r.baseline}`.toLowerCase().includes(q));
    const matched=visible.length,pinned=index!==null&&!visible.some(v=>v.i===index);
    if(pinned)visible.unshift({r:draft.rules[index],i:index});
    const container=$('#schemeRules'),nodes=new Map([...container.children].map(n=>[Number(n.dataset.ruleIndex),n]));let previous=null;
    for(const {r,i} of visible){
      let row=nodes.get(i);nodes.delete(i);
      if(!row){row=document.createElement('article');row.className='risk-rule-card';row.dataset.ruleIndex=i;
        row.innerHTML=`<div class="risk-rule-row">${current.editable?`<input type="checkbox" data-risk-check="${i}" aria-label="选择 ${esc(r.name)}">`:''}<button type="button" data-edit-risk="${i}" aria-controls="risk-rule-detail-${i}"></button><small class="risk-rule-state"></small></div><div class="risk-inline-editor" id="risk-rule-detail-${i}" hidden></div>`;
      }
      const next=previous?previous.nextElementSibling:container.firstElementChild;if(next!==row)container.insertBefore(row,next);previous=row;
      updateRow(i);const body=row.lastElementChild;body.hidden=i!==index;
      if(i===index&&!body.firstElementChild)body.innerHTML=ruleFields(r);
      else if(i!==index)body.replaceChildren();
    }
    for(const row of nodes.values())row.remove();
    if(!visible.length)container.innerHTML='<p class="settings-empty">没有匹配的风险点。</p>';
    $('#riskFilterStatus').textContent=`${matched} / ${draft.rules.length} 项${pinned?' · 已保留当前编辑项':''}`;
    updateEditingStatus();
  }
  function ruleFields(r){
    const keys=['id','name','category','industry','severity','baseline','judgment_criteria','applies_to','enabled'];
    const extra=Object.fromEntries(Object.entries(r).filter(([k])=>!keys.includes(k)));
    return `<fieldset ${!current.editable?'disabled':''} class="risk-rule-editor" aria-label="${esc(r.name)} · ${esc(r.id)}">${input('名称','name',r.name,'maxlength="200"')}<div class="settings-fields">${input('分类','category',r.category)}${input('适用行业','industry',r.industry||'通用')}${input('严重程度','severity',r.severity)}${input('适用范围','applies_to',Array.isArray(r.applies_to)?r.applies_to.join('、'):r.applies_to)}</div>${area('公司基线','baseline',r.baseline,3)}${area('判定要点（每行一项）','judgment_criteria',r.judgment_criteria,3)}<label class="settings-check"><input type="checkbox" data-rule-enabled ${r.enabled!==false?'checked':''}>启用此风险点</label><details><summary>示例、检索提示与扩展字段</summary><p class="settings-note">保留现有字段。可以编辑 JSON 中的 examples、clause_hints 等。</p><textarea id="riskExtra" rows="7" spellcheck="false">${esc(JSON.stringify(extra,null,2))}</textarea><button type="button" data-apply-extra>应用扩展字段</button><small id="riskExtraStatus"></small></details></fieldset>`;
  }
  function ruleEditor(i){
    applyExtra();index=index===i?null:i;ruleList();
    if(index!==null){
      const row=$(`[data-rule-index="${index}"]`),scroller=host.closest('.settings-content'),bar=$('.risk-rules-controls');
      if(scroller)scroller.scrollTop+=row.getBoundingClientRect().top-scroller.getBoundingClientRect().top-bar.offsetHeight-8;
    }
  }
  function applyExtra(){
    if(index===null||!current.editable||!$('#riskExtra'))return;
    let extra;try{extra=JSON.parse($('#riskExtra').value);}catch{throw Error(`风险点“${draft.rules[index].name}”的扩展字段不是有效 JSON，请修正后继续。`);}
    if(!extra||Array.isArray(extra)||typeof extra!=='object')throw Error('扩展字段必须是 JSON 对象');
    const protectedKeys=['id','name','category','industry','severity','baseline','judgment_criteria','applies_to','enabled'];
    if(Object.keys(extra).some(k=>protectedKeys.includes(k)))throw Error('常用字段请在上方表单编辑');
    const r=draft.rules[index];for(const key of Object.keys(r))if(!protectedKeys.includes(key))delete r[key];Object.assign(r,extra);
  }
  $('#schemeSearch').oninput=list;
  $('#schemeImport').onchange=run(async e=>{if(!leave())return;const file=e.target.files[0];if(!file)return;if(file.size>3000000)throw new Error('方案文件不能超过 3 MB');const parsed=JSON.parse(await file.text());const content=Array.isArray(parsed)?{label:file.name.replace(/\.json$/i,''),rules:parsed}:parsed.content||parsed;const saved=await api('/api/risk-schemes',{method:'POST',body:{scope:'personal',content}});dirty(false);items=await api('/api/risk-schemes');editor(saved);notice('已导入为个人方案。');});
  host.addEventListener('input',e=>{
    const el=e.target;if(el.id==='riskRuleSearch'){ruleList();return;}
    if(el.dataset.ruleField&&index!==null){const key=el.dataset.ruleField;draft.rules[index][key]=key==='judgment_criteria'?el.value.split('\n').filter(Boolean):key==='applies_to'?el.value.split(/[、,，]/).map(s=>s.trim()).filter(Boolean):el.value;modified.add(index);dirty(true);updateRow(index);updateEditingStatus();}
    if(el.closest('#schemeForm'))dirty(true);
    if(el.id==='riskExtra'){modified.add(index);dirty(true);updateRow(index);updateEditingStatus();$('#riskExtraStatus').textContent='扩展字段尚未应用';}
  });
  host.addEventListener('change',e=>{if(e.target.id==='riskRuleCategory')ruleList();if(e.target.dataset.ruleField==='category')categories();if(e.target.dataset.riskCheck!==undefined){const i=Number(e.target.dataset.riskCheck);e.target.checked?checked.add(i):checked.delete(i);updateEditingStatus();}if(e.target.hasAttribute('data-rule-enabled')){draft.rules[index].enabled=e.target.checked;modified.add(index);dirty(true);updateRow(index);updateEditingStatus();}});
  host.addEventListener('click',run(async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.scheme&&leave()){dirty(false);editor(items.find(s=>s.id===b.dataset.scheme));}
    if(b.hasAttribute('data-delete-scheme')){
      if(deleting||!current?.editable)return;const target=current;
      if(!confirm(`删除审查方案“${target.content.label}”？\n\n包含 ${target.content.rules.length} 个风险点。未保存修改也会丢弃。使用此方案的默认选择将恢复默认，历史报告与执行快照保留。`))return;
      deleting=true;b.disabled=true;
      try{
        await api(`/api/risk-schemes/${target.id}?revision=${target.revision}`,{method:'DELETE'});
        items=await api('/api/risk-schemes');selection=await api('/api/risk-schemes/options');
        if(!host.isConnected)return;
        if(current?.id===target.id){dirty(false);versionRequest++;current=null;draft=null;index=null;checked.clear();modified.clear();$('#schemeEditor').innerHTML='<p class="settings-empty">审查方案已删除。选择其他方案继续查看。</p>';}
        list();notice('审查方案已删除，历史报告仍保留原有依据。');
      }finally{deleting=false;if(b.isConnected)b.disabled=false;}
    }
    if(b.hasAttribute('data-inherit-risk')){await api('/api/risk-schemes/selection',{method:'PUT',body:{id:null}});selection=await api('/api/risk-schemes/options');list();notice('已恢复默认审查方案。');}
    if(b.hasAttribute('data-new-scheme')&&leave()){
      const saved=await api('/api/risk-schemes',{method:'POST',body:{scope:$('#newSchemeScope')?.value||'personal',content:{label:'新的审查方案',description:'',rules:[]}}});dirty(false);items=await api('/api/risk-schemes');editor(saved);
    }
    if(b.hasAttribute('data-copy-scheme')&&leave()){const saved=await api(`/api/risk-schemes/${current.id}/copy`,{method:'POST',body:{}});dirty(false);items=await api('/api/risk-schemes');editor(saved);notice('已复制为个人方案。');}
    if(b.hasAttribute('data-use-scheme')){await api('/api/risk-schemes/selection',{method:'PUT',body:{id:current.id}});selection=await api('/api/risk-schemes/options');b.textContent='我的默认方案';list();notice('已选择此审查方案。');}
    if(b.hasAttribute('data-default-scheme')){const target=current.id,prefs=await api('/api/settings');await api(`/api/risk-schemes/${target}/default`,{method:'POST',body:{revision:prefs.organization.revision}});selection=await api('/api/risk-schemes/options');list();const remove=$('[data-delete-scheme]');if(remove){remove.disabled=selection.default===current.id;remove.title=remove.disabled?'请先将其他方案设为默认':'';}notice('已设置为默认方案。');}
    if(b.hasAttribute('data-collapse-risk'))ruleEditor(index);
    if(b.hasAttribute('data-add-risk')){applyExtra();draft.rules.push({id:'CUSTOM-'+Date.now().toString(36).toUpperCase(),name:'新的风险点',category:'其他',industry:'通用',severity:'中',baseline:'',judgment_criteria:[],enabled:true});modified.add(draft.rules.length-1);dirty(true);categories();ruleEditor(draft.rules.length-1);}
    if(b.dataset.editRisk!==undefined)ruleEditor(Number(b.dataset.editRisk));
    if(b.dataset.bulk){for(const i of checked){draft.rules[i].enabled=b.dataset.bulk==='enable';modified.add(i);updateRow(i);}if(checked.size)dirty(true);if(index!==null&&$('[data-rule-enabled]'))$('[data-rule-enabled]').checked=draft.rules[index].enabled!==false;updateEditingStatus();}
    if(b.hasAttribute('data-apply-extra')){applyExtra();dirty(true);$('#riskExtraStatus').textContent='已应用，保存方案后生效';}
    if(b.dataset.schemeVersion&&leave()){const old=await api(`/api/risk-schemes/${current.id}?revision=${b.dataset.schemeVersion}`);editor({...current,content:old.content});dirty(true);notice(`已载入 v${old.revision}，保存方案后生成新版本。`);}
  }));
  list();
}
