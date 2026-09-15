import {t as tr,ui} from './i18n.js';
import {getLanguage} from './i18n.js';
import {mountLanguagePicker} from './language-ui.js';
import {setLoadingStatus} from './loading-ui.js';
import {api} from './api.js';
import {esc} from './markdown.js';
import {startTour,closeTour} from './onboarding.js?v=20260913-header-2';
import {orcaConnectHTML} from './orca-connect.js?v=20260914-settings-1';
export const registerURL='/login?register=1';
export async function signOut(){
 await api('/api/logout',{method:'POST',body:{}});
 sessionStorage.clear();location.replace('/login?lang='+getLanguage());
}

export async function setupAuth(){
 const form=document.getElementById('loginForm');if(!form||form.dataset.authSetup)return;
 const cfg=await api('/api/auth/config');
 form.dataset.authSetup='1';
 const wrapper=document.createElement('div');wrapper.className='account-auth';
 wrapper.innerHTML=ui`<p class="auth-eyebrow">YOUR CONTRACTS, CONNECTED</p><h2>欢迎回来</h2><p class="auth-description">登录，继续你的合同工作。</p><div class="account-actions auth-providers"><button data-provider="github"><img src="/static/brand/github.svg" width="18" height="18" alt=""> GitHub</button><button data-provider="google"><img src="/static/brand/google.svg" width="18" height="18" alt=""> Google</button></div><div class="auth-divider"><span>或使用邮箱</span></div><form id="emailAuth"><label>邮箱地址<input name="email" type="email" autocomplete="email" placeholder="you@company.com" required></label><label>密码<input name="password" type="password" autocomplete="current-password" placeholder="输入你的密码" maxlength="1024" required></label><button class="auth-primary" type="submit">登录工作台 <span aria-hidden="true">↗</span></button></form><p role="status" data-auth-status></p><button type="button" data-auth-mode>没有账号？注册</button><a class="auth-try" href="/demo">先用一份公开招标文件体验 <span aria-hidden="true">→</span></a>`;
 const details=document.createElement('details');details.className='legacy-auth';details.innerHTML=tr('<summary>使用管理员分配的账号</summary>');
 const view=document.getElementById('loginView'),layout=document.createElement('div');layout.className='auth-layout';
 layout.innerHTML=ui`<section class="auth-story"><a class="entry-brand" href="/"><img src="/static/brand/openharvey.svg" width="34" height="34" alt="">OpenHarvey</a><div class="auth-story-copy"><p class="auth-eyebrow">LESS PAPERWORK. MORE CLARITY.</p><h1>每一份合同，<br>都有一个好帮手。</h1><p>从读懂条款到完成审查，<br>让原文、对话和成果，在同一处连接。</p></div><div class="auth-workspace-preview" aria-label="工作区功能示意"><div class="preview-top"><span class="preview-dot"></span>虚构采购服务合同<span>虚构示例 · TXT</span></div><div class="preview-body"><div class="preview-paper"><span>招标文件</span><b>项目需求与技术要求</b><i></i><i></i><i class="marked"></i><i></i><small>原文 · 可定位引用</small></div><div class="preview-conversation"><span class="preview-question">帮我梳理这份文件的重点</span><div class="preview-reply"><img src="/static/brand/openharvey.svg" width="23" height="23" alt=""><div><b>从原文出发，逐条理清</b><span>项目范围 / 商务要求 / 履约安排</span><small>对话与原文，随时对照</small></div></div><div class="preview-output">↗ <span>摘要、报告、修改稿</span><small>统一归档</small></div></div></div></div><div class="auth-story-footer"><span>01 阅读原文</span><span>02 对话协作</span><span>03 保存成果</span></div></section><section class="auth-panel"><a class="auth-back" href="/">← 返回首页</a><div class="auth-form-host"></div><p class="auth-footnote">你的合同、对话与模型配置，集中在自己的空间。</p></section>`;
 view.append(layout);mountLanguagePicker();const host=layout.querySelector('.auth-form-host');host.append(wrapper,details);details.append(form);if(new URLSearchParams(location.search).has('legacy'))details.open=true;
 const status=wrapper.querySelector('[data-auth-status]');let signup=new URLSearchParams(location.search).has('register');
 const emailForm=wrapper.querySelector('#emailAuth'),modeButton=wrapper.querySelector('[data-auth-mode]');
 const renderMode=()=>{wrapper.dataset.signup=String(signup);if(location.pathname==='/login')document.title=(signup?tr('注册'):tr('登录'))+' · OpenHarvey';wrapper.querySelector('h2').textContent=signup?tr('开启你的合同空间'):tr('欢迎回来');wrapper.querySelector('.auth-description').textContent=signup?tr('注册保留试用资料，获得更多次数，连接自己的模型。'):tr('登录，继续你的合同工作。');emailForm.querySelector('button').textContent=signup?tr('注册并保留资料 →'):tr('登录工作台 →');emailForm.password.autocomplete=signup?'new-password':'current-password';emailForm.password.minLength=signup?8:1;modeButton.textContent=signup?tr('已有账号？登录'):tr('没有账号？注册');};
 modeButton.onclick=()=>{signup=!signup;status.textContent='';renderMode();};renderMode();
 const run=fn=>async e=>{const button=e.currentTarget;button.disabled=true;setLoadingStatus(status,tr('正在连接…'),true);try{await fn(e);}catch(error){setLoadingStatus(status,error.message);}finally{button.disabled=false;}};
 const link=new URLSearchParams(location.search).get('link')==='1';
 for(const button of wrapper.querySelectorAll('[data-provider]'))button.onclick=run(async()=>{const value=await api('/api/auth/start',{method:'POST',body:{provider:button.dataset.provider,link}});location.assign(value.auth_url);});
 emailForm.onsubmit=async e=>{e.preventDefault();const f=e.target,button=f.querySelector('button');if(button.disabled)return;button.disabled=true;modeButton.disabled=true;setLoadingStatus(status,tr('正在连接…'),true);try{
  await api('/api/auth/email',{method:'POST',body:{email:f.email.value,password:f.password.value,action:signup?'signup':'login',link}});f.password.value='';location.replace('/spaces');
 }catch(error){setLoadingStatus(status,error.message);}finally{button.disabled=false;modeButton.disabled=false;}};
 if(!cfg.enabled){status.textContent=cfg.demo_enabled?tr('第三方与邮箱登录尚未开放，可先免登录体验。'):tr('第三方与邮箱登录尚未开放，请使用管理员分配的账号。');wrapper.querySelectorAll('button').forEach(b=>b.disabled=true);details.open=true;}
}

