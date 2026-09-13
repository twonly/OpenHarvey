import {esc} from './markdown.js';

export const threadScope=t=>t.deleted_at?'deleted':t.archived_at?'archived':'active';
export const scopeLabels={active:'当前对话',archived:'已归档',deleted:'最近删除'};
export function threadListHTML(threads,selected){
  return threads.map((t,i)=>{
    const scope=threadScope(t);
    const label=({running:'正在运行',waiting:'等待确认或继续',completed:'已完成，尚未查看',failed:'运行未完成'})[t.activity];
    const indicator=label?`<span class="thread-state ${t.activity}" role="img" aria-label="${label}" title="${label}"></span>`:'';
    return `<div class="thread-row"><button class="thread-item ${t.id===selected?'active':''}" data-thread="${esc(t.id)}" title="${esc(t.title)}"><span class="thread-icon">${indicator||'聊'}</span><span class="thread-copy"><b>${esc(t.title)}</b></span></button><details class="thread-menu"><summary aria-label="管理对话 ${esc(t.title)}" title="管理对话">⋯</summary><div class="thread-menu-items"><button data-thread-action="rename" data-tid="${esc(t.id)}">重命名</button><button data-thread-action="up" data-tid="${esc(t.id)}" ${i===0?'disabled':''}>上移</button><button data-thread-action="down" data-tid="${esc(t.id)}" ${i===threads.length-1?'disabled':''}>下移</button>${scope==='active'?`<button data-thread-action="archive" data-tid="${esc(t.id)}">归档</button>`:`<button data-thread-action="restore" data-tid="${esc(t.id)}">${scope==='deleted'&&t.archived_at?'恢复到已归档':'恢复对话'}</button>`}${scope!=='deleted'?`<button class="thread-delete" data-thread-action="delete" data-tid="${esc(t.id)}">删除</button>`:''}</div></details></div>`;
  }).join('')||'<p class="rail-empty">此范围暂无对话</p>';
}
