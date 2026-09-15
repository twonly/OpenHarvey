import {t as tr,ui} from './i18n.js';
import {labels as liveLabels} from './i18n.js';
import {esc} from './markdown.js';

export const threadTitle=title=>title==='新对话'?tr('新对话'):title;
export const threadScope=t=>t.deleted_at?'deleted':t.archived_at?'archived':'active';
export const scopeLabels=liveLabels({active:'当前对话',archived:'已归档',deleted:'最近删除'});
export function threadListHTML(threads,selected){
  return threads.map((t,i)=>{
    const scope=threadScope(t);
    const label=({running:tr('正在运行'),waiting:tr('等待确认或继续'),completed:tr('已完成，尚未查看'),failed:tr('运行未完成')})[t.activity];
    const indicator=label?`<span class="thread-state ${t.activity}" role="img" aria-label="${label}" title="${label}"></span>`:'';
    return ui`<div class="thread-row"><button class="thread-item ${t.id===selected?'active':''}" data-thread="${esc(t.id)}" title="${esc(threadTitle(t.title))}"><span class="thread-icon">${indicator||tr('聊')}</span><span class="thread-copy"><b>${esc(threadTitle(t.title))}</b></span></button><details class="thread-menu"><summary aria-label="管理对话 ${esc(threadTitle(t.title))}" title="管理对话">⋯</summary><div class="thread-menu-items"><button data-thread-action="rename" data-tid="${esc(t.id)}">重命名</button><button data-thread-action="up" data-tid="${esc(t.id)}" ${i===0?'disabled':''}>上移</button><button data-thread-action="down" data-tid="${esc(t.id)}" ${i===threads.length-1?'disabled':''}>下移</button>${scope==='active'?ui`<button data-thread-action="archive" data-tid="${esc(t.id)}">归档</button>`:`<button data-thread-action="restore" data-tid="${esc(t.id)}">${scope==='deleted'&&t.archived_at?tr('恢复到已归档'):tr('恢复对话')}</button>`}${scope!=='deleted'?ui`<button class="thread-delete" data-thread-action="delete" data-tid="${esc(t.id)}">删除</button>`:''}</div></details></div>`;
  }).join('')||tr('<p class="rail-empty">此范围暂无对话</p>');
}