export async function exchangeCallback(){
 if(location.pathname!='/auth/callback')return false;
 const params=new URLSearchParams(location.search);
 await api('/api/auth/exchange',{method:'POST',body:{code:params.get('code'),flow:params.get('flow')}});
 location.replace('/spaces');return true;
}

let usageRender=null,usageObserver=null;
export async function accountReady(me,{tour=true}={}){
 document.body.dataset.accountKind=me.account_kind||'personal';
 const header=document.querySelector('body > header, #spacesApp > header'),nav=header?.querySelector('nav');
 document.getElementById('opsEntry')?.remove();
 if(me.capabilities?.ops&&nav){const entry=document.createElement('a');entry.id='opsEntry';entry.href='/ops';entry.textContent=tr('运营看板');nav.append(entry);}
 let bar=document.getElementById('accountUsage');
 if(usageRender)document.removeEventListener('usage-changed',usageRender);
 if(me.role!=='admin'){
  if(!bar){bar=document.createElement('div');bar.id='accountUsage';bar.className='account-usage';document.body.prepend(bar);}
  if(!bar.querySelector('.usage-info'))bar.innerHTML='<div class="usage-info"></div>';
  usageObserver?.disconnect();usageObserver=new ResizeObserver(()=>document.body.style.setProperty('--usage-h',bar.getBoundingClientRect().height+'px'));usageObserver.observe(bar);
  usageRender=async()=>{try{const usage=await api('/api/usage');bar.querySelector('.usage-info').innerHTML=ui`<span class="usage-dot" aria-hidden="true"></span><span>${me.account_kind==='demo'?tr('免登录试用'):tr('平台试用')} · 剩余 <b>${usage.remaining}</b> 次</span>${me.account_kind==='demo'?tr('<span class="usage-resource">新建对话 ')+usage.threads_remaining+tr(' · 上传 ')+usage.uploads_remaining+'</span>':''}${usage.expires_at?tr('<span class="usage-expiry">保留至 ')+esc(new Date(usage.expires_at*1000).toLocaleString(getLanguage()))+'</span>':''}<a href="${me.account_kind==='demo'?registerURL:'/model'}">${me.account_kind==='demo'?tr('注册并保留资料 →'):tr('使用自己的模型 →')}</a>`;}catch{}};
  document.addEventListener('usage-changed',usageRender);await usageRender();
 }else{bar?.remove();document.body.style.setProperty('--usage-h','0px');}
 document.getElementById('registerButton')?.remove();
 if(me.account_kind==='demo'&&nav){const register=document.createElement('a');register.id='registerButton';register.className='register-button';register.href=registerURL;register.textContent=tr('免费注册');nav.append(register);}
 document.getElementById('startTour')?.remove();
 if(me.account_kind==='demo'&&bar){
  const guide=document.createElement('button');guide.id='startTour';guide.className='tour-trigger';guide.textContent=tr('新手引导');bar.append(guide);
  guide.onclick=()=>startTour(me,{force:true});
  if(tour)await startTour(me);
 }else closeTour();
}
document.addEventListener('ui-language-changed',()=>{if(usageRender)void usageRender();void refreshAuthLanguage();});
async function refreshAuthLanguage(){
 const view=document.getElementById('loginView'),layout=view?.querySelector('.auth-layout'),form=document.getElementById('loginForm');
 if(!layout||!form)return;
 const email=layout.querySelector('#emailAuth'),fields=email?{email:email.email.value,password:email.password.value}:null,signup=layout.querySelector('.account-auth')?.dataset.signup==='true';
 view.append(form);layout.remove();delete form.dataset.authSetup;await setupAuth();
 const next=view.querySelector('#emailAuth');if(next&&fields){next.email.value=fields.email;next.password.value=fields.password;}
 if(view.querySelector('.account-auth')?.dataset.signup!==String(signup))view.querySelector('[data-auth-mode]')?.click();
}
document.addEventListener('session-expired',()=>{closeTour();document.getElementById('opsEntry')?.remove();document.getElementById('accountUsage')?.remove();document.getElementById('registerButton')?.remove();document.body.style.setProperty('--usage-h','0px');usageObserver?.disconnect();if(usageRender)document.removeEventListener('usage-changed',usageRender);});

