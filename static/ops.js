import {accountLanguage} from './language-ui.js';
import {t as tr,ui} from './i18n.js';
import {getLanguage} from './i18n.js';
import {labels as liveLabels} from './i18n.js';
import {previewCitation} from './preview-citations.js';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const titles=liveLabels({overview:['运营总览','使用、交付与运行，集中在一处。'],users:['用户与使用','谁在使用，使用多深，还剩多少试用额度。'],runs:['任务与交付','从原生执行到正式文件，逐条查看真实状态。'],contracts:['合同与风险','当前期间新建的合同空间，以及已有审查与反馈。'],models:['模型与消耗','使用量、耗时和 Token；费用只展示已有记录。'],runtime:['运行状况','当前队列与沙箱快照，以及所选期间的运行事件。']});
const labels=liveLabels({completed:'正常完成',failed:'失败',interrupted:'中断',running:'运行中',queued:'排队中',dispatching:'准备中',submitted:'已提交',cancelled:'已取消',paused:'已暂停',ready:'就绪',active:'可用',killed:'已销毁',new:'未启动',lost:'已丢失',error:'异常',done:'已结算',reserved:'已预留',refunded:'已退还',summary:'合同摘要',review:'风险审查',revision:'修改稿',document:'通用文档'});
const number=v=>v==null?'—':Number(v).toLocaleString(getLanguage(),{maximumFractionDigits:1});
const percent=v=>v==null?'—':(v*100).toFixed(1)+'%';
const duration=v=>v==null?'—':v>=60?(v/60).toFixed(1)+tr(' 分'):v.toFixed(1)+tr(' 秒');
const time=v=>v?new Date(v*1000).toLocaleString(getLanguage(),{timeZone:'Asia/Shanghai',hour12:false}):tr('未记录');
const badge=s=>`<span class="status ${esc(s)}">${esc(labels[s]||s||tr('未记录'))}</span>`;
const empty=(title=tr('暂无记录'),copy=tr('所选范围内没有保留的数据。'))=>`<div class="empty"><b>${esc(title)}</b><p>${esc(copy)}</p></div>`;
const link=(kind,id,label)=>`<button data-detail="${esc(kind)}" data-id="${esc(id)}">${esc(label)}</button>`;
let state=Object.fromEntries(new URLSearchParams(location.search));
let view=titles[state.view]?state.view:'overview',currentData=null,lastResult=null,requestVersion=0,controller=null,detailVersion=0;
const isDetail=location.pathname==='/ops/detail';
const day=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
function dateRange(days){const end=day(),d=new Date(end+'T00:00:00+08:00');d.setTime(d.getTime()-(days-1)*86400000);return [d.toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'}),end];}
if(!state.start||!state.end)[state.start,state.end]=dateRange(7);
state.exclude_owner??='1';state.offset??='0';

async function api(url,signal){
 const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal});
 if(!response.ok){let data;try{data=await response.json();}catch{}const error=new Error(data?.detail||ui`读取失败 (${response.status})`);error.status=response.status;throw error;}
 return response.json();
}
function section(){return view==='contracts'&&state.dataset==='artifacts'?'artifacts':view;}
function params(section=view){
 const q=new URLSearchParams();
 for(const k of ['start','end','account_kind','user_id','exclude_owner','offset','sort','order','queue_offset','binding_offset','paused_offset'])if(state[k]!=null&&state[k]!=='')q.set(k,state[k]);
 if(section!=='overview'&&section!=='runtime'&&state.q)q.set('q',state.q);
 if(['runs','models'].includes(section))for(const k of ['status','model'])if(state[k])q.set(k,state[k]);
 if(section==='users'&&state.active_only)q.set('active_only',state.active_only);
 return q;
}
function saveURL(){const q=new URLSearchParams(state);q.set('view',view);history.replaceState(null,'','/ops?'+q);}
function restoreInputs(){
 for(const [id,key] of [['start','start'],['end','end'],['accountKind','account_kind'],['userId','user_id'],['model','model'],['status','status'],['search','q'],['sort','sort'],['order','order']])$(id).value=state[key]||({sort:'created',order:'desc'}[id]||'');
 $('excludeOwner').checked=state.exclude_owner!=='0';
 const count=Math.round((new Date(state.end)-new Date(state.start))/86400000)+1;
 $('period').value=state.end===day()&&[1,7,30].includes(count)?count===1?'today':String(count):'custom';
 $('customDates').hidden=$('period').value!=='custom';
}
function navigate(next,extra={}){view=next;state={...state,view:next,offset:'0',queue_offset:'0',binding_offset:'0',paused_offset:'0',q:'',status:'',model:'',sort:'created',order:'desc',active_only:'',dataset:'',...extra};restoreInputs();load();}
function card(title,body,cls='',note=''){return `<section class="card ${cls}"><div class="card-head"><h2>${esc(title)}</h2><small>${esc(note)}</small></div>${body}</section>`;}
function stat(title,value,note,target,extra={},featured=false){return `<button class="stat ${featured?'featured':''}" data-nav="${target}" data-extra="${esc(JSON.stringify(extra))}"><label>${esc(title)}</label><span class="arrow" aria-hidden="true">↗</span><strong>${esc(value)}</strong><small>${esc(note)}</small></button>`;}
function bars(rows,key='status',value='count'){
 const max=Math.max(1,...rows.map(r=>r[value]||0));
 return rows.length?rows.map(r=>`<div class="bar-row"><span>${esc(labels[r[key]]||r[key])}</span><div class="bar-track"><span style="width:${Math.max(0,(r[value]||0)/max*100)}%;background:${r[key]==='failed'?'#bb7468':r[key]==='interrupted'?'#c5a061':'#628965'}"></span></div><strong>${number(r[value])}</strong></div>`).join(''):empty();
}
function trend(rows){
 const series=[['runs',tr('执行量'),'#315f4c'],['completed',tr('正常完成'),'#8ab768'],['artifacts',tr('正式产出'),'#b4a170']];
 const max=Math.ceil(Math.max(1,...rows.flatMap(r=>series.map(([k])=>r[k]||0)))/3)*3,w=660,h=210,p=28;
 const x=i=>p+i*(w-p*2)/Math.max(1,rows.length-1),y=v=>h-p-(v/max)*(h-p*2);
 let svg=ui`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="每日执行、正常完成与正式产出趋势">`;
 for(let i=0;i<4;i++){const v=max*i/3;svg+=`<line x1="${p}" x2="${w-p}" y1="${y(v)}" y2="${y(v)}" stroke="#e5e9df"/><text x="0" y="${y(v)+4}">${number(v)}</text>`;}
 for(const [key,label,color] of series){svg+=`<polyline fill="none" stroke="${color}" stroke-width="2.5" points="${rows.map((r,i)=>`${x(i)},${y(r[key]||0)}`).join(' ')}"/>`;for(let i=0;i<rows.length;i++)svg+=`<circle cx="${x(i)}" cy="${y(rows[i][key]||0)}" r="3" fill="${color}"><title>${esc(rows[i].day)} ${label} ${number(rows[i][key])}</title></circle>`;}
 const points=[...new Set([0,Math.floor((rows.length-1)/2),rows.length-1])];
 for(const i of points)if(rows[i])svg+=`<text x="${x(i)}" y="${h-3}" text-anchor="middle">${rows[i].day.slice(5)}</text>`;
 return svg+'</svg><div class="legend">'+series.map(([,label,color])=>`<span><i style="background:${color}"></i>${label}</span>`).join('')+tr('</div><details class="subtle"><summary>查看每日数据</summary>')+table([tr('日期'),tr('活跃人数'),tr('执行'),tr('正常完成'),tr('产出')],rows.map(r=>[r.day,number(r.active_users),number(r.runs),number(r.completed),number(r.artifacts)]))+'</details>';
}
function table(headers,rows){return rows.length?`<div class="table-scroll"><table><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(c=>'<tr>'+c.map(v=>`<td>${v??'—'}</td>`).join('')+'</tr>').join('')}</tbody></table></div>`:empty();}
function runTable(rows){return table([tr('用户 / 合同'),tr('模型 / Skill'),tr('状态'),tr('耗时'),'Token',tr('同对话产出'),tr('时间')],rows.map(r=>[
 `${link('runs',r.id,r.workspace_title||tr('合同记录已清理'))}<small>${link('users',r.user_id,r.username)}</small>`,
 `${esc(r.model||tr('未记录'))}<small>${esc(r.explicit_skill||tr('未显式选择 Skill'))}</small>`,`${badge(r.status)}${r.tool_errors?ui`<small>工具错误 ${number(r.tool_errors)}</small>`:''}`,duration(r.duration),number(r.tokens),number(r.thread_artifacts),`<span class="nowrap">${esc(time(r.created))}</span>`]));}
