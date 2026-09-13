import {esc} from './markdown.js';

export function accountLabel(me){
  return me.account_kind==='demo'?'访客':me.email||me.username||'我的账户';
}
export function accountIdentityHTML(me){
  const label=esc(accountLabel(me));
  return `<span class="account-identity" title="${label}"><img src="/static/brand/avatar-lucide.svg" width="28" height="28" alt=""><span>${label}</span></span>`;
}
