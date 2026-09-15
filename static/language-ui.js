import {getLanguage,setLanguage,t,requestedLanguage} from './i18n.js';

let account=null;
async function saveLanguage(locale){
  const response=await fetch('/api/settings/language',{method:'PUT',credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-Workbench-Request':'1'},body:JSON.stringify({ui_language:locale})});
  const result=await response.json();
  if(!response.ok)throw new Error(result.detail||t('语言设置保存失败，请重试。'));
  account.ui_language=result.ui_language;return result;
}
export async function accountLanguage(me){
  account=me;
  const logout=document.getElementById?.('logout');if(logout)logout.hidden=me.account_kind==='demo';
  // An explicit entry-page choice wins for this visit and becomes the account
  // preference, so the demo, workspace and later navigation remain consistent.
  const entry=requestedLanguage(location.search);
  let chosen=entry||me.ui_language;
  if(entry&&entry!==me.ui_language)await saveLanguage(entry);
  if(!chosen){try{chosen=new URLSearchParams(location.search).get('lang')||localStorage.getItem('workbench-guest-language');}catch{}chosen=chosen==='en'?'en':'zh-CN';if(chosen==='en')await saveLanguage(chosen);}
  setLanguage(chosen);
  if(entry){
    const url=new URL(location.href);url.searchParams.delete('lang');
    history.replaceState(history.state,'',url.pathname+url.search+url.hash);
  }
  mountLanguagePicker();
}
export function mountLanguagePicker(){
  if(typeof document==='undefined')return;
  for(const host of document.querySelectorAll('body > header nav, #spacesApp > header nav, .auth-panel, .header-actions, .demo-opening')){
    if(host.querySelector('[data-language-picker]'))continue;
    const label=document.createElement('label');label.className='language-picker';label.dataset.languagePicker='';
    label.innerHTML='<span aria-hidden="true">文 / A</span><select aria-label="界面语言 / Interface language"><option value="zh-CN">简体中文</option><option value="en">English</option></select><span class="language-error" role="status"></span>';
    host.append(label);const select=label.querySelector('select'),status=label.querySelector('[role=status]');select.value=getLanguage();
    select.onchange=async()=>{
      const old=getLanguage(),next=select.value;select.disabled=true;status.textContent='';
      try{if(account)await saveLanguage(next);setLanguage(next,{guest:!account});}
      catch(error){select.value=old;status.textContent=error.message;}
      finally{select.disabled=false;}
    };
  }
}
document.addEventListener('ui-language-changed',()=>{
  document.querySelectorAll('[data-language-picker] select').forEach(select=>select.value=getLanguage());
});
document.addEventListener('session-expired',()=>{account=null;let guest=requestedLanguage(location.search);try{guest=guest||localStorage.getItem('workbench-ui-language')||localStorage.getItem('workbench-guest-language');}catch{}setLanguage(guest||'zh-CN');});
mountLanguagePicker();
