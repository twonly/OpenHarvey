import {api} from './api.js';
import {esc} from './markdown.js';

export const feishuStatusLabels={not_configured:'尚未配置',configured:'等待授权',connected:'已连接',reauthorize:'需要重新授权'};
export function feishuResultText(result){
  const doc=result?.data?.document;
  return typeof doc?.content==='string'?doc.content:'';
}
export function feishuDocumentURL(value){
  try{const url=new URL(value);return url.protocol==='https:'&&url.hostname.endsWith('.feishu.cn')&&!url.username&&!url.password?url.href:null;}catch{return null;}
}
export async function renderConnectors(root,{notice,dirty,isCurrent=()=>true}){
  let state;
  try{state=await api('/api/connectors/feishu');}
  catch(error){if(isCurrent())root.innerHTML=`<h2>连接器</h2><p class="settings-empty">${esc(error.message)}</p>`;return;}
  if(!isCurrent())return;
  if(!document.getElementById('connectorsCSS')){
    const link=document.createElement('link');link.id='connectorsCSS';link.rel='stylesheet';link.href='/static/connectors-ui.css';document.head.append(link);
  }
  const linked=state.status==='connected',configured=state.app_configured,direct=state.transport==='direct_cli';
  const missingScopes=(state.scopes||[]).filter(scope=>!(state.granted_scopes||[]).includes(scope));
  const environmentLabels={not_created:'尚未创建',paused:'已暂停，下次使用时自动准备',ready:'正在准备凭证',starting:'正在启动',syncing:'正在同步',creating:'正在创建',killed:'已销毁，下次使用时重建',lost:'下次使用时恢复环境'};
  const ready=state.environments?.some(e=>e.credential_state==='ready'),verified=state.verification?.read&&state.verification?.write;
  const params=new URLSearchParams(location.search),outcome=params.get('feishu');
  const outcomeText={connected:'飞书授权成功。现在可以验证身份，再试读一份文档。',denied:'你取消了本次授权，可以准备好后再连接。',failed:'授权未完成。请核对应用密钥、回调地址、可用范围及权限发布状态后重新授权。'}[outcome]||'';
  if(outcome){history.replaceState(null,'',location.pathname);}
  root.innerHTML=`<div class="settings-heading"><div><h2>连接器</h2><p>让助手使用你在企业系统中有权访问的资料。</p></div><span class="settings-tag">${state.local_preview?'本地预览':'企业连接'}</span></div>
  <article class="feishu-card">
    <header class="feishu-header"><div class="feishu-icon" aria-hidden="true">↗</div><div><h3>飞书 / Lark</h3><p>查找文档 · 读取知识库 · 结合业务资料回答</p></div><span class="feishu-status ${linked?'connected':''}" role="status">${feishuStatusLabels[state.status]||'连接异常'}</span></header>
    <p class="feishu-intro">连接你的飞书账号，把公司制度、产品资料和项目文档带入工作台。${direct?'支持飞书 / Lark 文档、知识库和多维表格的读取与明确指定的写入，也可搜索联系人、按你的指令以你的身份发送消息。':'本期支持云文档和知识库中的文档读取。'}</p>
    ${outcomeText?`<p class="feishu-feedback" role="status">${outcomeText}</p>`:''}
    ${direct?`<ol class="feishu-steps" aria-label="直连接入进度"><li class="${linked?'done':''}"><b>1</b>飞书账号${linked?'已授权':'等待授权'}</li><li class="${ready?'done':''}"><b>2</b>E2B 凭证${ready?'已就绪':'待准备'}</li><li class="${verified?'done':''}"><b>3</b>实际读写${verified?'已验证':'待验证'}</li></ol><p class="settings-note">${(state.environments||[]).map(e=>esc(e.title)+'：'+(e.credential_state==='ready'?'凭证已就绪':esc(e.error||environmentLabels[e.sandbox_state]||'等待准备'))).join('；')||'在合同空间发起任务时自动准备 E2B 连接。'}</p><a href="/spaces">打开合同空间 →</a><button data-refresh-direct>刷新验证状态</button>${state.last_call?`<p class="settings-note">最近${state.last_call.kind==='write'?'写入':'读取'}：${state.last_call.outcome==='success'?'成功':'失败或结果待核对'} · ${new Date(state.last_call.created*1000).toLocaleString()} · CLI ${(state.last_call.duration_ms/1000).toFixed(2)} 秒</p>`:''}`:`<ol class="feishu-steps" aria-label="接入进度"><li class="${configured?'done':''}"><b>1</b>配置应用</li><li class="${linked?'done':''}"><b>2</b>授权账号</li><li class="${state.tested_at?'done':''}"><b>3</b>验证并试读</li></ol>`}
    <section class="feishu-quick"><h4>用飞书网页完成连接</h4><p>首次使用会引导你在飞书创建应用，再授权账号。凭证由官方 CLI 自动保存，无需复制密钥或填写回调地址。企业的应用创建和权限审批要求仍然适用。${direct?'此连接会申请文档读写、多维表格、以你的身份发送消息和通讯录搜索权限。':''}</p><label>平台 <select id="feishuBrand" ${configured?'disabled':''}><option value="feishu" ${state.brand==='feishu'?'selected':''}>飞书</option><option value="lark" ${state.brand==='lark'?'selected':''}>Lark（国际版）</option></select></label> <button data-quick class="primary" ${state.cli_available?'':'disabled'}>${linked?'重新连接飞书':'连接飞书'}</button>${direct&&linked&&missingScopes.length?`<p class="feishu-feedback">有新增权限尚未授权。点击「重新连接飞书」补充授权，已有应用会继续使用。</p><details><summary>查看待授权权限</summary><code>${esc(missingScopes.join('\n'))}</code></details>`:''}<div id="feishuQuickProgress" aria-live="polite"></div></section>
    <details class="feishu-setup" ${direct?'hidden':''}><summary>高级设置 · 使用已有企业应用</summary>
      <p>企业管理员先在<a href="https://open.feishu.cn/app" target="_blank" rel="noopener noreferrer">飞书开放平台 ↗</a>创建企业自建应用。当前本地版按工作台账号保存配置。</p>
      <div class="feishu-guide-grid"><section><h4>① 获取应用凭证</h4><p>打开应用的「凭证与基础信息」，把 App ID 和 App Secret 填入下方。密钥仅在服务端加密保存。</p></section>
      <section><h4>② 开通用户权限并发布</h4><p>在「权限管理」中选择<strong>用户身份</strong>，开通下列权限；设置应用可用范围包含自己，再创建版本并发布。若需企业审批，请由管理员处理。</p><code id="feishuScopes">${esc(state.scopes.join('\n'))}</code><button type="button" data-copy="scopes">复制权限列表</button></section>
      <section><h4>③ 配置回调地址</h4><p>在「安全设置」的重定向 URL 中完整添加下方地址。授权期间保持本地工作台运行，使用相同地址打开本页。</p><code id="feishuCallback">${esc(state.redirect_uri)}</code><button type="button" data-copy="callback">复制回调地址</button></section></div>
      <form id="feishuConfig" class="settings-form"><div class="settings-fields"><label>App ID<input name="app_id" value="${esc(state.app_id)}" placeholder="cli_…" required maxlength="104" autocomplete="off"></label><label>App Secret<input name="app_secret" type="password" placeholder="${state.secret_configured?'已保存；留空保留现有密钥':'请输入应用密钥'}" ${state.secret_configured?'':'required'} maxlength="2048" autocomplete="new-password"></label></div><div class="settings-form-actions"><button type="submit" class="primary">保存应用配置</button><span class="settings-note">更换凭证后需重新授权。</span></div></form>
    </details>
    <section class="feishu-account"><div><h4>${linked?'已授权的飞书账号':'连接你的飞书账号'}</h4><p>${linked?esc(state.identity?.name||'飞书用户'):'授权后，按你在飞书中的权限读取资料。应用权限、用户授权和文档访问权都需要满足。'}</p>${linked?`<small>已授予 ${state.granted_scopes.length} 项权限 · ${state.tested_at?'最近验证 '+new Date(state.tested_at*1000).toLocaleString():'身份尚未重新验证'}</small>`:''}</div><div class="feishu-actions"><button data-authorize ${state.mode==='manual'?'':'hidden'} ${state.secret_configured?'':'disabled'}>${linked?'重新授权已有应用':'授权已有应用'}</button>${linked?'<button data-disconnect>断开连接</button>':''}</div></section>
    ${linked?`<details class="feishu-grants"><summary>查看实际授权范围</summary><code>${esc(state.granted_scopes.join('\n')||'飞书未返回权限列表')}</code><p>断开连接会清除本地保存的用户授权，并阻止后续调用。要撤销飞书端授权，请到飞书的应用授权管理中取消。已生成的工作台内容仍会保留。</p></details>`:''}
    <section class="feishu-test"><h4>验证连接</h4><p>${direct?'此按钮只验证飞书账号。实际读写请在 E2B 测试合同空间中让助手执行，结果由真实 CLI 调用记录更新。':'先验证当前身份，再搜索或粘贴一份你有权限的飞书文档。身份验证成功不代表所有文档均可读取。'}</p><button data-test ${linked?'':'disabled'}>验证飞书身份</button><p id="feishuTestStatus" role="status"></p>
      ${!state.cli_available?'<p class="feishu-feedback">本地尚未找到飞书 CLI。请由本地维护者运行 <code>npx @larksuite/cli@latest install</code>，完成后刷新此页。</p>':''}
      <form id="feishuRead" ${direct?'hidden':''}><label for="feishuQuery">文档链接或搜索词</label><div class="feishu-search-row"><input id="feishuQuery" name="query" placeholder="粘贴飞书文档链接，或搜索“渠道政策”" required maxlength="2000" ${linked&&state.cli_available?'':'disabled'}><button type="submit" ${linked&&state.cli_available?'':'disabled'}>试读资料</button></div></form><div id="feishuResult" aria-live="polite"></div>
    </section>
    <section class="feishu-examples"><h4>连接后，可以这样问助手</h4><ul><li>在飞书里查找渠道销售政策，列出相关文档及来源。</li><li>读取这份飞书文档，总结与当前合同有关的要求。</li></ul><p class="settings-note">${direct?'当前为 E2B 直连测试：助手使用官方 CLI，业务请求直接访问飞书。控制端负责授权与续期；界面不接收访问令牌。':'当前工具接入本地 Agent。云端沙箱尚未接入本地连接器。图片、附件及嵌入的电子表格不包含在本期读取范围中。'}</p></section>
    <details class="feishu-help"><summary>遇到问题？查看接入方式与排查说明</summary><dl><dt>为什么需要企业自建应用？</dt><dd>当前版本通过企业应用获取你的授权。应用创建、权限开通与发布可能需要企业管理员参与。</dd><dt>回调地址错误</dt><dd>请逐字核对安全设置中的 URL，包括 http、端口和路径。localhost 与 127.0.0.1 应保持一致。</dd><dt>授权成功但读不到文档</dt><dd>确认授权的是正确飞书身份、文档可访问，且应用已发布相应用户权限。搜索没有结果不代表企业里没有这份资料。</dd><dt>官方有哪些接入方式？</dt><dd><a href="https://github.com/larksuite/cli" target="_blank" rel="noopener noreferrer">飞书 CLI</a>提供业务命令和用户授权；<a href="https://github.com/larksuite/lark-openapi-mcp" target="_blank" rel="noopener noreferrer">OpenAPI MCP</a>把 API 提供给 Agent；远程 MCP 还有专门的接入方案。本地版复用官方 CLI，通过工作台管理账号授权和工具接入。</dd></dl></details>
  </article>`;
  const $=s=>root.querySelector(s);
  const busy=fn=>async e=>{
    e.preventDefault();const button=e.submitter||e.currentTarget;button.disabled=true;
    try{await fn(e);}catch(error){if(isCurrent()){notice(error.message);$('#feishuTestStatus').textContent=error.message;}}
    finally{if(button.isConnected)button.disabled=false;}
  };
  $('[data-refresh-direct]')?.addEventListener('click',busy(async()=>{await renderConnectors(root,{notice,dirty,isCurrent});}));
  const flowActive=flow=>['starting','application','authorization'].includes(flow?.step);
  let lastFlow;
  function showFlow(flow){
    const signature=JSON.stringify(flow);if(signature===lastFlow)return;lastFlow=signature;
    const active=flowActive(flow);
    $('[data-quick]').disabled=active||!state.cli_available;
    $('#feishuQuickProgress').innerHTML=flow?.message?`<p class="feishu-feedback" role="status">${esc(flow.message)}</p>${flow.url?`<p><a class="primary" href="${esc(flow.url)}" target="_blank" rel="noopener noreferrer">${flow.step==='application'?'打开飞书创建应用':'打开飞书授权账号'} ↗</a></p>${flow.qr?'<img class="feishu-qr" src="/api/connectors/feishu/qr" alt="飞书官方配置与授权二维码">':''}<p class="settings-note">完成后返回此页，状态会自动更新。</p>`:''}${active?'<button data-cancel-quick>取消本次连接</button>':''}`:'';
    $('[data-cancel-quick]')?.addEventListener('click',busy(async()=>{await api('/api/connectors/feishu/quick',{method:'DELETE'});await renderConnectors(root,{notice,dirty,isCurrent});}));
  }
  async function pollFlow(){
    if(!isCurrent()||!root.contains($('#feishuQuickProgress')))return;
    try{
      const latest=await api('/api/connectors/feishu');
      if(!isCurrent())return;
      showFlow(latest.flow);
      if(latest.flow?.step==='done'){await renderConnectors(root,{notice,dirty,isCurrent});return;}
      if(flowActive(latest.flow))setTimeout(pollFlow,2000);
    }catch(error){if(isCurrent())$('#feishuQuickProgress').textContent=error.message+' 刷新页面可继续查看连接进度。';}
  }
  showFlow(state.flow);
  if(flowActive(state.flow))setTimeout(pollFlow,2000);
  $('[data-quick]').onclick=async e=>{
    e.currentTarget.disabled=true;
    try{const flow=await api('/api/connectors/feishu/quick',{method:'POST',body:{brand:$('#feishuBrand').value}});if(isCurrent()){showFlow(flow);setTimeout(pollFlow,500);}}
    catch(error){notice(error.message);e.currentTarget.disabled=false;}
  };
  $('#feishuConfig').oninput=()=>{dirty(true);$('[data-authorize]').disabled=true;$('[data-authorize]').textContent='请先保存应用配置';};
  $('#feishuConfig').onsubmit=busy(async e=>{const values=Object.fromEntries(new FormData(e.target));await api('/api/connectors/feishu',{method:'PUT',body:{...values,revision:state.revision}});dirty(false);notice('飞书应用配置已保存，请继续授权。');await renderConnectors(root,{notice,dirty,isCurrent});});
  $('[data-authorize]').onclick=busy(async()=>{const result=await api('/api/connectors/feishu/authorize',{method:'POST',body:{}});dirty(false);location.assign(result.authorization_url);});
  $('[data-disconnect]')?.addEventListener('click',busy(async()=>{await api('/api/connectors/feishu',{method:'DELETE'});dirty(false);notice('已断开飞书连接。');await renderConnectors(root,{notice,dirty,isCurrent});}));
  $('[data-test]').onclick=busy(async()=>{const result=await api('/api/connectors/feishu/test',{method:'POST',body:{}});if(isCurrent())$('#feishuTestStatus').textContent=`身份验证成功：${result.identity?.name||'飞书用户'}。可以继续试读具体文档。`;});
  async function showResult(name,args){
    const isURL=name==='read_document';
    $('#feishuResult').textContent='正在从飞书读取…';
    let result;try{result=await api('/api/connectors/feishu/read',{method:'POST',body:{name,arguments:args}});}catch(error){if(isCurrent())$('#feishuResult').textContent=error.message;throw error;}
    if(!isCurrent())return;
    const data=result.data||{};
    let content='';
    if(isURL){
      const xml=feishuResultText(result).replace(/<\/(?:p|h[1-6]|title|tr|li)>/gi,'$&\n');
      const text=new DOMParser().parseFromString(xml,'text/html').body.textContent;
      content=`<p>${data.document?.revision_id!==undefined?'文档版本 '+esc(data.document.revision_id)+' · ':''}<a href="${esc(args.url)}" target="_blank" rel="noopener noreferrer">在飞书查看原文 ↗</a></p><pre>${esc(text||'飞书未返回可显示的正文。请确认文档类型和访问权限。')}</pre>`;
    }else{
      const results=Array.isArray(data.results)?data.results:[];
      const plain=value=>String(value||'').replace(/<\/?(?:h|hb)>/g,'');
      content=results.length?`<ul class="feishu-search-results">${results.map((item,i)=>{const url=feishuDocumentURL(item.url);return `<li><b>${esc(plain(item.title||item.title_highlighted)||'未命名文档')}</b>${item.summary||item.summary_highlighted?`<p>${esc(plain(item.summary||item.summary_highlighted))}</p>`:''}${url?`<div><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">在飞书打开 ↗</a> <button data-read-result="${i}">读取文档</button></div>`:''}</li>`;}).join('')}</ul>`:'<p>本次搜索没有返回文档。可以换个关键词，或粘贴你有权限的文档链接。</p>';
      if(data.has_more&&data.page_token)content+='<button data-next-page>下一页</button>';
    }
    $('#feishuResult').innerHTML=`<p class="feishu-feedback">${isURL?'已收到文档读取结果':'已收到搜索结果'} · ${new Date(result.read_at*1000).toLocaleString()}</p>${content}<p class="settings-note">${esc(result.note)}</p>`;
    for(const b of root.querySelectorAll('[data-read-result]'))b.onclick=busy(()=>showResult('read_document',{url:data.results[Number(b.dataset.readResult)].url,scope:'full'}));
    $('[data-next-page]')?.addEventListener('click',busy(()=>showResult('search_documents',{...args,page_token:data.page_token})));
  }
  $('#feishuRead').onsubmit=busy(async e=>{
    const query=new FormData(e.target).get('query').trim();const isURL=/^https?:\/\//i.test(query);
    const name=isURL?'read_document':'search_documents',args=isURL?{url:query,scope:'full'}:{query};
    await showResult(name,args);
  });
  for(const button of root.querySelectorAll('[data-copy]'))button.onclick=busy(async()=>{await navigator.clipboard.writeText(button.dataset.copy==='scopes'?state.scopes.join('\n'):state.redirect_uri);notice('已复制。');});
}
