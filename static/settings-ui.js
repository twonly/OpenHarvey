import {t as tr,ui} from './i18n.js';
import {getLanguage,setLanguage} from './i18n.js';
import {labels as liveLabels} from './i18n.js';
import {loadingHTML} from './loading-ui.js';
import {accountIdentityHTML} from './account-identity.js';
import {renderUsers,orcaConnect} from './account-ui.js?v=20260914-loading-all';
import {api} from './api.js';
import {esc} from './markdown.js';
import {settingsPaths,settingsTab,savedWorkbenchURL} from './settings-routes.js';

const scopes=liveLabels({builtin:'内置',public:'公开示例',personal:'我的'});
export function preferenceValues(previous,entries){
  const values={...previous,onboarding_completed:true};
  for(const [key,value]of entries){if(value==='')delete values[key];else values[key]=value;}
  return values;
}
export function setupSettings({notice,onClose,onOpen}){
  const root=document.createElement('section');root.id='settingsView';root.hidden=true;root.setAttribute('aria-label',tr('工作台设置'));document.body.append(root);
  let identity=null,tab='general',dirty=false,returnURL='',items=[],selected=null,files={},generation=0;
  const $=sel=>root.querySelector(sel);
  const run=fn=>async(...args)=>{try{await fn(...args);}catch(e){notice(e.message);}};
  document.addEventListener('ui-language-changed',()=>{if(!root.hidden&&!dirty)void render();});
  document.addEventListener('memory-changed',()=>{if(!root.hidden&&tab==='labs'&&!dirty)void render().catch(e=>notice(e.message));});
  window.addEventListener('focus',()=>{if(!root.hidden&&tab==='labs'&&!dirty)void render().catch(e=>notice(e.message));});
  const leave=()=>!dirty||confirm(tr('有尚未保存的修改，确定离开？'));
  const field=(label,name,value='',extra='')=>`<label>${esc(label)}<input name="${name}" value="${esc(value??'')}" ${extra}></label>`;
  const area=(label,name,value='',rows=4,extra='')=>`<label>${esc(label)}<textarea name="${name}" rows="${rows}" ${extra}>${esc(value??'')}</textarea></label>`;
  const select=(label,name,value,options)=>`<label>${esc(label)}<select name="${name}">${options.map(([v,l])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;
  function shell(){
    root.setAttribute('aria-label',tr('工作台设置'));
    root.innerHTML=ui`<div class="settings-nav"><div class="settings-title"><b>设置</b><button data-close aria-label="返回工作台">×</button></div><nav aria-label="设置导航">${[['general',tr('通用设置')],['labs','Labs'],['skills','Skills'],['risks',tr('风险库')],['traces',tr('执行记录')],['providers',tr('模型与服务')],...(identity.capabilities?.feishu?[['connectors',tr('连接器')]]:[]),...(identity.role==='admin'?[['members',tr('用户管理')]]:[])].map(([id,label])=>`<button data-tab="${id}" aria-current="${tab===id?'page':'false'}">${label}</button>`).join('')}</nav><p>${identity.account_kind==='demo'?tr('免登录体验'):tr('我的账户')}<br><span>${accountIdentityHTML(identity)} · ${identity.role==='admin'?tr('平台管理员'):identity.account_kind==='demo'?'demo':tr('个人用户')}</span></p><a class="settings-guide-link" href="/guide" target="_blank" rel="noopener">设置指南 ↗</a><button data-close class="settings-back">← 返回工作台</button></div><div class="settings-content"><div id="settingsPage"></div></div>`;
    $('[aria-current="page"]').scrollIntoView({block:'nearest',inline:'nearest'});
  }
  function route(next,mode){if(mode!=='none'&&location.pathname!==settingsPaths[next])history[mode==='replace'?'replaceState':'pushState'](null,'',settingsPaths[next]);}
  async function open(next='general',{historyMode='push',user=null}={}){
    if(!root.hidden&&!leave())return;
    identity=user||await api('/api/me');
    if(['members','organization'].includes(next)&&identity.role!=='admin'){next='general';historyMode='replace';notice(tr('当前账号不能访问管理页面。'));}
    if(root.hidden)returnURL=settingsTab(location.pathname)?savedWorkbenchURL(sessionStorage.getItem('workbench-location')):location.pathname+location.search+location.hash;
    document.getElementById('workspaceSwitcher').open=false;
    document.getElementById('appShell').inert=true;
    root.hidden=false;tab=next;dirty=false;route(next,historyMode);onOpen?.();
    try{await render();}catch(error){$('#settingsPage').innerHTML='<p class="settings-empty" role="alert">'+esc(error.message)+'</p>';throw error;}
  }
  async function close({historyMode='push'}={}){
    if(!leave())return false;dirty=false;generation++;root.hidden=true;root.replaceChildren();document.getElementById('appShell').inert=false;
    if(historyMode!=='none')history.pushState(null,'',returnURL||'/');await onClose?.();
    return true;
  }
  const heading=(title,caption,actions='')=>`<div class="settings-heading"><div><h2>${title}</h2><p>${caption}</p></div>${actions}</div>`;
  async function render(){
    const g=++generation;shell();$('#settingsPage').innerHTML=loadingHTML(tr('正在读取设置…'));
    if(tab==='members'){await renderUsers($('#settingsPage'),notice);return;}
    if(tab==='providers'&&identity.account_kind==='demo'){$('#settingsPage').replaceChildren();orcaConnect($('#settingsPage'),identity);return;}
    if(['providers','members'].includes(tab)){
      const {renderAdmin}=await import('./admin-ui.js?v=20260916-provider-config');if(g!==generation)return;
      await renderAdmin($('#settingsPage'),{mode:tab,identity,notice,dirty:value=>dirty=value,leave});if(g===generation)orcaConnect($('#settingsPage'),identity);return;
    }
    if(tab==='labs'){
      const {renderLabs}=await import('./memory-ui.js');if(g!==generation)return;
      await renderLabs($('#settingsPage'),{notice,dirty:value=>dirty=value,isCurrent:()=>g===generation});return;
    }
    if(tab==='connectors'){
      const {renderConnectors}=await import('./connectors-ui.js');if(g!==generation)return;
      await renderConnectors($('#settingsPage'),{notice,dirty:value=>dirty=value,isCurrent:()=>g===generation});return;
    }
    if(tab==='traces'){
      const {renderTraces}=await import('./traces-ui.js?v=20260912-5');if(g!==generation)return;
      await renderTraces($('#settingsPage'),{identity,notice});return;
    }
    if(tab==='risks'){
      const {renderRiskSettings}=await import('./risk-settings-ui.js?v=20260913-2');if(g!==generation)return;
      await renderRiskSettings($('#settingsPage'),{identity,notice,dirty:value=>dirty=value,leave});return;
    }
    if(tab==='skills'){
      items=await api('/api/skills');if(g!==generation)return;
      $('#settingsPage').innerHTML=heading('Skills',tr('将常用任务写成可复用的指引。'),tr('<button data-new-skill class="primary">新建 Skill</button>'))+ui`<div class="settings-split"><div class="settings-list-panel"><input id="skillSearch" type="search" placeholder="搜索 Skills" aria-label="搜索 Skills"><select id="skillScope" aria-label="Skill 来源"><option value="">全部来源</option>${Object.entries(scopes).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select><div id="skillList"></div></div><div id="skillEditor"><p class="settings-empty">选择一个 Skill 查看或编辑。</p></div></div>`;
      renderList();return;
    }
    const prefs=await api('/api/settings');if(g!==generation)return;
    let catalog;try{catalog=await api('/api/models');}catch{catalog={models:[]};}
    if(g!==generation)return;
    const modelOptions=[['',tr('恢复系统默认')],...catalog.models.map(m=>[m.id,m.label])];
    const prefFields=values=>select(tr('界面语言'),'ui_language',values.ui_language||getLanguage(),[['zh-CN','简体中文'],['en','English']])+`<p class="settings-note">${tr('只影响页面和操作提示，不改变 Agent 回复或报告语言。')}</p>`+select(tr('默认模型'),'model',values.model||'',modelOptions)+field(tr('默认我方立场'),'perspective',values.perspective||'',tr('placeholder="系统默认" maxlength="120"'))+select(tr('默认执行方式'),'permission_mode',values.permission_mode||'',[['',tr('恢复系统默认')],['full',tr('全权执行（云端沙箱）')],['auto',tr('常规执行')],['cautious',tr('谨慎执行')]])+select(tr('回答详略'),'verbosity',values.verbosity||'',[['',tr('恢复系统默认')],['concise',tr('简洁')],['normal',tr('标准')],['detailed',tr('详细')]]);
    {
      $('#settingsPage').innerHTML=heading(tr('通用设置'),tr('默认值用于新任务；对话中明确指定的立场与要求优先。'))+ui`<form id="preferencesForm" class="settings-form" data-revision="${prefs.revision}"><div class="settings-fields">${prefFields(prefs.values)}${field(tr('助手名称'),'assistant_name',prefs.effective.assistant_name,'maxlength="32" required')}${field(tr('如何称呼你'),'user_nickname',prefs.effective.user_nickname,tr('maxlength="32" placeholder="您"'))}${area(tr('业务背景'),'background',prefs.effective.background)}${area(tr('补充指引'),'guidance',prefs.effective.guidance)}</div><div class="settings-defaults">${[['model',tr('模型')],['perspective',tr('立场')],['permission_mode',tr('执行方式')],['verbosity',tr('回答详略')]].map(([k,l])=>`<span>${l} · ${esc(tr(prefs.sources[k]))}：${esc(({full:tr('全权执行'),auto:tr('常规执行'),cautious:tr('谨慎执行'),normal:tr('标准'),concise:tr('简洁'),detailed:tr('详细')})[prefs.effective[k]]||prefs.effective[k]||tr('运行环境默认'))}</span>`).join('')}</div><div class="settings-form-actions"><button class="primary" type="submit">保存设置</button><button type="button" data-reset>恢复系统默认</button></div></form>${identity.role==='admin'&&!identity.auth_subject?tr('<a href="/login?link=1">绑定 GitHub / Google / 邮箱登录身份</a>'):''}<details class="settings-password" ${identity.auth_subject||identity.account_kind==='demo'?'hidden':''}><summary>修改密码</summary><form id="passwordForm" class="settings-form">${field(tr('当前密码'),'current','','type="password" autocomplete="current-password" required')}${field(tr('新密码'),'password','','type="password" autocomplete="new-password" minlength="8" maxlength="200" required')}${field(tr('确认新密码'),'confirm','','type="password" autocomplete="new-password" required')}<button type="submit">修改并重新登录</button></form></details>`;
      $('#preferencesForm').onsubmit=run(async e=>{e.preventDefault();const values=preferenceValues(prefs.values,new FormData(e.target));await api('/api/settings',{method:'PUT',body:{values,revision:prefs.revision}});dirty=false;setLanguage(values.ui_language);notice(tr('个人设置已保存。'));await render();});
      $('[data-reset]').onclick=run(async()=>{if(!leave())return;await api('/api/settings',{method:'PUT',body:{values:{onboarding_completed:true,ui_language:'zh-CN'},revision:prefs.revision}});dirty=false;setLanguage('zh-CN');notice(tr('已恢复系统默认。'));await render();});
      $('#passwordForm').onsubmit=run(async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(data.password!==data.confirm)throw new Error(tr('两次新密码不一致'));await api('/api/settings/password',{method:'PUT',body:data});dirty=false;root.hidden=true;document.getElementById('appShell').inert=false;document.dispatchEvent(new Event('session-expired'));notice(tr('密码已修改，请重新登录。'));});
    }
  }
  function renderList(){
    const q=$('#skillSearch').value.trim().toLowerCase(),scope=$('#skillScope').value;
    $('#skillList').innerHTML=items.filter(s=>(!scope||s.scope===scope)&&`${s.content.label} ${s.name} ${s.content.description}`.toLowerCase().includes(q)).map(s=>`<button data-skill-edit="${esc(s.id)}" class="settings-list-item ${selected?.id===s.id?'active':''}"><b>${esc(s.content.label)}</b><span>${scopes[s.scope]}${s.enabled?'':tr(' · 已停用')} · v${s.revision}</span><p>${esc(s.content.description)}</p></button>`).join('')||tr('<p class="settings-empty">没有匹配的 Skill。</p>');
  }
  function editor(item){
    selected=item;files={...(item?.content.files||{})};const c=item?.content||{},readonly=item&&!item.editable;
    $('#skillEditor').innerHTML=ui`<form id="skillForm" class="settings-form"><div class="settings-editor-head"><h3>${item?tr('编辑 Skill'):tr('新建 Skill')}</h3>${item?ui`<span class="settings-tag">${scopes[item.scope]} · v${item.revision}</span><button type="button" data-copy-skill>复制到我的 Skills</button>`:''}</div>${readonly?tr('<p class="settings-note">此 Skill 只读。复制为个人 Skill 后可以调整。</p>'):''}<fieldset ${readonly?'disabled':''}>${field(tr('Skill 名称'),'label',c.label,'required maxlength="100"')}${area(tr('用途说明'),'description',c.description,2,tr('required maxlength="1024" placeholder="说明什么时候使用这个 Skill"'))}${area(tr('Markdown 正文'),'body',c.body,16,tr('required maxlength="100000" placeholder="描述任务步骤、要求与输出格式…"'))}<div class="settings-reference-head"><b>参考文件</b><label class="settings-file-add">＋ 添加 Markdown / TXT<input id="skillFiles" type="file" accept=".md,.txt" multiple hidden></label></div><div id="skillFileList"></div><details><summary>高级选项</summary>${!item&&identity.role==='admin'?select(tr('适用范围'),'scope','personal',[['personal',tr('我的 Skill')],['public',tr('公开示例 Skill')]]):''}<label class="settings-check"><input type="checkbox" name="enabled" ${!item||item.enabled?'checked':''}>启用此 Skill</label></details></fieldset>${!readonly?tr('<div class="settings-form-actions"><button type="submit" class="primary">保存 Skill</button>')+ (item?tr('<button type="button" data-delete-skill class="settings-danger">删除</button>'):'')+'</div>':''}<div id="skillVersions"></div></form>`;
    renderFiles(readonly);
    $('#skillFiles').onchange=run(async e=>{for(const f of e.target.files){if(!/\.(md|txt)$/i.test(f.name)||f.size>500000)throw new Error(tr('参考文件仅支持 Markdown / TXT，每个最多 500 KB'));const path='references/'+f.name;if(files[path]!==undefined&&!confirm(ui`替换参考文件 ${f.name}？`))continue;files[path]=await f.text();}dirty=true;renderFiles(false);e.target.value='';});
    $('#skillForm').onsubmit=run(async e=>{e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));const body={content:{label:d.label,description:d.description,body:d.body,files},enabled:d.enabled==='on',revision:item?.revision,scope:d.scope||'personal'};const saved=await api('/api/skills'+(item?'/'+item.id:''),{method:item?'PUT':'POST',body});dirty=false;items=await api('/api/skills');renderList();editor(saved);notice(tr('Skill 已保存。'));});
    if(item){
      $('[data-copy-skill]').onclick=run(async()=>{if(!leave())return;const copy=await api(`/api/skills/${item.id}/copy`,{method:'POST',body:{}});dirty=false;items=await api('/api/skills');editor(copy);renderList();notice(tr('已复制到我的 Skills。'));});
      if(!readonly)$('[data-delete-skill]').onclick=run(async()=>{if(!confirm(ui`删除“${c.label}”？历史执行仍保留原版本。`))return;await api(`/api/skills/${item.id}?revision=${item.revision}`,{method:'DELETE'});dirty=false;selected=null;await render();notice(tr('Skill 已删除。'));});
      if(item.scope!=='builtin')loadVersions(item);
    }
  }
  async function loadVersions(item){
    try{const versions=await api(`/api/skills/${item.id}/versions`);if(selected?.id!==item.id||!$('#skillVersions'))return;
    $('#skillVersions').innerHTML=ui`<details><summary>历史版本（${versions.length}）</summary><div class="settings-history">${versions.map(v=>`<button type="button" data-version="${v.revision}">v${v.revision} · ${new Date(v.created*1000).toLocaleString(getLanguage())}${v.revision===item.revision?tr(' · 当前'):''}</button>`).join('')}</div></details>`;
    }catch(e){notice(e.message);}
  }
  function renderFiles(readonly){
    $('#skillFileList').innerHTML=Object.entries(files).map(([path,body])=>ui`<details class="settings-reference"><summary>${esc(path)} <small>${body.length} 字</small></summary><textarea aria-label="${esc(path)}" data-reference="${esc(path)}" rows="8" ${readonly?'readonly':''}>${esc(body)}</textarea>${!readonly?ui`<button type="button" data-remove-reference="${esc(path)}">移除文件</button>`:''}</details>`).join('')||tr('<p class="settings-note">可以添加任务说明、示例或业务参考资料。</p>');
  }
  root.addEventListener('input',e=>{if(['risks','traces','providers','members','connectors','labs'].includes(tab))return;if(e.target.id==='skillSearch'){renderList();return;}dirty=true;if(e.target.dataset.reference)files[e.target.dataset.reference]=e.target.value;});
  root.addEventListener('change',e=>{if(['risks','traces','providers','members','connectors','labs'].includes(tab))return;if(e.target.id==='skillScope')renderList();else dirty=true;});
  root.addEventListener('click',run(async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.hasAttribute('data-close'))await close();
    if(b.dataset.tab&&leave()){tab=b.dataset.tab;route(tab,'push');dirty=false;selected=null;await render();}
    if(b.hasAttribute('data-new-skill')&&leave()){dirty=false;editor(null);renderList();}
    if(b.dataset.skillEdit&&leave()){dirty=false;editor(items.find(s=>s.id===b.dataset.skillEdit));renderList();}
    if(b.dataset.removeReference){delete files[b.dataset.removeReference];dirty=true;renderFiles(false);}
    if(b.dataset.version&&leave()){
      const old=await api(`/api/skills/${selected.id}?revision=${b.dataset.version}`),current=items.find(s=>s.id===selected.id);
      editor({...current,content:old.content});dirty=true;notice(ui`已载入 v${old.revision}，点击保存后生成新版本。`);
    }
  }));
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  window.addEventListener('popstate',run(async()=>{
    if(document.body.dataset.auth!=='ready')return;
    if(!root.hidden&&!leave()){history.pushState(null,'',settingsPaths[tab]);return;}
    dirty=false;const next=settingsTab(location.pathname);
    if(next){if(root.hidden||next!==tab)await open(next,{historyMode:'none'});}
    else if(!root.hidden)await close({historyMode:'none'});
  }));
  document.addEventListener('session-expired',()=>{dirty=false;generation++;root.hidden=true;root.replaceChildren();document.getElementById('appShell').inert=false;});
  return {open,close,isOpen:()=>!root.hidden};
}
