import {api} from './api.js';
const status=document.getElementById('status'),retry=document.getElementById('startDemo');
let captchaToken='',busy=false,captchaShown=false;
async function openDemo(){
 if(busy)return;busy=true;retry.hidden=true;status.textContent='正在准备独立的试用空间…';
 try{
  await api('/api/demo/start',{method:'POST',body:{captcha_token:captchaToken}});
  status.textContent='正在载入虚构合同示例…';
  const result=await api('/api/demo/workspace',{method:'POST',body:{}});
  location.replace('/agent#'+result.workspace_id);
 }catch(error){
  status.textContent=error.message;retry.hidden=false;
  if(error.status===403&&!captchaShown){
   try{const cfg=await api('/api/auth/config');if(cfg.captcha_site_key){
    captchaShown=true;const script=document.createElement('script');script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.onload=()=>window.turnstile.render('#captcha',{sitekey:cfg.captcha_site_key,callback:token=>{captchaToken=token;void openDemo();},'expired-callback':()=>captchaToken=''});
    script.onerror=()=>{status.textContent='验证组件加载失败，请刷新页面重试。';};document.body.append(script);
   }}catch{}
  }
 }finally{busy=false;}
}
retry.onclick=openDemo;
void openDemo();
