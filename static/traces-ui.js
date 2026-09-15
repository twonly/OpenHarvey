import {t as tr,ui} from './i18n.js';
import {getLanguage} from './i18n.js';
import {api} from './api.js';
import {esc} from './markdown.js';
import {statusLabels,traceTimeline,traceTurnSummary} from './trace-view.js?v=20260911-16';
export async function renderTraces(host,{identity,notice}){
 let offset=0,request=0,refreshing=false;
 const members=[];
 if(!host.isConnected)return;
 const $=s=>host.querySelector(s),run=fn=>async(...args)=>{try{await fn(...args);}catch(e){if(host.isConnected)notice(e.message);}};
 host.innerHTML=ui`<div class="settings-heading"><div><h2>执行记录</h2><p>按合同和会话查看每轮消息、工具动作与保存结果。</p></div><button data-refresh-traces>刷新记录</button></div><div class="traces-filters"><input id="traceSearch" type="search" aria-label="搜索执行记录" placeholder="搜索合同、会话、ID 或消息"><select id="traceScope" aria-label="对话范围"><option value="active">当前对话</option><option value="archived">已归档</option><option value="deleted">最近删除</option><option value="all">全部对话</option></select><select id="traceStatus" aria-label="执行状态"><option value="">全部状态</option><option value="errors">有错误的记录</option>${Object.entries(statusLabels).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select>${members.length?ui`<select id="traceMember" aria-label="按成员筛选"><option value="">全部成员</option>${members.map(m=>`<option value="${m.id}" ${m.id===identity.id?'selected':''}>${esc(m.username)}</option>`).join('')}</select>`:''}</div><p id="traceSyncStatus" class="settings-note" role="status"></p><details class="trace-audit"><summary>E2B 运行环境</summary><p class="settings-note">包括会话创建前的启动失败；读取不会唤醒环境。</p><button data-load-sandboxes>读取环境与服务日志</button><div id="sandboxDiagnostics"></div></details><div id="traceList"></div><div class="trace-pagination"><button data-trace-prev>上一页</button><span id="traceCount"></span><button data-trace-next>下一页</button></div>${identity.role==='admin'?tr('<details class="trace-audit"><summary>管理操作记录</summary><button data-load-audit>读取最近记录</button><div id="traceAudit"></div></details>'):''}`;
 host.querySelector('[data-load-sandboxes]').onclick=run(async()=>{
  const data=await api('/api/traces/sandboxes');
  if(host.isConnected)$('#sandboxDiagnostics').innerHTML=data.workspaces.length?data.workspaces.map(w=>`<details><summary>${esc(w.title)} · ${esc(w.binding.status)}</summary><pre>${esc(JSON.stringify(w,null,2))}</pre></details>`).join(''):tr('<p>尚无 E2B 合同工作区。</p>');
 });
 const params=()=>new URLSearchParams({q:$('#traceSearch').value,status:$('#traceStatus').value,scope:$('#traceScope').value,...($('#traceMember')?.value?{user_id:$('#traceMember').value}:{})});
 const stateLabel=r=>r.deleted_at?tr(' · 已删除'):r.archived_at?tr(' · 已归档'):'';
 const label=(kind,id)=>`${kind} ID：${esc(id)}`;
 function group(className,id){const node=document.createElement('details');node.className=className;node.dataset.key=id;node.innerHTML='<summary></summary><div class="trace-group-body"></div>';return node;}
 // Reuse keyed rows so refresh keeps expanded messages, tools and reading position.
 function reconcile(container,rows,create,update,anchor=null){
  const old=new Map([...container.children].filter(n=>n!==anchor).map(n=>[n.dataset.key,n]));let prior=anchor;
  for(const row of rows){const node=old.get(row.id)||create(row);old.delete(row.id);update(node,row);const next=prior?prior.nextElementSibling:container.firstElementChild;if(next!==node)container.insertBefore(node,next);prior=node;}
  for(const node of old.values())node.remove();
 }
 function summary(node,html){const slot=node.firstElementChild;if(slot.innerHTML!==html)slot.innerHTML=html;}
 async function loading(node,fn,force=false){
  if(node._loading){await node._loading;if(!force)return;}
  if(!force&&node.dataset.loaded)return;
  const body=node.matches('.trace-turn')?node.querySelector('.trace-inline-detail'):node.lastElementChild;
  node._loading=(async()=>{try{if(!node.dataset.loaded)body.innerHTML=tr('<p class="settings-note">正在读取…</p>');await fn(body);node.dataset.loaded='1';}catch(e){if(node.isConnected){body.innerHTML=ui`<p class="trace-error-label">${esc(e.message)}</p><button data-trace-retry>重新读取</button>`;delete node.dataset.loaded;}}finally{node._loading=null;}})();
  return node._loading;
 }
 function sessionPanel(id){
  const node=document.createElement('section');node.className='trace-session';node.dataset.key=id;node.hidden=true;
  node.innerHTML='<div class="trace-session-heading"></div><div class="trace-group-body"></div>';return node;
 }
 async function chooseSession(contract,id,force=false){
  contract.dataset.session=id;
  for(const button of contract.querySelectorAll('.trace-session-choice'))button.setAttribute('aria-pressed',String(button.dataset.key===id));
  let selected;
  for(const panel of contract.querySelectorAll('.trace-session')){panel.hidden=panel.dataset.key!==id;if(!panel.hidden)selected=panel;}
  if(selected)await turns(selected,force);
 }
 async function threads(node,force=false){return loading(node,async body=>{
  const data=await api(`/api/traces/contracts/${node.dataset.key}/threads?`+params());if(!node.isConnected)return;
  if(!body.querySelector('.trace-session-choices'))body.innerHTML=tr('<nav class="trace-session-choices" aria-label="切换会话"></nav><div class="trace-session-panels"></div>');
  reconcile(body.querySelector('.trace-session-choices'),data.threads,r=>{const button=document.createElement('button');button.type='button';button.className='trace-session-choice';button.dataset.key=r.id;button.dataset.traceSession=r.id;return button;},(button,r)=>{
   const html=ui`<b>${esc(r.title)}${stateLabel(r)}</b><span>${r.run_count} 轮 · ${esc(r.id.slice(0,8))}</span>`;
   if(button.innerHTML!==html)button.innerHTML=html;button.title=label(tr('会话'),r.id);
  });
  reconcile(body.querySelector('.trace-session-panels'),data.threads,r=>sessionPanel(r.id),(panel,r)=>summary(panel,ui`<b>${esc(r.title)}${stateLabel(r)}</b><span>按发生顺序 · 点击行查看详情</span>`));
  if(!data.threads.length){body.innerHTML=tr('<p class="settings-note">暂无匹配会话。</p>');return;}
  const selected=data.threads.some(t=>t.id===node.dataset.session)?node.dataset.session:data.threads[0].id;
  await chooseSession(node,selected,force);
 },force);}
 function turnRow(id){
  const node=document.createElement('tbody');node.className='trace-turn';node.dataset.key=id;
  node.innerHTML=`<tr class="trace-run-row"></tr><tr class="trace-detail-row" id="trace-detail-${id}" hidden><td colspan="5"><div class="trace-inline-detail"></div></td></tr>`;return node;
 }
 function expandTurn(node,open){
  node.dataset.expanded=String(open);node.lastElementChild.hidden=!open;
  node.querySelector('[data-trace-turn]').setAttribute('aria-expanded',String(open));
 }
 async function turns(node,force=false,more=false){return loading(node,async body=>{
  const start=more?Number(node.dataset.count||0):0;
  const target=more?50:Math.max(50,Number(node.dataset.count||0));
  const data={runs:[],total:0};
  do{const page=await api(`/api/traces/threads/${node.dataset.key}/runs?offset=${start+data.runs.length}&limit=${Math.min(100,target-data.runs.length)}`);data.runs.push(...page.runs);data.total=page.total;if(!page.runs.length)break;}while(data.runs.length<target&&start+data.runs.length<data.total);
  if(!node.isConnected)return;
  if(!body.querySelector('.trace-turns'))body.innerHTML=tr('<div class="trace-table-scroll"><table class="trace-turns" aria-label="会话轮次"><thead><tr><th scope="col">轮次 / 用户消息</th><th scope="col">状态</th><th scope="col">模型</th><th scope="col">耗时 / 用量</th><th scope="col">工具</th></tr></thead></table></div><button data-trace-more hidden>继续查看后续轮次</button>');
  const items=more?[...(node._runs||[]),...data.runs]:data.runs;node._runs=items;node.dataset.count=String(items.length);
  reconcile(body.querySelector('.trace-turns'),items,r=>turnRow(r.id),(child,r)=>{
   const stamp=JSON.stringify(r.summary),changed=child.dataset.stamp&&child.dataset.stamp!==stamp;child.dataset.stamp=stamp;
   summary(child,traceTurnSummary(r,items.indexOf(r)+1,child.dataset.expanded==='true'));
   expandTurn(child,child.dataset.expanded==='true');
   if(changed){delete child.dataset.loaded;if(child.dataset.expanded==='true')detail(child);}
  },body.querySelector('.trace-turns thead'));
  body.querySelector('[data-trace-more]').hidden=items.length>=data.total;
 },force||more);}
 async function detail(node){return loading(node,async body=>{const data=await api('/api/traces/'+node.dataset.key);if(node.isConnected){body.classList.add('trace-inline-detail');body.innerHTML=traceTimeline(data);}});}
 async function list(){
  const n=++request,p=params();p.set('offset',String(offset));const data=await api('/api/traces/contracts?'+p);if(n!==request||!host.isConnected)return;
  reconcile($('#traceList'),data.contracts,r=>group('trace-contract',r.id),(node,r)=>summary(node,ui`<div class="trace-group-label"><b>${esc(r.title)}</b><small title="${label(tr('合同'),r.id)}">合同 ${esc(r.id.slice(0,8))} · ${esc(r.username)}</small></div><span class="trace-group-count">${r.thread_count} 个会话 · ${r.run_count} 轮记录</span>`));
  if(!data.contracts.length)$('#traceList').innerHTML=tr('<p class="settings-empty">还没有匹配的记录。</p>');
  $('#traceCount').textContent=ui`${data.total} 份合同`;host.querySelector('[data-trace-prev]').disabled=offset===0;host.querySelector('[data-trace-next]').disabled=offset+20>=data.total;
  for(const node of host.querySelectorAll('.trace-contract[open]'))await threads(node,true);
 }
 async function refresh(){
  if(refreshing)return;refreshing=true;const button=host.querySelector('[data-refresh-traces]'),slot=$('#traceSyncStatus');button.disabled=true;slot.textContent=tr('正在同步原生执行记录…');
  try{const ids=$('#traceMember')?.value?[$('#traceMember').value]:members.length?members.map(m=>m.id):[identity.id];let unavailable=0;
   for(const uid of ids){if(!host.isConnected)return;const r=await api('/api/traces/refresh',{method:'POST',body:{user_id:uid}});unavailable+=r.unavailable;}
   if(!host.isConnected)return;await list();slot.textContent=unavailable?ui`${unavailable} 个会话的运行环境暂不可用，已保留检索摘要。`:'';
  }catch(e){if(host.isConnected)slot.textContent=e.message;}finally{refreshing=false;button.disabled=false;}
 }
 let timer;$('#traceSearch').oninput=()=>{clearTimeout(timer);timer=setTimeout(run(async()=>{offset=0;await list();}),250);};$('#traceScope').onchange=$('#traceStatus').onchange=run(async()=>{offset=0;await list();});if($('#traceMember'))$('#traceMember').onchange=run(async()=>{offset=0;await list();await refresh();});
 host.addEventListener('toggle',run(async e=>{const n=e.target;if(!n.open)return;if(n.matches('.trace-contract'))await threads(n);}),true);
 host.addEventListener('click',run(async e=>{
  const row=e.target.closest('.trace-run-row');
  if(row){const node=row.parentElement,open=node.dataset.expanded!=='true';expandTurn(node,open);if(open)await detail(node);return;}
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.traceSession)await chooseSession(b.closest('.trace-contract'),b.dataset.traceSession);

  if(b.hasAttribute('data-refresh-traces'))await refresh();
  if(b.hasAttribute('data-trace-prev')){offset=Math.max(0,offset-20);await list();}
  if(b.hasAttribute('data-trace-next')){offset+=20;await list();}
  if(b.hasAttribute('data-trace-more'))await turns(b.closest('.trace-session'),true,true);
  if(b.hasAttribute('data-trace-retry')){const n=b.closest('.trace-turn,.trace-session,.trace-contract');if(n.matches('.trace-contract'))await threads(n);else if(n.matches('.trace-session'))await turns(n);else await detail(n);}
  if(b.hasAttribute('data-load-audit')){const rows=await api('/api/admin/audit');if(!host.isConnected)return;$('#traceAudit').innerHTML=rows.map(r=>`<p>${new Date(r.created*1000).toLocaleString(getLanguage())} · ${esc(r.username)} · ${esc(r.action)}<small>${esc(r.target)}</small></p>`).join('')||tr('<p>暂无管理操作记录。</p>');}
 }));
 await list();await refresh();
}