function pagination(data,key='offset'){const off=Number(state[key]||0);return ui`<div class="pagination"><span>共 ${number(data.total)} 条 · 每页 ${data.limit||50} 条</span><button data-page="-1" data-offset-key="${key}" ${off===0?'disabled':''}>上一页</button><span>${Math.floor(off/50)+1}</span><button data-page="1" data-offset-key="${key}" ${off+50>=data.total?'disabled':''}>下一页</button></div>`;}
function pairs(rows){return rows.map(([k,v])=>`<div class="metric-pair"><span>${esc(k)}</span><strong>${v}</strong></div>`).join('');}
function issueList(rows){return rows.length?`<div class="compact-list">${rows.map(r=>`<div class="issue">${link('runs',r.id,r.workspace_title||tr('合同记录已清理'))}<p>${badge(r.status)}　${esc(r.username)} · ${esc(r.model||tr('模型未记录'))}</p></div>`).join('')}</div>`:empty(tr('没有失败或中断记录'),tr('当前筛选范围内的执行摘要未记录此类状态。'));}
function renderOverview(d){const m=d.metrics;return `<div class="stats">${stat(tr('活跃使用人数'),number(m.active_users),tr('提交请求或有原生执行的去重账号'),'users',{active_only:'1'},true)}${stat(tr('正常完成执行'),number(m.states.completed),ui`已结束执行 ${number(m.ended)} 条`,'runs',{status:'completed'})}${stat(tr('新建合同空间'),number(m.new_workspaces),tr('所选期间创建，含最近删除'),'contracts')}${stat(tr('正式产出'),number(m.artifacts),tr('按真实保存的产出 ID 去重'),'contracts',{dataset:'artifacts'})}${stat(tr('Token 消耗'),number(m.tokens),ui`有记录 ${m.token_samples} / ${m.runs} 条执行`,'models')}${stat(tr('执行失败率'),percent(m.failure_rate),ui`${m.states.failed} 次失败 / ${m.ended} 次已结束`,'runs',{status:'failed'})}</div><div class="grid">${card(tr('使用与交付趋势'),trend(d.trend),'wide',tr('每日 · 北京时间'))}${card(tr('执行状态'),bars(Object.entries(m.states).map(([status,count])=>({status,count})))+pairs([[tr('请求入队量'),number(m.queued_requests)],[tr('中断率'),percent(m.interruption_rate)]]),'narrow',tr('原生执行记录'))}${card(tr('近期失败与中断'),issueList(d.issues))}${card(tr('队列与资源'),pairs([[tr('待运行或待处理请求'),number(d.runtime.queue_total)],[tr('暂停队列'),number(d.runtime.paused_total)],[tr('全平台今日试用'),number(d.runtime.platform_quota?.daily_used)+' / '+number(d.runtime.platform_quota?.daily_limit)],[tr('全平台受限并发'),number(d.runtime.platform_quota?.running)+' / '+number(d.runtime.platform_quota?.concurrency_limit)],[tr('下次试用日配额重置'),esc(time(d.runtime.next_quota_reset))]])+bars(d.runtime.sandboxes))}${card(tr('最近执行'),runTable(d.recent),'full',tr('点击合同查看本轮详情'))}${card(tr('当前保留存量'),pairs([[tr('账号'),number(d.stock.users)],[tr('合同空间'),number(d.stock.workspaces)],[tr('文档'),number(d.stock.documents)],[tr('产出'),number(d.stock.artifacts)]]),'full',tr('按账号筛选，不按日期裁剪'))}</div>`;}
function renderUsers(d){return card(state.active_only==='1'?tr('期间活跃账号'):tr('账号与使用'),table([tr('账号'),tr('类型 / 状态'),tr('试用额度'),tr('期间执行'),tr('期间产出'),tr('合同存量'),tr('个人模型配置'),tr('最后观察到的使用')],d.items.map(r=>[
 `${link('users',r.id,r.email||r.username)}<small>${esc(r.username)}</small>`,`${esc(r.account_kind==='demo'?'Demo':tr('个人'))}${r.role==='admin'?tr(' · 管理员'):''}<small>${r.effective_active?tr('可用'):r.cleaned_at?tr('已到期清理'):tr('已停用 / 到期')}</small>`,ui`${number(Math.max(0,r.trial_total-r.trial_used))} / ${number(r.trial_total)}<small>剩余 / 总额度</small>`,number(r.runs),number(r.artifacts),number(r.workspaces),r.configured_providers?ui`${r.configured_providers} 个已启用`:tr('未配置'),esc(time(r.last_observed))]))+pagination(d),'full',tr('使用时间不是注册或登录时间'));}
