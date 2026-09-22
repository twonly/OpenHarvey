import {t as tr,ui} from './i18n.js';
import {pendingRequest,preparationLabel,loadingStateHTML} from './message-queue.js?v=20260912-21';
import {esc,markdown,citations} from './markdown.js';
import {visibleMessageIssue,isCompaction,isCompactionContinuation} from './events.js';
import {riskBoard} from './risk-ui.js';
import {memoryReferencesHTML} from './memory-ui.js';
import {toolHTML,thinkingHTML} from './agent-ui.js?v=20260913-2';
import {skillLabel,skillCommand,skillMessage} from './skill-labels.js';

export function welcomeHTML(documents=[]){
  const contract=documents.find(d=>!d.thread_id);
  const suggestions=[[tr('付款条件'),tr('这份合同的付款条件是什么？')],[tr('验收标准'),tr('这份合同约定了哪些验收标准？')],[tr('违约责任'),tr('这份合同的违约责任是如何约定的？')]];
  return ui`<div class="welcome contract-welcome"><h2>这份合同，想先看什么？</h2><p>提炼要点、审查风险，或直接询问具体条款。</p>${contract?ui`<p class="welcome-document" title="${esc(contract.filename)}">当前合同 · ${esc(contract.filename)}</p>`:''}<div class="welcome-examples" aria-label="示例问题"><span>也可以问</span>${suggestions.map(([label,prompt])=>`<button type="button" data-welcome-prompt="${esc(prompt)}">${label}<span aria-hidden="true">↗</span></button>`).join('')}</div><p class="welcome-hint">也可以在右侧圈选条款，带着原文继续讨论。</p></div>`;
}

