import {esc} from './markdown.js';

export function groupVersions(versions){
  const groups=[];
  for(const version of versions){
    const group=groups.at(-1),previous=group?.at(-1),latest=group?.[0];
    const sameDay=previous&&new Date(previous.created*1000).toDateString()===new Date(version.created*1000).toDateString();
    const join=previous&&!previous.label&&!version.label&&['edit','review'].includes(version.kind)&&previous.kind===version.kind
      &&version.actor_id&&version.actor_id===previous.actor_id&&version.thread_id&&version.thread_id===previous.thread_id
      &&previous.parent_id===version.id&&sameDay&&previous.created-version.created<=120&&latest.created-version.created<=600;
    if(join)group.push(version);else groups.push([version]);
  }
  return groups;
}
export function groupTitle(group){
  if(group.length===1)return group[0].label||group[0].summary;
  if(group[0].kind==='review'){
    const counts=group.reduce((a,v)=>({accept:a.accept+(v.details?.accept||0),reject:a.reject+(v.details?.reject||0)}),{accept:0,reject:0});
    return [counts.accept?`接受 ${counts.accept} 处修订`:'',counts.reject?`拒绝 ${counts.reject} 处修订`:''].filter(Boolean).join('，')||'完成一轮审阅';
  }
  return '连续编辑合同';
}
export function versionHistoryHTML(versions,{current,preview,fileURL,important=false,limit=20}){
  const groups=groupVersions(versions).filter(g=>!important||g[0].label);
  const actions=v=>`<div class="redline-version-actions"><button data-r-preview="${esc(v.id)}">${preview===v.id?'正在查看':'查看'}</button><a href="${esc(fileURL(v.id))}" download>下载 DOCX</a><details><summary>更多</summary><div><button data-r-name="${esc(v.id)}">${v.label?'重命名':'标记为重要版本'}</button>${v.label?`<button data-r-unmark="${esc(v.id)}" data-label-revision="${v.label_revision}">取消重要标记</button>`:''}<button data-r-restore="${esc(v.id)}" ${v.id===current?'disabled':''}>恢复为当前工作稿</button></div></details></div>`;
  const stamp=v=>`${esc(v.kind==='agent'?'Agent':v.author)} · ${esc(new Date(v.created*1000).toLocaleString())}`;
  const badge=v=>(v.id===current?'<span class="redline-version-badge">当前</span>':'')+(v.id===preview?'<span class="redline-version-badge">正在查看</span>':'');
  const card=v=>`<article class="redline-version" data-version-id="${esc(v.id)}"><strong>${v.label?'★ ':''}${esc(v.label||v.summary)}</strong>${badge(v)}<p>${stamp(v)}</p>${v.label?`<p class="redline-version-description">${esc(v.summary)}</p>`:''}${actions(v)}</article>`;
  return `<div class="redline-history-head"><p>每次保存均保留，可展开查看和恢复。</p><button data-r-action="mark-version">标记${preview?'所看版本':'当前工作稿'}</button><div class="redline-history-filter"><button data-r-history="all" aria-pressed="${!important}">全部记录</button><button data-r-history="important" aria-pressed="${important}">重要版本</button></div></div>`+
    (groups.slice(0,limit).map(g=>g.length===1?card(g[0]):`<section class="redline-version-group"><article class="redline-version" data-version-id="${esc(g[0].id)}"><strong>${esc(groupTitle(g))}</strong>${badge(g[0])}<p>${stamp(g[0])}</p>${actions(g[0])}</article><details class="redline-version-saves" ${g.some(v=>v.id===preview)?'open':''}><summary>展开 ${g.length} 条保存记录</summary>${g.map(card).join('')}</details></section>`).join('')||`<p class="redline-empty">${important?'还没有重要版本。可标记当前工作稿，或从历史记录中选择。':'暂无保存记录。'}</p>`)+
    (groups.length>limit?'<button data-r-action="more-versions">显示更多记录</button>':'');
}