function renderRuns(d){const m=d.metrics;return `<div class="stats">${stat(tr('执行记录'),number(m.runs),ui`正常完成 ${m.states.completed} · 失败 ${m.states.failed}`,'runs')}${stat(tr('耗时 P50 / P95'),duration(m.duration_p50)+' / '+duration(m.duration_p95),ui`完整耗时样本 ${m.duration_samples} 条`,'runs')}${stat(tr('工具错误'),number(m.tool_errors),tr('可能已被 Agent 恢复，不等于任务失败'),'runs')}</div>`+card(tr('执行明细'),runTable(d.items)+pagination(d),'full',tr('文件数量为对话级关联'));}
function renderContracts(d){if(d.dataset==='artifacts')return card(tr('期间正式产出'),ui`<div class="pill-list"><button data-nav="contracts">查看新建合同</button></div>`+table([tr('产出'),tr('真实类型 / 格式'),tr('合同'),tr('用户'),tr('保存时间')],d.items.map(a=>[link('artifacts',a.id,a.title),esc(labels[a.kind]||a.kind)+' / '+esc(a.format||tr('文件缺失')),link('contracts',a.workspace_id,a.workspace_title),link('users',a.user_id,a.username),esc(time(a.created))]))+pagination(d),'full',tr('按产出保存时间筛选'));return `<div class="grid">${card(tr('期间新建合同'),ui`<div class="pill-list"><button data-nav="contracts" data-extra='${esc(JSON.stringify({dataset:"artifacts"}))}'>查看期间正式产出</button></div>`+table([tr('合同'),tr('用户'),tr('状态'),tr('对话'),tr('材料'),tr('产出'),tr('创建 / 最后业务活动')],d.items.map(r=>[link('contracts',r.id,r.title),link('users',r.user_id,r.username),r.deleted_at?tr('最近删除'):tr('正常'),number(r.threads),number(r.documents),number(r.artifacts),esc(time(r.created))+`<small>${esc(time(r.last_activity_at))}</small>`]))+pagination(d),'full')}${card(tr('风险处置反馈'),d.feedback.length?bars(d.feedback,'decision'):empty(tr('暂无反馈'),tr('尚无当前期间仍有效的最新风险处置反馈。')),'full',tr('最新处置；不代表模型准确率'))}</div>`;}
function renderModels(d){const m=d.metrics;return `<div class="stats">${stat(tr('Token 消耗'),number(m.tokens),ui`${m.token_samples} / ${m.runs} 条执行有记录`,'models')}${stat(tr('已有费用记录'),m.cost==null?tr('未记录'):number(m.cost),ui`${m.cost_samples} / ${m.runs} 条 · 原生费用，非账单`,'models')}${stat(tr('耗时 P95'),duration(m.duration_p95),ui`完整耗时样本 ${m.duration_samples} 条`,'runs')}</div><div class="grid">${card(tr('模型使用'),table([tr('模型'),tr('执行'),'Token',tr('失败率'),tr('耗时 P50'),tr('耗时 P95'),tr('已有费用')],d.items.map(r=>[`<button data-nav="runs" data-extra="${esc(JSON.stringify({model:r.model==='未记录'?'__missing__':r.model}))}">${esc(r.model)}</button>`,number(r.runs),number(r.tokens),percent(r.failure_rate),duration(r.duration_p50),duration(r.duration_p95),r.cost==null?tr('未记录'):number(r.cost)]))+pagination(d),'full',tr('点击模型查看执行明细'))}${card(tr('试用与个人模型请求'),table([tr('模型来源'),tr('额度状态'),tr('请求数'),tr('代理调用')],d.quota.map(r=>[r.platform?tr('平台试用'):tr('个人模型'),badge(r.status),number(r.count),number(r.proxy_calls)])),'full',ui`排除连接探测；UTC 配额下次重置：${time(d.next_quota_reset)}`)}</div>`;}
function renderRuntime(d){return ui`<p class="subtle">全平台今日试用 ${number(d.platform_quota?.daily_used)} / ${number(d.platform_quota?.daily_limit)}，受限运行并发 ${number(d.platform_quota?.running)} / ${number(d.platform_quota?.concurrency_limit)}。额度不受看板筛选影响。</p><div class="grid">${card(tr('当前队列'),table([tr('用户'),tr('请求状态'),tr('阶段'),tr('入队时间')],d.queue.map(r=>[link('users',r.user_id,r.username),badge(r.status),esc(r.stage||tr('未记录')),esc(time(r.created))]))+pagination({total:d.queue_total},'queue_offset'),'wide',tr('当前待运行或待处理请求'))}${card(tr('沙箱状态'),bars(d.sandboxes),'narrow',tr('已保存状态，不唤醒沙箱'))}${card(tr('暂停队列'),d.paused.length?table([tr('用户'),tr('原因')],d.paused.map(r=>[esc(r.username),esc(r.reason)]))+pagination({total:d.paused_total},'paused_offset'):empty(tr('没有暂停队列'),tr('当前快照中未发现暂停队列。')),'full')}${card(tr('沙箱与检查点'),table([tr('合同 / 用户'),tr('状态'),tr('代次'),tr('最近同步'),tr('最后活动')],d.bindings.map(r=>[`${link('contracts',r.id,r.title)}<small>${esc(r.username)}</small>`,badge(r.status),number(r.generation),esc(time(r.synced)),esc(time(r.last_activity))]))+pagination({total:d.bindings_total},'binding_offset'),'full',tr('已保存状态，不进行在线探测'))}${card(tr('运行事件'),table([tr('时间'),tr('用户'),tr('事件'),tr('合同')],d.items.map(r=>[esc(time(r.created)),esc(r.username),esc(r.kind),link('contracts',r.workspace_id,tr('查看合同与诊断'))]))+pagination(d),'full',tr('仅页面可见时每 30 秒刷新'))}</div>`;}
function setDefinitions(meta){$('definitions').innerHTML=ui`<p>${meta.notes.map(note=>esc(tr(note))).join('<br>')}</p><p>记录范围：${esc(time(meta.coverage.first_record))} — ${esc(time(meta.coverage.last_record))}。历史范围不代表连续采集覆盖，首版不显示环比。</p><p>来源：${meta.sources.map(source=>esc(tr(source))).join('、')}。最近快照同步：${esc(time(meta.snapshot_synced))}。</p><p>活跃账号按已接受请求与原生执行去重。失败率分母为正常完成、失败、中断之和。耗时只统计完整结束记录；队列结束不等于执行成功，执行成功不等于保存文件。</p><p>Token 采用已保存原生摘要总量，缓存不二次叠加；费用仅汇总有记录样本，不代表平台账单。风险反馈按最新版本展示；接受风险不代表模型判断正确。</p>`;}
async function load(){
 if(isDetail)return;
 const version=++requestVersion;controller?.abort();controller=new AbortController();
 const sorts=view==='models'?[['runs',tr('执行量')],['tokens','Token'],['duration_p50',tr('耗时 P50')],['failure_rate',tr('失败率')]]:view==='runtime'?[['created',tr('事件时间')]]:view==='runs'?[['created',tr('时间')],['duration',tr('耗时')],['tokens','Token'],['username',tr('用户')]]:[['created',view==='users'?tr('最近使用'):tr('时间')],['username',tr('用户')]];
 $('sort').innerHTML=sorts.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');if(!sorts.some(([v])=>v===state.sort))state.sort=sorts[0][0];$('sort').value=state.sort;$('search').parentElement.hidden=view==='runtime';
 saveURL();$('pageTitle').textContent=titles[view][0];$('pageDescription').textContent=titles[view][1];document.title=titles[view][0]+' · OpenHarvey';
 document.querySelectorAll('[data-view]').forEach(a=>{if(a.dataset.view===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('localFilters').hidden=view==='overview';$('modelFilter').hidden=!['runs','models'].includes(view);$('statusFilter').hidden=!['runs','models'].includes(view);
 $('export').textContent=view==='runtime'?tr('导出事件 CSV'):tr('导出 CSV');$('export').href='/api/ops/export/'+section()+'?'+params();$('content').setAttribute('aria-busy','true');$('refresh').disabled=true;
 try{const data=await api('/api/ops/'+section()+'?'+params(),controller.signal);if(version!==requestVersion)return;
  currentData=data;lastResult={view,start:state.start,end:state.end};$('content').innerHTML=({overview:renderOverview,users:renderUsers,runs:renderRuns,contracts:renderContracts,models:renderModels,runtime:renderRuntime}[view])(data);
  $('notice').hidden=true;$('updateTime').textContent=tr('更新于 ')+time(data.meta.as_of);
  $('scopeNote').textContent=ui`${state.start} — ${state.end} · 北京时间 · 当前保留记录 · 可能包含测试记录${view==='runtime'?tr(' · 队列和沙箱为当前快照，不受日期过滤'):''}${data.meta.snapshot_synced&&Date.now()/1000-data.meta.snapshot_synced>300?tr(' · 历史快照超过 5 分钟未同步（可能为空闲）'):''}`;
  setDefinitions(data.meta);
 }catch(error){if(error.name==='AbortError'||version!==requestVersion)return;$('notice').hidden=false;$('notice').textContent=error.message+(currentData?ui`。当前显示上次成功读取的「${titles[lastResult.view][0]}」，范围 ${lastResult.start} — ${lastResult.end}；筛选尚未应用。`:'');if(!currentData)$('content').innerHTML=empty(tr('数据暂不可用'),error.message);if(currentData&&lastResult)$('pageTitle').textContent=titles[lastResult.view][0]+tr('（上次结果）');if(error.status===401||error.status===403){$('content').innerHTML=empty(tr('无法访问'),error.message);currentData=null;}}
 finally{if(version===requestVersion){$('refresh').disabled=false;$('content').setAttribute('aria-busy','false');}}
}
function detailURL(kind,id){const q=params();q.set('kind',kind);q.set('id',id);q.set('origin_view',view);return '/ops/detail?'+q;}
function detailsGrid(rows){return '<div class="details-grid">'+rows.map(([k,v])=>`<div><small>${esc(k)}</small><strong>${v}</strong></div>`).join('')+'</div>';}
function artifactLinks(rows){return rows.length?'<div class="pill-list">'+rows.map(a=>link('artifacts',a.id,a.title)).join('')+'</div>':empty(tr('没有正式产出'),tr('以真实保存记录为准。'));}
function drawerContent(kind,d){
 if(kind==='runs'){const r=d.run,s=r.summary;return detailsGrid([[tr('执行状态'),badge(s.status)],[tr('模型'),esc(s.model||tr('未记录'))],[tr('耗时'),duration(s.duration)],['Token',number(s.tokens)],[tr('费用'),s.cost==null?tr('未记录'):number(s.cost)],[tr('快照同步'),esc(time(d.synced))]])+ui`<p class="subtle">${esc(d.content_status)}</p><p>${esc(s.prompt||tr('提问摘要未记录'))}</p>${s.error?`<pre>${esc(typeof s.error==='string'?s.error:JSON.stringify(s.error,null,2))}</pre>`:''}<a class="button" href="${esc(detailURL(kind,r.id))}">查看对话与原文 →</a><div class="drawer-section"><h3>同对话正式产出</h3><p class="subtle">${esc(d.artifact_association)}</p>${artifactLinks(d.artifacts)}</div>`;}
 if(kind==='users'){const u=d.user;return detailsGrid([[tr('账号'),esc(u.email||u.username)],[tr('类型'),esc(u.account_kind)],[tr('可用状态'),u.effective_active?tr('可用'):tr('已停用 / 到期')],[tr('试用剩余'),number(Math.max(0,u.trial_total-u.trial_used))],[tr('最近使用'),esc(time(u.last_observed))],[tr('模型配置'),number(u.configured_providers)]])+ui`<div class="drawer-section"><h3>所选期间的使用</h3><button data-nav="runs" data-extra="${esc(JSON.stringify({user_id:u.id,exclude_owner:'0'}))}">查看 ${d.runs.total} 条执行 →</button></div><div class="drawer-section"><h3>所选期间新建合同</h3>${d.contracts.items.map(w=>`<p>${link('contracts',w.id,w.title)}</p>`).join('')||empty()}</div>`;}
 if(kind==='contracts'){const w=d.workspace;return detailsGrid([[tr('合同'),esc(w.title)],[tr('状态'),w.deleted_at?tr('最近删除'):tr('正常')],[tr('创建时间'),esc(time(w.created))],[tr('运行环境'),esc(w.backend)]])+ui`<div class="drawer-section"><h3>原文与附件</h3>${d.documents.map(doc=>`<p>${link('documents',doc.id,doc.filename)}</p>`).join('')||empty()}</div><div class="drawer-section"><h3>正式产出</h3>${artifactLinks(d.artifacts)}</div><a class="button" href="${esc(detailURL(kind,w.id))}">打开原文与产出对照 →</a>${d.sandbox?ui`<details class="drawer-section"><summary>沙箱诊断</summary><pre>${esc(JSON.stringify(d.sandbox,null,2))}</pre></details>`:''}`;}
 return ui`<a class="button" href="${esc(detailURL(kind,kind==='documents'?d.document.id:d.artifact.id))}">打开完整内容 →</a><pre>${esc(kind==='documents'?d.mapping.text:d.report.content)}</pre>`;
}
async function openDrawer(kind,id){
 const version=++detailVersion;$('drawerTitle').textContent=({runs:tr('执行详情'),users:tr('用户详情'),contracts:tr('合同详情'),documents:tr('原文'),artifacts:tr('正式产出')}[kind]||tr('详情'));
 if(!$('drawer').open)$('drawer').showModal();$('drawerBody').innerHTML=tr('<p>正在读取已保存内容…</p>');
 try{const data=await api('/api/ops/'+kind+'/'+encodeURIComponent(id)+'?'+params());if(version!==detailVersion)return;$('drawerBody').innerHTML=drawerContent(kind,data);}catch(error){if(version===detailVersion)$('drawerBody').innerHTML=empty(tr('内容不可用'),error.message);}
}
function citations(text){return esc(text).replace(/【D([a-zA-Z0-9]+):(B\d+)(?:-B\d+)?】/g,(all,did,bid)=>`<button class="citation" data-cite="${did}" data-block="${bid}">${all}</button>`);}
function messageHTML(m){return `<div class="message"><strong>${m.info.role==='user'?tr('用户'):tr('助手')} · ${esc(time((m.info.time?.created||0)/1000))}</strong>${m.parts.map(p=>p.type==='text'?citations(p.text||''):p.type==='tool'?`<details><summary>${esc(p.tool)} · ${esc(labels[p.state?.status]||p.state?.status||'')}</summary><pre>${esc(JSON.stringify(p.state,null,2))}</pre></details>`:esc(p.filename||tr('文件'))).join('\n')}</div>`;}
let readerDocs=[],readerArtifacts=[],readerVersion=0;
async function readDocument(id,block,end,provided){
 const version=++readerVersion;
 try{const d=provided||await api('/api/ops/documents/'+encodeURIComponent(id));if(version!==readerVersion)return;
  const doc=readerDocs.find(x=>x.id===id);if(doc&&doc.source_hash===d.mapping.source_hash)doc.locations=Object.fromEntries((d.mapping.segments||[]).map(s=>[s.id,{page:s.page}]));
  $('documentReader').innerHTML=(d.mapping.segments||[]).map(s=>`<p id="block-${esc(s.id)}"><span class="block-id">${esc(s.citation||s.id)}${s.page!=null?tr(' · 第 ')+esc(s.page)+tr(' 页'):''}</span>${esc(s.text)}</p>`).join('')||empty();
  $('documentSelect').value=id;$('documentDownload').href='/api/ops/documents/'+encodeURIComponent(id)+'/file';$('documentDownload').hidden=false;
  if(block){const el=$('documentReader').querySelector('#block-'+CSS.escape(block));if(el){for(let i=Number(block.slice(1));i<=Number((end||block).slice(1))&&i<=Number(block.slice(1))+100000;i++)$('block-B'+i)?.classList.add('highlight');el.scrollIntoView({block:'center',behavior:'smooth'});}}
 }catch(e){if(version===readerVersion)$('documentReader').innerHTML=empty(tr('原文不可用'),e.message);}
}
let artifactVersion=0;
async function readArtifact(id){const version=++artifactVersion;try{const d=await api('/api/ops/artifacts/'+encodeURIComponent(id));if(version!==artifactVersion)return;const fmt=d.report.format||'md';
 $('artifactReader').innerHTML=['html','svg'].includes(fmt)?ui`<iframe data-artifact-preview="${esc(id)}" title="隔离预览：${esc(d.artifact.title)}" sandbox="allow-scripts" src="/api/ops/artifacts/${encodeURIComponent(id)}/preview"></iframe>`:`<div class="message">${citations(d.report.content||'')}</div>`;
 $('artifactDownloads').innerHTML=d.formats.map(format=>ui`<a class="button" href="/api/ops/artifacts/${encodeURIComponent(id)}/file?format=${encodeURIComponent(format)}">下载 ${esc(format.toUpperCase())}</a>`).join('');
 if(d.artifact.kind==='review')$('artifactReader').insertAdjacentHTML('beforeend',tr('<h3>结构化风险判断</h3><pre>')+esc(JSON.stringify(d.report.findings||[],null,2))+'</pre>');
 }catch(e){if(version===artifactVersion)$('artifactReader').innerHTML=empty(tr('产出不可用'),e.message);}}
async function fullDetail(){
 $('filters').hidden=true;$('localFilters').hidden=true;document.querySelector('.header-actions').hidden=true;$('scopeNote').textContent=tr('只读内容排障 · 查看他人内容会记录访问审计 · 不唤醒沙箱');
 $('pageTitle').textContent=tr('内容排障');$('pageDescription').textContent=tr('对照已保存对话、原文和正式产出。');
 const kind=state.kind,id=state.id;if(!['runs','contracts','documents','artifacts'].includes(kind)||!id){$('content').innerHTML=empty(tr('详情地址无效'));return;}
 try{
  const d=await api('/api/ops/'+kind+'/'+encodeURIComponent(id));
  let wid=kind==='contracts'?d.workspace.id:kind==='runs'?d.workspace_id:kind==='documents'?d.document.workspace_id:d.artifact.workspace_id;
  const w=kind==='contracts'?d:wid?await api('/api/ops/contracts/'+encodeURIComponent(wid)):null;
  readerDocs=w?.documents||[];readerArtifacts=w?.artifacts||[];
  $('content').innerHTML=ui`<div class="full-detail"><a href="/ops?${esc(params())}&view=${esc(state.origin_view||'overview')}">← 返回运营看板</a>${w?`<h2>${esc(w.workspace.title)}</h2>`:''}</div>${kind==='runs'?ui`<section class="card full" style="margin-bottom:16px"><h2>本轮对话</h2><p class="subtle">${esc(d.content_status)} · 同步于 ${esc(time(d.synced))}</p>${d.messages.map(messageHTML).join('')||empty(tr('没有可用快照'),tr('未请求原生运行时，也未恢复沙箱。'))}<details><summary>执行配置快照</summary><pre>${esc(JSON.stringify(d.configuration,null,2))}</pre></details></section>`:''}<div class="content-layout"><section class="card"><h3>原文与附件</h3><div class="reader-toolbar"><select id="documentSelect" aria-label="选择原文">${readerDocs.map(doc=>`<option value="${esc(doc.id)}">${esc(doc.filename)}</option>`).join('')}</select><a id="documentDownload" class="button" hidden>下载原件</a></div><div id="documentReader" class="reader">${empty(tr('没有原文'))}</div></section><section class="card"><h3>正式产出 · 对话级关联</h3><div class="reader-toolbar"><select id="artifactSelect" aria-label="选择产出">${readerArtifacts.map(a=>`<option value="${esc(a.id)}">${esc(a.title)} · ${esc(labels[a.kind]||a.kind)}</option>`).join('')}</select></div><div id="artifactDownloads" class="reader-toolbar"></div><div id="artifactReader" class="reader">${empty(tr('没有正式产出'))}</div></section></div>${w?ui`<details class="drawer-section"><summary>风险反馈历史与合同诊断</summary><pre>${esc(JSON.stringify({feedback:w.artifacts.filter(a=>a.feedback?.length).map(a=>({title:a.title,feedback:a.feedback})),sandbox:w.sandbox},null,2))}</pre></details>`:''}`;
  $('documentSelect').onchange=e=>readDocument(e.target.value);$('artifactSelect').onchange=e=>readArtifact(e.target.value);
  const did=kind==='documents'?id:readerDocs[0]?.id,aid=kind==='artifacts'?id:readerArtifacts[0]?.id;
  if(did)await readDocument(did);if(aid){$('artifactSelect').value=aid;await readArtifact(aid);}
  $('content').setAttribute('aria-busy','false');
 }catch(e){$('content').innerHTML=empty(tr('内容不可用'),e.message);}
}
window.addEventListener('message',async event=>{
 const data=event.data,frames=[...document.querySelectorAll('iframe[data-artifact-preview]')];
 if(event.origin!=='null'||data?.type!=='workbench.citation'||!frames.some(f=>f.contentWindow===event.source&&f.dataset.artifactPreview===data.artifactId))return;
 const doc=readerDocs.find(d=>d.id===data.docid&&d.source_hash===data.hash);if(!doc)return;
 try{const saved=await api('/api/ops/documents/'+encodeURIComponent(doc.id));if(saved.mapping.source_hash!==doc.source_hash)return;doc.locations=Object.fromEntries((saved.mapping.segments||[]).map(s=>[s.id,{page:s.page}]));
 const citation=previewCitation(event,document.querySelectorAll('iframe[data-artifact-preview]'),readerDocs);if(citation)await readDocument(citation.docid,citation.block,citation.end,saved);
 }catch(e){$('notice').hidden=false;$('notice').textContent=e.message;}
});
document.addEventListener('click',event=>{
 const nav=event.target.closest('[data-view]');if(nav){event.preventDefault();if(isDetail){const q=params();q.set('view',nav.dataset.view);location.href='/ops?'+q;}else navigate(nav.dataset.view);return;}
 const target=event.target.closest('[data-nav]');if(target){if($('drawer').open)$('drawer').close();navigate(target.dataset.nav,JSON.parse(target.dataset.extra||'{}'));return;}
 const detail=event.target.closest('[data-detail]');if(detail){openDrawer(detail.dataset.detail,detail.dataset.id);return;}
 const page=event.target.closest('[data-page]');if(page){const key=page.dataset.offsetKey||'offset';state[key]=String(Math.max(0,Number(state[key]||0)+Number(page.dataset.page)*50));load();return;}
 const citation=event.target.closest('[data-cite]');if(citation&&$('documentReader')){if(readerDocs.some(d=>d.id===citation.dataset.cite))readDocument(citation.dataset.cite,citation.dataset.block);else{$('notice').hidden=false;$('notice').textContent=tr('该引用的文档不在当前合同已有材料中。');}}
});
$('drawer').addEventListener('close',()=>{detailVersion++;});$('closeDrawer').onclick=()=>$('drawer').close();
$('refresh').onclick=()=>load();
$('filters').onsubmit=e=>{e.preventDefault();state={...state,start:$('start').value,end:$('end').value,account_kind:$('accountKind').value,user_id:$('userId').value,exclude_owner:$('excludeOwner').checked?'1':'0',offset:'0'};load();};
$('period').onchange=()=>{const value=$('period').value;$('customDates').hidden=value!=='custom';if(value!=='custom'){[state.start,state.end]=dateRange(value==='today'?1:Number(value));restoreInputs();load();}};
$('searchButton').onclick=()=>{Object.assign(state,{q:$('search').value,model:$('model').value,status:$('status').value,sort:$('sort').value,order:$('order').value,offset:'0'});load();};
$('search').onkeydown=e=>{if(e.key==='Enter'){$('searchButton').click();}};
setInterval(()=>{if(view==='runtime'&&!document.hidden&&!isDetail&&!$('drawer').open)load();},30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&view==='runtime'&&!isDetail)load();});
document.addEventListener('ui-language-changed',()=>{if(document.body.dataset.languageReady){if(isDetail)void fullDetail();else void load();}});
async function boot(){try{await accountLanguage(await api('/api/me'));document.body.dataset.languageReady='1';const options=await api('/api/ops/options');$('userId').insertAdjacentHTML('beforeend',options.users.map(u=>`<option value="${esc(u.id)}">${esc(u.username)} · ${esc(u.account_kind)}</option>`).join(''));$('model').insertAdjacentHTML('beforeend',options.models.map(m=>`<option value="${esc(m.model)}">${esc(m.model)}</option>`).join('')+tr('<option value="__missing__">未记录模型</option>'));restoreInputs();if(isDetail)await fullDetail();else await load();}catch(e){$('content').innerHTML=empty(tr('无法访问运营看板'),e.message);$('updateTime').textContent=tr('未读取');}}
boot();
