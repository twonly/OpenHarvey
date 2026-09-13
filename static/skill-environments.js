import {esc} from './markdown.js';
export function skillEnvironmentsHTML(rows){
 const labels={applied:'已生效',waiting:'已保存，当前任务结束后生效',on_start:'已保存，环境下次启动时生效',syncing:'已保存，正在同步',failed:'已保存，环境更新失败'};
 if(!rows.length)return '<p class="settings-note">已保存的 Skills 会在合同运行环境启动时应用。</p>';
 return '<h3>合同环境生效状态</h3>'+rows.map(r=>`<div class="settings-note"><b>${esc(r.title)}</b> · ${esc(labels[r.status]||r.status)}${r.error?`<p>${esc(r.error)}</p>`:''}</div>`).join('')+(rows.some(r=>r.status==='failed')?'<button type="button" data-retry-skills>重试环境更新</button>':'');
}
