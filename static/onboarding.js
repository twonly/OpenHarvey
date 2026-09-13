import {api} from './api.js';
let active=null,opening=false;
export function closeTour(){active?.close();}
export async function startTour(me,{force=false}={}){
 if(me.account_kind!=='demo'||active||opening)return;opening=true;
 let prefs;try{prefs=await api('/api/settings');}catch{opening=false;return;}
 opening=false;
 const params=new URLSearchParams(location.search),uploadTour=params.get('tour')==='upload';
 if((prefs.effective.onboarding_completed&&!force&&!uploadTour)||params.has('link'))return;
 if(!document.getElementById('appShell')&&!document.getElementById('spacesApp'))return;
 const onAgent=Boolean(document.getElementById('appShell')),isDemo=me.account_kind==='demo';
 const dialog=document.createElement('dialog');dialog.className='workspace-tour';dialog.setAttribute('aria-labelledby','tourTitle');
 dialog.innerHTML='<div class="tour-spotlight" aria-hidden="true"></div><section class="tour-card"><div class="tour-top"><span>快速上手</span><button data-close aria-label="关闭新手引导">×</button></div><ol class="tour-progress" aria-label="引导进度"><li>认识工作区</li><li>上传合同</li><li>注册与模型</li></ol><div class="tour-content"></div><p class="tour-error" role="alert"></p><footer><button data-skip>跳过引导</button><div><button data-prev>上一步</button><button data-next class="auth-primary">下一步 →</button></div></footer></section>';
 const progressKey='workbench-tour:'+me.id;
 let savedStep=0;try{savedStep=Number(sessionStorage.getItem(progressKey))||0;}catch{}
 let step=uploadTour?1:force?0:Math.max(0,Math.min(2,savedStep)),region=0;
 const areas=onAgent?[
  ['对话区','#chatPane','直接提问、选择审查任务，随时追问你的合同助手。'],
  ['合同原文','#docPane','阅读招标文件；点击回答里的引用，可回到对应原文。'],
  ['产出物','#artPane','查看已保存的摘要、审查报告和修改稿，并下载使用。'],
  ['工作区','#workspaceRail','在一份合同下管理多段对话、附件和产出物。']
 ]:[['合同列表','.workspace-card','每份主合同都有独立空间，相关对话、附件和成果集中保存。'],['上传入口','#uploadButton','从这里上传自己的主合同，自动建立一个新的合同空间。']];
 function position(){
  let selector=step===0?areas[region][1]:step===1?(onAgent?'header a[href="/spaces"]':'#uploadButton'):(isDemo?'#registerButton':'#openSettings');
  const target=document.querySelector(selector),ring=dialog.querySelector('.tour-spotlight'),card=dialog.querySelector('.tour-card');
  const rect=target?.getBoundingClientRect();
  ring.hidden=!rect||rect.width===0||rect.height===0||innerWidth<760;
  if(!ring.hidden){Object.assign(ring.style,{left:Math.max(4,rect.left-4)+'px',top:Math.max(4,rect.top-4)+'px',width:Math.min(rect.width+8,innerWidth-8)+'px',height:Math.min(rect.height+8,innerHeight-8)+'px'});}
  card.dataset.side=step===0&&onAgent&&region===0?'right':'left';
 }
 async function finish(){
  const buttons=[...dialog.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  try{const latest=await api('/api/settings');await api('/api/settings',{method:'PUT',body:{values:{...latest.values,onboarding_completed:true},revision:latest.revision}});try{sessionStorage.removeItem(progressKey);}catch{}dialog.close();return true;}
  catch(error){dialog.querySelector('.tour-error').textContent=error.message;return false;}
  finally{buttons.forEach(b=>b.disabled=false);}
 }
 function render(){
  try{sessionStorage.setItem(progressKey,String(step));}catch{}
  dialog.querySelectorAll('.tour-progress li').forEach((el,i)=>{el.dataset.active=String(i===step);el.setAttribute('aria-current',i===step?'step':'false');});
  const content=dialog.querySelector('.tour-content');
  if(step===0)content.innerHTML=`<p class="tour-kicker">第一步 · 看懂工作区</p><h2 id="tourTitle">一份合同，一个完整的工作现场</h2><p>从原文出发，和助手一起完成工作。</p><div class="tour-regions">${areas.map((a,i)=>`<button data-region="${i}" aria-pressed="${i===region}">${a[0]}</button>`).join('')}</div><div class="tour-region-copy"><b>${areas[region][0]}</b><p>${areas[region][2]}</p></div>`;
  if(step===1)content.innerHTML=`<p class="tour-kicker">第二步 · 换成你的合同</p><h2 id="tourTitle">上传，从「合同空间」开始</h2><p>点击顶部的「合同空间」，再选择「上传新合同」。每份主合同都会建立独立空间。</p><div class="tour-upload-path"><span>合同空间</span><i>→</i><span>＋ 上传新合同</span></div><p class="tour-note">支持 PDF、Word、Markdown 和 TXT。补充材料可在对话左侧的「附件」中添加。</p><button class="tour-action" data-upload>${onAgent?'前往合同空间':'选择我的合同'} ↗</button>`;
  if(step===2)content.innerHTML=`<p class="tour-kicker">第三步 · ${isDemo?'留住你的工作成果':'按你的方式工作'}</p><h2 id="tourTitle">${isDemo?'注册，让试用继续':'连接你自己的模型'}</h2><p>${isDemo?'注册后，当前试用的合同与对话会保留在账号中，并获得更多试用次数。':'合同、对话与成果已归属于你的账号，可以随时回来继续。'}</p><div class="tour-benefits"><span>✓ ${isDemo?'保留试用资料':'集中保存资料'}</span><span>✓ ${isDemo?'更多试用次数':'使用平台试用额度'}</span><span>✓ 在设置中配置自己的模型与 API Key</span></div><a class="tour-action" href="${isDemo?'/login?register=1':'/model'}">${isDemo?'免费注册并保留资料':'前往模型设置'} ↗</a>`;
  dialog.querySelector('[data-prev]').hidden=step===0;dialog.querySelector('[data-next]').textContent=step===2?'开始使用 ✓':'下一步 →';
  content.querySelectorAll('[data-region]').forEach(b=>b.onclick=()=>{region=Number(b.dataset.region);render();dialog.querySelector(`[data-region="${region}"]`).focus();});
  content.querySelector('[data-upload]')?.addEventListener('click',()=>{
   try{sessionStorage.setItem(progressKey,'2');}catch{}dialog.close();if(onAgent)location.assign('/spaces?tour=upload');else{document.getElementById('uploadInput').click();}
  });
  const link=content.querySelector('a.tour-action');if(link)link.onclick=async e=>{e.preventDefault();if(await finish())location.assign(link.href);};
  position();
 }
 dialog.querySelector('[data-next]').onclick=()=>{if(step===2)void finish();else{step++;render();}};
 dialog.querySelector('[data-prev]').onclick=()=>{step--;render();};
 dialog.querySelector('[data-skip]').onclick=finish;dialog.querySelector('[data-close]').onclick=finish;
 dialog.oncancel=e=>{e.preventDefault();void finish();};
 dialog.onclose=()=>{window.removeEventListener('resize',position);dialog.remove();active=null;document.getElementById('startTour')?.focus();};
 document.body.append(dialog);active=dialog;dialog.showModal();render();window.addEventListener('resize',position);dialog.querySelector('[data-next]').focus();
 if(uploadTour){params.delete('tour');history.replaceState(null,'',location.pathname+(params.size?'?'+params:'')+location.hash);}
}
