import {t as tr,ui,getLanguage} from './i18n.js';
import {esc} from './markdown.js';

export function filteredWorkspaces(items,{scope='active',query='',sort='updated'}={}){
  const needle=query.trim().toLocaleLowerCase('zh-CN');
  return items.filter(item=>(scope==='deleted'?!!item.deleted_at:!item.deleted_at)&&
    (scope!=='starred'||!!item.starred)&&(!needle||item.title.toLocaleLowerCase('zh-CN').includes(needle)))
    .sort((a,b)=>sort==='name'?a.title.localeCompare(b.title,'zh-CN'):
      sort==='created'?b.created-a.created:(b.starred-a.starred)||(b.last_activity_at-a.last_activity_at)||(b.created-a.created));
}

const date=value=>new Intl.DateTimeFormat(getLanguage(),{year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value*1000));
const relative=value=>{
  const days=Math.max(0,Math.floor((Date.now()-value*1000)/86400000));
  if(days===0)return tr('今天');if(days===1)return tr('昨天');if(days<30)return ui`${days} 天前`;return date(value);
};

export function workspaceRows(items){
  if(!items.length)return tr('<div class="space-empty"><span aria-hidden="true">⌁</span><h2>这里还没有合同空间</h2><p>上传一份合同，Agent 会为它建立独立的对话与文件空间。</p></div>');
  return items.map(item=>{
    const href=`/agent#${encodeURIComponent(item.id)}`;
    const failed=item.purge_error?`<small class="purge-error">${esc(item.purge_error)}</small>`:'';
    const identity=ui`<span class="document-mark">合</span><span class="space-title"><b>${esc(item.title)}</b><small>${esc(item.id.slice(0,8).toUpperCase())}${failed}</small></span>`;
    return ui`<article class="space-row" data-space-row="${esc(item.id)}">
      <button class="star-button" data-space-action="${item.starred?'unstar':'star'}" data-space-id="${esc(item.id)}" aria-label="${item.starred?tr('取消重点关注'):tr('重点关注')} ${esc(item.title)}" title="${item.starred?tr('取消重点关注'):tr('重点关注')}" ${item.deleted_at?'hidden':''}>${item.starred?'★':'☆'}</button>
      ${item.deleted_at?`<div class="space-main">${identity}</div>`:`<a class="space-main" href="${href}">${identity}</a>`}
      <div class="space-metric"><b>${Number(item.thread_count)||0}</b><span>个会话</span></div>
      <div class="space-metric"><b>${Number(item.artifact_count)||0}</b><span>份产出物</span></div>
      <div class="space-date"><b>${date(item.created)}</b><span>创建</span></div>
      <div class="space-date"><b>${relative(item.last_activity_at||item.created)}</b><span>最近更新</span></div>
      <div class="space-actions">${item.deleted_at?ui`<button data-space-action="restore" data-space-id="${esc(item.id)}" ${item.purging_at?'disabled':''}>恢复</button><button class="delete-space" data-space-action="purge" data-space-id="${esc(item.id)}">${item.purge_error?tr('重试清理'):tr('永久删除')}</button>`:ui`<a href="${href}">查看详情</a><button data-space-action="rename" data-space-id="${esc(item.id)}">重命名</button><button class="delete-space" data-space-action="delete" data-space-id="${esc(item.id)}">删除</button>`}</div>
    </article>`;
  }).join('');
}