export function matchingSkills(input,skills=[]){
  const match=input.match(/^\/([^\s]*)$/);
  return match?skills.filter(s=>`${s.name} ${s.label} ${s.description||''}`.toLowerCase().includes(match[1].toLowerCase())):null;
}
function quoteHTML(text,filename,documents){
  return ui`<blockquote class="message-source-quote"><div class="message-quote-source">引用原文 · ${esc(filename||tr('合同原文'))}</div><div class="message-quote-text">${citations(esc(text),documents)}</div></blockquote>`;
}
export function userMessageHTML(text,documents=[],quotes=[],skills=[],explicitSkill=null){
  const name=explicitSkill||skillCommand(text)?.[1];
  const badge=name?ui`<span class="message-skill" title="本条消息指定的 Skill">${esc(skillLabel(name,skills))}</span>`:'';
  const body=skillMessage(text,name,skills);
  // Presentation only: native history retains the original validated quote text.
  const sections=body.split(/\n\n选中原文（([^\n]+)）：\n/);
  let html=badge+`<div class="user-text">${citations(esc(sections[0]),documents)}</div>`;
  for(let i=1;i+1<sections.length;i+=2)html+=quoteHTML(sections[i+1],sections[i],documents);
  if(sections.length===1)for(const q of quotes)html+=quoteHTML(q.text,q.filename||documents.find(d=>d.id===q.document_id)?.filename,documents);
  return html;
}
export function conversationHTML(state,open=new Set()){
  const currentTurn=state.messages.findLastIndex(m=>m.info.role==='user');
  const groups=[];
  for(const [index,m] of state.messages.entries()){
    if(isCompaction(m.info)){
      const stopped=state.status.type==='idle'||index<state.messages.length-1;
      const label=m.info.error?tr('压缩未完成'):m.info.time?.completed&&m.info.finish==='stop'?tr('压缩完成'):stopped?tr('压缩已中断'):tr('正在压缩上下文');
      const key='compaction-'+m.info.id;
      const text=(m.parts||[]).filter(p=>p.type==='text').map(p=>p.text||'').join('\n');
      const issue=visibleMessageIssue(state,index);
      groups.push({role:'process',content:`<details class="compaction-record" data-key="${esc(key)}" ${open.has(key)?'open':''}><summary><span>${tr('上下文压缩')}</span><small>${esc(label)}</small></summary><p class="muted">${tr('用于接续任务的过程记录')}</p><div class="markdown">${markdown(text,state.documents)}</div>${issue?`<p class="chat-error">${esc(issue)}</p>`:''}</details>`});
      continue;
    }
    let content='';
    for(const p of m.parts||[]){
      if(isCompactionContinuation(p))continue;
      if(p.type==='text'&&p.text)content+=m.info.role==='user'?userMessageHTML(p.text,state.documents,[],state.skills):`<div class="markdown" data-text-part="${esc(p.id)}">${markdown(p.text,state.documents)}</div>`;
      if(p.type==='tool'){
        content+=toolHTML(p,state.status.type==='idle'||index<currentTurn,open);
      }
    }
    if(m.info.role==='assistant')content+=memoryReferencesHTML(m.parts||[],open,m.info.id);
    const issue=visibleMessageIssue(state,index);
    if(issue)content+=`<p class="chat-error">${esc(issue)}</p>`;
    else if(index===state.messages.length-1&&m.info.role==='assistant'&&!m.info.time?.completed&&state.status.type==='idle')content+=tr('<p class="muted">这段回复尚未完成。可发送消息继续。</p>');
    if(!content)continue;
    const role=m.info.role==='user'?'user':'assistant',last=groups.at(-1);
    if(role==='assistant'&&last?.role===role)last.content+=content;
    else groups.push({role,content});
  }
  const pending=pendingRequest(state);
  if(pending){
    const label=pending.status==='sending'?tr('正在发送'):pending.status==='failed'?tr('发送未确认，内容已保留'):pending.status==='dispatching'?preparationLabel(pending):pending.status==='submitted'?tr('已提交，等待响应'):tr('已收到，等待执行');
    groups.push({role:'user',content:userMessageHTML(pending.body.text,state.documents,pending.body.quotes||[],state.skills,pending.body.skill)+`<small class="muted">${pending.status==='dispatching'?loadingStateHTML(label):esc(label)}</small>`});
  }
  return groups.map(g=>`<article class="chat-message ${g.role}"><div class="byline">${g.role==='user'?tr('你'):g.role==='process'?tr('执行记录'):tr('合同助手')}</div>${g.content}</article>`).join('')+thinkingHTML(state);
}

export function csvRows(text){
  const rows=[],row=[];let field='',quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}
    else if(c===','&&!quoted){row.push(field);field='';}
    else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);rows.push([...row]);row.length=0;field='';}
    else field+=c;
  }
  if(field||row.length){row.push(field);rows.push(row);}
  return rows;
}

export function artifactHTML(data,documents,threadId){
  const preview=artifactPreview(data,documents,threadId);
  return data.kind==='review'&&data.findings?.length?riskBoard(data,documents)+ui`<details class="report-full"><summary>查看完整报告</summary>${preview}</details>`:preview;
}
function artifactPreview(data,documents,threadId){
  const fmt=data.format||'md';
  if(fmt==='html'||fmt==='svg')return ui`<iframe data-artifact-preview="${esc(data.id)}" class="artifact-frame" title="${esc(data.title)}预览" sandbox="allow-scripts" referrerpolicy="no-referrer" src="/api/artifacts/${encodeURIComponent(data.id)}/preview${threadId?'?thread_id='+encodeURIComponent(threadId):''}"></iframe>`;
  if(fmt==='json')return `<pre class="plain-preview">${esc(JSON.stringify(JSON.parse(data.content),null,2))}</pre>`;
  if(fmt==='csv')return `<div class="markdown"><table>${csvRows(data.content).map((row,i)=>`<tr>${row.map(c=>`<${i?'td':'th'}>${esc(c)}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</table></div>`;
  if(fmt==='txt')return `<pre class="plain-preview">${esc(data.content)}</pre>`;
  return `<div class="markdown">${markdown(data.content,documents)}</div>`;
}
