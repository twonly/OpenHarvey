import {t as tr,ui} from './i18n.js';
import {labels as liveLabels} from './i18n.js';
import {pendingRequest} from './message-queue.js?v=20260912-21';
// Beautiful UI primitives, adapted from React to native HTML and OpenCode data.
// MIT (c) 2026 Shane Levine; see vendor/beautiful-ui/LICENSE and THIRD_PARTY.md.
import {esc} from './markdown.js';
import {isCompaction} from './events.js';

const paths={check:'M20 6L9 17l-5-5',read:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6',write:'M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z',bash:'M4 17l6-5-6-5M12 19h8',skill:'M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z',search:'M21 21l-5-5 M18 10a8 8 0 1 1-16 0a8 8 0 0 1 16 0',chevron:'M6 9l6 6 6-6',close:'M18 6L6 18M6 6l12 12',shield:'M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z'};
export function icon(name){return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.read}"/></svg>`;}
export function ring(active=false,number=''){return `<span class="bui-ring"><svg width="24" height="24" viewBox="0 0 24 24" class="${active?'bui-spin':''}" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="none" stroke="var(--line)" stroke-width="2"/>${active?'<circle cx="12" cy="12" r="11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-dasharray="19.35 49.76"/>':''}</svg><span>${number}</span></span>`;}
export const toolLabels=liveLabels({websearch:'搜索网络',webfetch:'读取网页',read:'读取原文',grep:'搜索材料',glob:'查找文件',skill:'加载 Skill',write:'写入文件',edit:'编辑文件',bash:'处理文件',todowrite:'更新任务清单',question:'等待答复'});
export function toolHTML(p,stopped,open){
  const s=p.state||{},status=stopped&&['pending','running'].includes(s.status)?'interrupted':s.status;
  const label={pending:tr('等待'),running:tr('执行中'),completed:tr('完成'),error:tr('失败'),interrupted:tr('已中断')}[status]||status;
  const glyph={grep:'search',glob:'search',edit:'write',todowrite:'check',question:'skill'}[p.tool]||p.tool;
  const detail=s.detail||(status==='completed'?(p.tool==='question'?tr('已收到你的答复'):tr('操作已完成')):status==='error'||status==='interrupted'?tr('操作未完成'):tr('等待执行结果'));
  const action=p.tool==='question'&&status==='completed'?tr('收到答复'):toolLabels[p.tool]||p.tool;
  return `<details class="tool-action bui-tool" data-key="${esc(p.id)}" ${open.has(p.id)?'open':''}><summary><span class="tool-glyph ${esc(status)}">${icon(glyph)}</span><span class="tool-label">${esc(action)}</span><span class="tool-chip" title="${esc(detail)}">${esc(detail)}</span><span class="tool-status ${esc(status)}">${esc(label)}</span><span class="bui-chevron">${icon('chevron')}</span></summary><div class="tool-detail">${esc(detail)}</div></details>`;
}
export function executionPhase(state){
  if(state.permissions?.length)return {kind:'permission',label:tr('等待你的许可')};
  if(state.questions?.length)return {kind:'question',label:tr('等待你的答复')};
  if(state.status?.type==='retry')return {kind:'retry',label:tr('等待重试'),detail:state.status.message||tr('模型服务暂时不可用')};
  const latest=state.messages?.at(-1);
  if(state.status?.type!=='idle'&&(isCompaction(latest?.info)&&!latest.info.time?.completed||latest?.parts?.some(p=>p.type==='compaction')))return {kind:'compaction',label:tr('正在压缩上下文')};
  if(pendingRequest(state))return {kind:'pending',label:tr('正在准备')};
  if(state.status?.type==='idle'&&!state.queue?.active)return {kind:'idle',label:''};
  const messages=state.messages||[],start=messages.findLastIndex(m=>m.info?.role==='user');
  const turn=messages.slice(start+1).filter(m=>m.info?.role==='assistant');
  const parts=turn.flatMap(m=>m.parts||[]),hasText=parts.some(p=>p.type==='text'&&p.text?.trim());
  const running=parts.findLast(p=>p.type==='tool'&&['pending','running'].includes(p.state?.status));
  if(running)return {kind:'tool',label:toolLabels[running.tool]||tr('正在处理'),hasText};
  const last=turn.at(-1);
  if(last&&!last.info?.time?.completed&&!last.info?.finish&&last.parts?.some(p=>p.type==='text'&&p.text?.trim()))return {kind:'generating',label:tr('正在生成'),hasText};
  return {kind:'processing',label:tr('正在处理'),hasText};
}
export function thinkingHTML(state){
  const phase=executionPhase(state);
  if(!['retry','compaction'].includes(phase.kind)&&(phase.kind!=='processing'||phase.hasText))return '';
  return `<div class="bui-thinking" role="status">${ring(true)}<span><b class="bui-shimmer">${esc(phase.label)}…</b>${phase.detail?`<small>${esc(phase.detail)}</small>`:''}</span></div>`;
}
export function todosHTML(state,expanded){
  const todos=state.todos||[];if(!todos.length)return '';
  const done=todos.filter(t=>t.status==='completed').length;
  // OpenCode retains the previous list across prompts; busy does not make it current.
  if(done===todos.length)return '';
  const active=todos.some(t=>t.status==='in_progress')&&state.status?.type!=='idle';
  return ui`<details class="bui-tasks" ${expanded??active?'open':''}><summary>${icon('check')}<b>任务清单</b><span>${done} / ${todos.length} 项</span><i class="bui-chevron">${icon('chevron')}</i></summary><ol>${todos.map((t,i)=>{
    const status=t.status==='in_progress'&&state.status?.type==='idle'?'interrupted':t.status;
    const label={completed:tr('已完成'),in_progress:tr('进行中'),pending:tr('待处理'),cancelled:tr('已取消'),interrupted:tr('已中断')}[status]||tr('待处理');
    const badge=status==='completed'?`<span class="bui-badge">${icon('check')}</span>`:ring(status==='in_progress',i+1);
    return `<li data-status="${esc(status)}">${badge}<span class="task-copy">${esc(t.content)}</span><span class="task-status ${esc(status)}">${label}</span></li>`;
  }).join('')}</ol></details>`;
}
export function requestsHTML(state){
  return (state.questions||[]).map(q=>ui`<form class="request-card bui-approval" data-question="${esc(q.id)}"><div class="approval-kicker">${icon('skill')}<span>需要你的补充</span></div>${q.questions.map((question,i)=>ui`<fieldset><legend>${esc(question.question)}</legend><div class="approval-options">${question.options.map(o=>`<label><input type="${question.multiple?'checkbox':'radio'}" name="q${i}" value="${esc(o.label)}"><span><b>${esc(o.label)}</b><small>${esc(o.description||'')}</small></span></label>`).join('')}</div><input type="text" name="free${i}" placeholder="也可以直接输入答复…" aria-label="${esc(question.question)}的补充答复"></fieldset>`).join('')}<footer><span>${q.questions.length} 个问题</span><button type="submit" class="approval-confirm">提交并继续 →</button></footer></form>`).join('')+
  (state.permissions||[]).map(p=>ui`<div class="request-card bui-approval"><div class="approval-kicker">${icon('shield')}<span>操作确认</span></div><h3>${esc(p.description||({bash:tr('运行文件处理命令'),edit:tr('修改工作文件'),external_directory:tr('访问工作材料'),read:tr('读取文件')})[p.permission]||tr('执行工具操作'))}</h3><p>允许 Agent 继续这项操作吗？</p><details class="approval-technical"><summary>技术详情</summary><pre class="approval-scope">${esc((p.patterns||[]).join('\n'))}</pre></details><footer><span title="同类允许遵循原生请求给出的匹配范围，仅在当前对话生效">按原生权限范围授权</span><button data-permission="${esc(p.id)}" data-reply="reject">拒绝</button><button data-permission="${esc(p.id)}" data-reply="always" title="同类范围：${esc((p.always||p.patterns||[]).map(x=>x==='*'?tr('当前对话内该类操作，仍遵守禁止规则'):x).join('；'))}">本对话同类允许</button><button class="approval-confirm" data-permission="${esc(p.id)}" data-reply="once">本次允许 ${icon('check')}</button></footer></div>`).join('');
}
export function orderedDocuments(documents){return [...documents.filter(d=>!d.thread_id),...documents.filter(d=>d.thread_id)];}
export function documentTab(d,selected){return `<button class="document-tab ${selected===d.id?'active':''}" data-open-attachment="${esc(d.id)}" aria-pressed="${selected===d.id}" title="${esc(d.filename)}"><span class="file-tag">${d.thread_id?esc(d.suffix?.slice(1).toUpperCase()||tr('文')):tr('主合同')}</span><b>${esc(d.filename)}</b></button>`;}