export async function renderUsers(host,notice){
 const users=await api('/api/admin/users'),limits=await api('/api/admin/trial-limits');
 host.innerHTML=ui`<h2>用户与试用额度</h2><p>管理员管理资格和额度；用户的个人配置相互隔离。</p><div class="account-users">${users.map(u=>ui`<form data-user="${esc(u.id)}"><strong>${esc(u.email||u.username)}</strong><span>${u.role==='admin'?tr('平台管理员'):u.account_kind==='demo'?'demo':tr('个人用户')} · 剩余 ${u.trial.remaining} 次</span><label><input name="active" type="checkbox" ${u.active?'checked':''}>启用</label><label>增加额度<input name="add_requests" type="number" min="0" max="10000" value="0"></label><button>保存</button></form>`).join('')}</div><details><summary>平台试用限制</summary><form id="trialLimits">${Object.entries(limits).map(([k,v])=>`<label>${esc(({demo_hours:tr('Demo 保留小时'),demo_threads:tr('Demo 会话数'),demo_requests:tr('Demo 初始请求数'),demo_uploads:tr('Demo 上传数'),upload_mb:tr('单文件 MB'),personal_requests:tr('注册赠送总次数'),user_concurrency:tr('每用户并发'),global_concurrency:tr('全站并发'),global_daily:tr('每日平台请求上限'),personal_daily:tr('每用户每日运行上限'),proxy_calls:tr('每轮模型调用上限')})[k]||k)}<input name="${esc(k)}" type="number" min="1" max="10000" value="${v}"></label>`).join('')}<button class="primary">保存限制</button></form></details>`;
 for(const f of host.querySelectorAll('[data-user]'))f.onsubmit=async e=>{e.preventDefault();const button=f.querySelector('button');if(button.disabled)return;button.disabled=true;try{await api('/api/admin/users/'+f.dataset.user,{method:'PATCH',body:{active:f.elements.active.checked,add_requests:Number(f.elements.add_requests.value)}});await renderUsers(host,notice);}catch(error){notice(error.message);button.disabled=false;}};
 host.querySelector('#trialLimits').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/trial-limits',{method:'PUT',body:Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)]))});notice(tr('试用限制已保存'));}catch(error){notice(error.message);}};
}

export function orcaConnect(host,identity){
 const panel=document.createElement('section');panel.className='orca-connect-panel';
 if(identity.account_kind==='demo')panel.classList.add('model-access-card');
 panel.innerHTML=orcaConnectHTML(identity,registerURL);
 if(identity.account_kind==='demo')panel.querySelector('[data-return-workspace]').onclick=()=>host.closest('#settingsView').querySelector('[data-close]').click();
 host.prepend(panel);
 if(identity.account_kind!=='demo'){
  const mount=()=>{window.OrcaConnect?.mountAll(panel);panel.querySelector('[data-orca-fallback]').hidden=!!panel.querySelector('[data-orca-connect-ready]');};
  if(!document.querySelector('script[data-orca-widget]')){const script=document.createElement('script');script.src='https://api.orcarouter.ai/cdn/orca-connect-v1.js';script.async=true;script.dataset.orcaWidget='1';script.onload=mount;document.body.append(script);}
  else mount();
  panel.querySelector('[data-orca-fallback]').onclick=async()=>{try{const data=await api('/orca/connect-url');location.assign(data.auth_url);}catch(e){panel.querySelector('[role=status]').textContent=e.message;}};
 }
 return identity.account_kind==='demo';
}

document.addEventListener('registration-required',event=>{if(document.getElementById('registrationPrompt'))return;const d=document.createElement('dialog');d.id='registrationPrompt';d.className='account-onboarding';d.setAttribute('aria-labelledby','registrationTitle');d.innerHTML=ui`<h2 id="registrationTitle">继续使用 OpenHarvey</h2><p>${esc(event.detail)}</p><div class="dialog-actions"><button class="oh-button">稍后</button><a class="oh-button primary" href="${document.body.dataset.accountKind==='demo'?registerURL:'/model'}">${document.body.dataset.accountKind==='demo'?tr('注册并保留资料'):tr('配置自己的模型')}</a></div>`;document.body.append(d);d.querySelector('button').onclick=()=>d.close();d.onclose=()=>d.remove();d.showModal();});
