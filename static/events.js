import {t as tr} from './i18n.js';
export function unchangedEvent(state,event){
  const field=event.type==='session.status'?'status':event.type==='todo.updated'?'todos':null;
  return !!field&&JSON.stringify(state[field])===JSON.stringify(event.properties?.[field]);
}

export function isCompaction(info){return info?.summary===true||info?.mode==='compaction'||info?.agent==='compaction';}
export function isCompactionContinuation(part){
  return part?.type==='text'&&part.synthetic===true&&(part.metadata?.compaction_continue===true||part.text?.endsWith('Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.'));
}
// UI projections only: native messages/status remain authoritative on reconnect.
export function errorText(error){
  if(error?.name==='MessageAbortedError')return tr('本次运行已停止，可以继续对话。');
  return error?.data?.message||error?.name||tr('本次运行未完成');
}
export function messageIssue(info){
  if(info?.error)return errorText(info.error);
  if(info?.finish==='length')return tr('模型已达到本次输出上限，任务尚未完成。可以发送“继续”接着处理。');
  if(info?.finish==='content-filter')return tr('模型服务未返回完整答复。');
  return null;
}
export function visibleMessageIssue(state,index){
  const info=state.messages?.[index]?.info;
  // A per-call token limit is actionable only after the native run stops.
  if(info?.finish==='length'&&!info.error&&(state.status?.type!=='idle'||index!==state.messages.length-1))return null;
  return messageIssue(info);
}
export function runIssue(state){
  const last=state.messages?.at(-1)?.info;
  return visibleMessageIssue(state,(state.messages?.length||0)-1)||(state.status?.type==='idle'&&last?.role==='assistant'&&!last.time?.completed
    ?tr('上次运行已中断，可以发送消息继续。'):null);
}
export function applyEvent(state,event){
  const p=event.properties||{};
  if(event.type==='session.updated'){state.title=p.info.title;}
  else if(event.type==='workbench.queue'){state.queue=p.queue;}
  else if(event.type==='message.updated'){
    const found=state.messages.find(m=>m.info.id===p.info.id);
    if(found) found.info=p.info; else state.messages.push({info:p.info,parts:[]});
  } else if(event.type==='message.part.updated'){
    const part=p.part;
    let m=state.messages.find(m=>m.info.id===part.messageID);
    if(!m){m={info:{id:part.messageID,role:'assistant'},parts:[]};state.messages.push(m);}
    const i=m.parts.findIndex(x=>x.id===part.id);
    if(i>=0)m.parts[i]=part;else m.parts.push(part);
  } else if(event.type==='message.part.delta'){
    const part=state.messages.find(m=>m.info.id===p.messageID)?.parts.find(x=>x.id===p.partID);
    if(part?.type==='text' && p.field==='text')part.text=(part.text||'')+p.delta;
  } else if(event.type==='session.status')state.status=p.status;
  else if(event.type==='todo.updated')state.todos=p.todos;
  else if(event.type==='session.error')state.error=errorText(p.error);
  else if(event.type==='question.asked')state.questions=[...(state.questions||[]).filter(q=>q.id!==p.id),p];
  else if(event.type==='permission.asked')state.permissions=[...(state.permissions||[]).filter(q=>q.id!==p.id),p];
  else if(event.type==='question.replied'||event.type==='question.rejected')state.questions=(state.questions||[]).filter(q=>q.id!==p.requestID);
  else if(event.type==='permission.replied')state.permissions=(state.permissions||[]).filter(q=>q.id!==p.requestID);
}

export function connectEvents(tid,onEvent,onReconnect,onDisconnect){
  const stream=new EventSource(`/api/threads/${tid}/events`);
  let disconnected=null,closed=false,interrupted=false,reported=false;
  const reportDisconnect=()=>{interrupted=true;if(disconnected===null&&!closed&&!reported)disconnected=setTimeout(()=>{disconnected=null;if(!closed){reported=true;onDisconnect();}},5000);};
  stream.onmessage=e=>{
    if(closed)return;
    const event=JSON.parse(e.data);
    if(event.type==='workbench.disconnected'){reportDisconnect();return;}
    clearTimeout(disconnected);disconnected=null;
    const recovering=interrupted;
    interrupted=false;reported=false;
    if(recovering)onReconnect();
    if(!['workbench.connected','workbench.heartbeat'].includes(event.type))onEvent(event);
  };
  stream.onerror=reportDisconnect;
  return ()=>{closed=true;clearTimeout(disconnected);stream.close();};
}
