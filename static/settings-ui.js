import {renderUsers,orcaConnect} from './account-ui.js';
import {skillEnvironmentsHTML} from './skill-environments.js?v=20260912-21';
import {api} from './api.js';
import {esc} from './markdown.js';
import {renderAdmin} from './admin-ui.js?v=20260911-14';
import {renderTraces} from './traces-ui.js?v=20260912-5';
import {renderRiskSettings} from './risk-settings-ui.js?v=20260913-2';
import {settingsPaths,settingsTab,savedWorkbenchURL} from './settings-routes.js';

const scopes={builtin:'内置',public:'公开示例',personal:'我的'};
export function setupSettings({notice,onClose}){
  const root=document.createElement('section');root.id='settingsView';root.hidden=true;root.setAttribute('aria-label','工作台设置');document.body.append(root);
  let identity=null,tab='general',dirty=false,returnURL='',items=[],selected=null,files={},generation=0;
  const $=sel=>root.querySelector(sel);
  const run=fn=>async(...args)=>{try{await fn(...args);}catch(e){notice(e.message);}};
  const leave=()=>!dirty||confirm('有尚未保存的修改，确定离开？');
  const field=(label,name,value='',extra='')=>`<label>${esc(label)}<input name="${name}" value="${esc(value??'')}" ${extra}></label>`;
  const area=(label,name,value='',rows=4,extra='')=>`<label>${esc(label)}<textarea name="${name}" rows="${rows}" ${extra}>${esc(value??'')}</textarea></label>`;
  const select=(label,name,value,options)=>`<label>${esc(label)}<select name="${name}">${options.map(([v,l])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;
  function shell(){
    root.innerHTML=`<div class="settings-nav"><div class="settings-title"><b>设置</b><button data-close aria-label="返回工作台">×</button></div><nav aria-label="设置导航">${[['general','通用设置'],['skills','Skills'],['risks','风险库'],['traces','执行记录'],['providers','模型与服务'],...(identity.role==='admin'?[['members','用户管理']]:[])].map(([id,label])=>`<button data-tab="${id}" aria-current="${tab===id?'page':'false'}">${label}</button>`).join('')}</nav><p>${identity.account_kind==='demo'?'免登录体验':'我的账户'}<br><span>${esc(identity.username)} · ${identity.role==='admin'?'平台管理员':identity.account_kind==='demo'?'demo':'个人用户'}</span></p><a class="settings-guide-link" href="/guide" target="_blank" rel="noopener">设置指南 ↗</a><button data-close class="settings-back">← 返回工作台</button></div><div class="settings-content"><div id="settingsPage"></div></div>`;
    $('[aria-current="page"]').scrollIntoView({block:'nearest',inline:'nearest'});
  }
  function route(next,mode){if(mode!=='none'&&location.pathname!==settingsPaths[next])history[mode==='replace'?'replaceState':'pushState'](null,'',settingsPaths[next]);}
  async function open(next='general',{historyMode='push',user=null}={}){
    if(!root.hidden&&!leave())return;
    identity=user||await api('/api/me');
    if(['members','organization'].includes(next)&&identity.role!=='admin'){next='general';historyMode='replace';notice('当前账号不能访问管理页面。');}
    if(root.hidden)returnURL=settingsTab(location.pathname)?savedWorkbenchURL(sessionStorage.getItem('workbench-location')):location.pathname+location.search+location.hash;
    document.getElementById('workspaceSwitcher').open=false;
    document.getElementById('appShell').inert=true;
    root.hidden=false;tab=next;dirty=false;route(next,historyMode);
    await render();
  }
  async function close({historyMode='push'}={}){
    if(!leave())return false;dirty=false;generation++;root.hidden=true;root.replaceChildren();document.getElementById('appShell').inert=false;
    if(historyMode!=='none')history.pushState(null,'',returnURL||'/');await onClose?.();
    return true;
  }
  const heading=(title,caption,actions='')=>`<div class="settings-heading"><div><h2>${title}</h2><p>${caption}</p></div>${actions}</div>`;
  async function render(){
    const g=++generation;shell();$('#settingsPage').innerHTML='<p class="settings-empty">正在读取…</p>';
    if(tab==='members'){await renderUsers($('#settingsPage'),notice);return;}
    if(tab==='providers'&&identity.account_kind==='demo'){orcaConnect($('#settingsPage'),identity);return;}
    if(['providers','members'].includes(tab)){await renderAdmin($('#settingsPage'),{mode:tab,identity,notice,dirty:value=>dirty=value,leave});orcaConnect($('#settingsPage'),identity);return;}
    if(tab==='traces'){await renderTraces($('#settingsPage'),{identity,notice});return;}
    if(tab==='risks'){await renderRiskSettings($('#settingsPage'),{identity,notice,dirty:value=>dirty=value,leave});return;}
    if(tab==='skills'){
      items=await api('/api/skills');if(g!==generation)return;
      $('#settingsPage').innerHTML=heading('Skills','将常用任务写成可复用的指引。保存后自动同步到空闲环境；运行中的任务结束后生效。','<button data-new-skill class="primary">新建 Skill</button>')+`<div id="skillEnvironments" aria-live="polite"></div><div class="settings-split"><div class="settings-list-panel"><input id="skillSearch" type="search" placeholder="搜索 Skills" aria-label="搜索 Skills"><select id="skillScope" aria-label="Skill 来源"><option value="">全部来源</option>${Object.entries(scopes).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select><div id="skillList"></div></div><div id="skillEditor"><p class="settings-empty">选择一个 Skill 查看或编辑。</p></div></div>`;
      renderList();void refreshEnvironments();return;
    }
    const prefs=await api('/api/settings');if(g!==generation)return;
    let catalog;try{catalog=await api('/api/models');}catch{catalog={models:[]};}
    if(g!==generation)return;
    const modelOptions=[['','恢复系统默认'],...catalog.models.map(m=>[m.id,m.label])];
    const prefFields=values=>select('默认模型','model',values.model||'',modelOptions)+field('默认我方立场','perspective',values.perspective||'','placeholder="系统默认" maxlength="120"')+select('默认执行方式','permission_mode',values.permission_mode||'',[['','恢复系统默认'],['full','全权执行（云端沙箱）'],['auto','常规执行'],['cautious','谨慎执行']])+select('回答详略','verbosity',values.verbosity||'',[['','恢复系统默认'],['concise','简洁'],['normal','标准'],['detailed','详细']]);
    {
      $('#settingsPage').innerHTML=heading('通用设置','默认值用于新任务；对话中明确指定的立场与要求优先。')+`<form id="preferencesForm" class="settings-form" data-revision="${prefs.revision}"><div class="settings-fields">${prefFields(prefs.values)}${field('助手名称','assistant_name',prefs.effective.assistant_name,'maxlength="32" required')}${field('如何称呼你','user_nickname',prefs.effective.user_nickname,'maxlength="32" placeholder="您"')}${area('业务背景','background',prefs.effective.background)}${area('补充指引','guidance',prefs.effective.guidance)}</div><div class="settings-defaults">${[['model','模型'],['perspective','立场'],['permission_mode','执行方式'],['verbosity','回答详略']].map(([k,l])=>`<span>${l} · ${esc(prefs.sources[k])}：${esc(({full:'全权执行',auto:'常规执行',cautious:'谨慎执行',normal:'标准',concise:'简洁',detailed:'详细'})[prefs.effective[k]]||prefs.effective[k]||'运行环境默认')}</span>`).join('')}</div><div class="settings-form-actions"><button class="primary" type="submit">保存设置</button><button type="button" data-reset>恢复系统默认</button></div></form>${identity.role==='admin'&&!identity.auth_subject?'<a href="/login?link=1">绑定 GitHub / Google / 邮箱登录身份</a>':''}<details class="settings-password" ${identity.auth_subject||identity.account_kind==='demo'?'hidden':''}><summary>修改密码</summary><form id="passwordForm" class="settings-form">${field('当前密码','current','','type="password" autocomplete="current-password" required')}${field('新密码','password','','type="password" autocomplete="new-password" minlength="8" maxlength="200" required')}${field('确认新密码','confirm','','type="password" autocomplete="new-password" required')}<button type="submit">修改并重新登录</button></form></details>`;
      $('#preferencesForm').onsubmit=run(async e=>{e.preventDefault();const values=Object.fromEntries([...new FormData(e.target)].filter(([,v])=>v!==''));await api('/api/settings',{method:'PUT',body:{values:{...values,onboarding_completed:true},revision:prefs.revision}});dirty=false;notice('个人设置已保存。');await render();});
      $('[data-reset]').onclick=run(async()=>{if(!leave())return;await api('/api/settings',{method:'PUT',body:{values:{onboarding_completed:true},revision:prefs.revision}});dirty=false;notice('已恢复系统默认。');await render();});
      $('#passwordForm').onsubmit=run(async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(data.password!==data.confirm)throw new Error('两次新密码不一致');await api('/api/settings/password',{method:'PUT',body:data});dirty=false;root.hidden=true;document.getElementById('appShell').inert=false;document.dispatchEvent(new Event('session-expired'));notice('密码已修改，请重新登录。');});
    }
  }
  let statusLoading=false;
  async function refreshEnvironments(){
    if(root.hidden||tab!=='skills'||!$('#skillEnvironments')||statusLoading)return;
    statusLoading=true;const g=generation;
    try{const rows=await api('/api/skill-environments');if(g===generation&&$('#skillEnvironments')){const html=skillEnvironmentsHTML(rows);if($('#skillEnvironments').innerHTML!==html)$('#skillEnvironments').innerHTML=html;}}
    catch(error){if(g===generation&&$('#skillEnvironments'))$('#skillEnvironments').textContent='环境状态暂不可用：'+error.message;}
    finally{statusLoading=false;}
  }
  setInterval(()=>{if(!document.hidden)void refreshEnvironments();},3000);
  function renderList(){
    const q=$('#skillSearch').value.trim().toLowerCase(),scope=$('#skillScope').value;
    $('#skillList').innerHTML=items.filter(s=>(!scope||s.scope===scope)&&`${s.content.label} ${s.name} ${s.content.description}`.toLowerCase().includes(q)).map(s=>`<button data-skill-edit="${esc(s.id)}" class="settings-list-item ${selected?.id===s.id?'active':''}"><b>${esc(s.content.label)}</b><span>${scopes[s.scope]}${s.enabled?'':' · 已停用'} · v${s.revision}</span><p>${esc(s.content.description)}</p></button>`).join('')||'<p class="settings-empty">没有匹配的 Skill。</p>';
  }
  function editor(item){
    selected=item;files={...(item?.content.files||{})};const c=item?.content||{},readonly=item&&!item.editable;
    $('#skillEditor').innerHTML=`<form id="skillForm" class="settings-form"><div class="settings-editor-head"><h3>${item?'编辑 Skill':'新建 Skill'}</h3>${item?`<span class="settings-tag">${scopes[item.scope]} · v${item.revision}</span><button type="button" data-copy-skill>复制到我的 Skills</button>`:''}</div>${readonly?'<p class="settings-note">此 Skill 只读。复制为个人 Skill 后可以调整。</p>':''}<fieldset ${readonly?'disabled':''}>${field('显示名称','label',c.label,'required maxlength="100"')}${area('用途说明','description',c.description,2,'required maxlength="1024" placeholder="说明什么时候使用这个 Skill"')}${area('Markdown 正文','body',c.body,16,'required maxlength="100000" placeholder="描述任务步骤、要求与输出格式…"')}<div class="settings-reference-head"><b>参考文件</b><label class="settings-file-add">＋ 添加 Markdown / TXT<input id="skillFiles" type="file" accept=".md,.txt" multiple hidden></label></div><div id="skillFileList"></div><details><summary>高级选项</summary>${item?`<p>调用名称：<code>${esc(item.name)}</code></p>`:field('调用名称','name','','pattern="[a-z0-9]+(-[a-z0-9]+)*" maxlength="40" placeholder="自动生成，也可填写 payment-check"')}${!item&&identity.role==='admin'?select('适用范围','scope','personal',[['personal','我的 Skill'],['public','公开示例 Skill']]):''}<label class="settings-check"><input type="checkbox" name="enabled" ${!item||item.enabled?'checked':''}>启用此 Skill</label></details></fieldset>${!readonly?'<div class="settings-form-actions"><button type="submit" class="primary">保存 Skill</button>'+ (item?'<button type="button" data-delete-skill class="settings-danger">删除</button>':'')+'</div>':''}<div id="skillVersions"></div></form>`;
    renderFiles(readonly);
    $('#skillFiles').onchange=run(async e=>{for(const f of e.target.files){if(!/\.(md|txt)$/i.test(f.name)||f.size>500000)throw new Error('参考文件仅支持 Markdown / TXT，每个最多 500 KB');const path='references/'+f.name;if(files[path]!==undefined&&!confirm(`替换参考文件 ${f.name}？`))continue;files[path]=await f.text();}dirty=true;renderFiles(false);e.target.value='';});
    $('#skillForm').onsubmit=run(async e=>{e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));const body={content:{label:d.label,description:d.description,body:d.body,files},enabled:d.enabled==='on',revision:item?.revision,name:d.name||undefined,scope:d.scope||'personal'};const saved=await api('/api/skills'+(item?'/'+item.id:''),{method:item?'PUT':'POST',body});dirty=false;items=await api('/api/skills');renderList();editor(saved);notice('Skill 已保存，生效进度见合同环境状态。');void refreshEnvironments();});
    if(item){
      $('[data-copy-skill]').onclick=run(async()=>{if(!leave())return;const copy=await api(`/api/skills/${item.id}/copy`,{method:'POST',body:{}});dirty=false;items=await api('/api/skills');editor(copy);renderList();notice('已复制到我的 Skills。');});
      if(!readonly)$('[data-delete-skill]').onclick=run(async()=>{if(!confirm(`删除“${c.label}”？历史执行仍保留原版本。`))return;await api(`/api/skills/${item.id}?revision=${item.revision}`,{method:'DELETE'});dirty=false;selected=null;await render();notice('Skill 已删除。');});
      if(item.scope!=='builtin')loadVersions(item);
    }
  }
  async function loadVersions(item){
    try{const versions=await api(`/api/skills/${item.id}/versions`);if(selected?.id!==item.id||!$('#skillVersions'))return;
    $('#skillVersions').innerHTML=`<details><summary>历史版本（${versions.length}）</summary><div class="settings-history">${versions.map(v=>`<button type="button" data-version="${v.revision}">v${v.revision} · ${new Date(v.created*1000).toLocaleString()}${v.revision===item.revision?' · 当前':''}</button>`).join('')}</div></details>`;
    }catch(e){notice(e.message);}
  }
  function renderFiles(readonly){
    $('#skillFileList').innerHTML=Object.entries(files).map(([path,body])=>`<details class="settings-reference"><summary>${esc(path)} <small>${body.length} 字</small></summary><textarea aria-label="${esc(path)}" data-reference="${esc(path)}" rows="8" ${readonly?'readonly':''}>${esc(body)}</textarea>${!readonly?`<button type="button" data-remove-reference="${esc(path)}">移除文件</button>`:''}</details>`).join('')||'<p class="settings-note">可以添加任务说明、示例或业务参考资料。</p>';
  }
  root.addEventListener('input',e=>{if(['risks','traces','providers','members'].includes(tab))return;if(e.target.id==='skillSearch'){renderList();return;}dirty=true;if(e.target.dataset.reference)files[e.target.dataset.reference]=e.target.value;});
  root.addEventListener('change',e=>{if(['risks','traces','providers','members'].includes(tab))return;if(e.target.id==='skillScope')renderList();else dirty=true;});
  root.addEventListener('click',run(async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.hasAttribute('data-close'))await close();
    if(b.dataset.tab&&leave()){tab=b.dataset.tab;route(tab,'push');dirty=false;selected=null;await render();}
    if(b.hasAttribute('data-retry-skills')){await api('/api/skill-environments/retry',{method:'POST',body:{}});await refreshEnvironments();}
    if(b.hasAttribute('data-new-skill')&&leave()){dirty=false;editor(null);renderList();}
    if(b.dataset.skillEdit&&leave()){dirty=false;editor(items.find(s=>s.id===b.dataset.skillEdit));renderList();}
    if(b.dataset.removeReference){delete files[b.dataset.removeReference];dirty=true;renderFiles(false);}
    if(b.dataset.version&&leave()){
      const old=await api(`/api/skills/${selected.id}?revision=${b.dataset.version}`),current=items.find(s=>s.id===selected.id);
      editor({...current,content:old.content});dirty=true;notice(`已载入 v${old.revision}，点击保存后生成新版本。`);
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
