import {esc} from './markdown.js';

export function queueHTML(queue,models=[]){
  const items=queue?.items||[];
  if(!items.length)return '';
  const failed=items.some(i=>i.status==='failed');
  const uncertain=items.some(i=>i.status==='failed'&&i.stage==='submitting');
  const modelName=id=>models.find(m=>m.id===id)?.label||id?.split('/').at(-1)||'';
  const reason=uncertain?'有消息的提交结果尚未确认，请先检查对话，再决定是否重发。':failed?'有消息未能发送，请查看原因并撤回编辑。':'';
  return `<div class="queue-heading"><b>待发送 · ${items.length}</b><span>${queue.paused?'':'依次发送'}</span>${queue.paused&&!failed?`<button type="button" data-queue-resume>发送</button>`:''}</div>${reason?`<p class="queue-reason">${esc(reason)}</p>`:''}<ol>${items.map((item,i)=>`<li><div class="queue-item-copy"><span class="queue-position">${i+1} · ${item.status==='failed'?(item.stage==='submitting'?'提交结果待确认':'未能发送'):queue.paused?'尚未发送':'等待当前任务结束'}</span><small class="queue-model">${esc(item.body.model?'模型：'+modelName(item.body.model):'')}${item.body.skill?' · /'+esc(item.body.skill):''}</small><p>${esc(item.body.text)}</p>${item.error?`<p class="queue-error">${esc(item.error)}</p>`:''}</div><button type="button" data-withdraw-message="${esc(item.id)}">撤回并重新编辑</button></li>`).join('')}</ol>`;
}

export function restoreDraft(recovered,current,saved=[]){
  const key=d=>JSON.stringify([d.text||'',d.skill||null,d.quotes||[],d.model||null,d.risk_scheme||null]);
  const meaningful=d=>d.text?.trim()||d.skill||d.quotes?.length;
  const seen=new Set([key(recovered)]);
  return {draft:recovered,saved:[...saved,current].filter(d=>{
    if(!meaningful(d)||seen.has(key(d)))return false;
    seen.add(key(d));return true;
  })};
}

// Pending delivery is a UI projection of the outbox, never native chat history.
export function pendingRequest(state){
  const current=state.queue?.current;
  const local=state.pendingSend;
  if(state.queue?.paused&&!current&&local?.status!=='sending')return null;
  const item=current||local||(!state.queue?.paused?state.queue?.items?.[0]:null);
  if(!item)return null;
  const mid=item.message_id||(local?.id===item.id?local.message_id:null);
  if(mid&&state.messages?.some(m=>m.info.id===mid&&m.parts?.some(p=>p.type==='text'&&p.text)))return null;
  return item;
}
export function reconcilePending(state){
  const p=state.pendingSend;
  if(!p)return;
  const candidates=[state.queue?.current,...(state.queue?.items||[])].filter(Boolean);
  const c=candidates.find(c=>p.id===c.id||p.request_id===c.request_id);
  if(c){p.id=c.id;p.status=c.status;p.message_id=c.message_id||p.message_id;}
  if(p?.message_id&&state.messages?.some(m=>m.info.id===p.message_id&&m.parts?.some(part=>part.type==='text'&&part.text)))state.pendingSend=null;
  else if(p.id&&state.queue&&!c&&p.status!=='sending')state.pendingSend=null;
}

export function preparationLabel(item){
  const stage=({checking:'检查环境',creating:'创建环境',resuming:'恢复环境',starting:'启动 Agent',syncing:'同步合同和配置',connecting:'建立连接',submitting:'提交请求'})[item?.stage]||'准备环境';
  return `连接 Agent 环境中...(${stage})`;
}

export function loadingStateHTML(label){
  return `<span class="agent-loading"><span class="agent-loading-grid" aria-hidden="true">${Array.from({length:9},(_,i)=>`<i style="--pixel:${[0,1,2,7,8,3,6,5,4][i]}"></i>`).join('')}</span><span class="agent-loading-label">${esc(label)}</span></span>`;
}
