import {api} from './api.js';
import {esc} from './markdown.js';
import {RedlineOutline} from './redline-outline.js';
import {versionHistoryHTML} from './redline-versions.js';

const check=r=>{if(!r?.success)throw new Error(r?.failure?.message||'文档修改未成功');return r;};
const id=()=>crypto.randomUUID();

export class RedlineEditor {
  constructor({onQuote,onArtifact,onError}) {
    Object.assign(this,{onQuote,onArtifact,onError});this.client=id();this.generation=0;this.savedGeneration=0;this.subscriptions=[];this.reviewEvents=[];this.importedComments=new Set();
    window.addEventListener('pagehide',()=>{if(this.documentId&&this.owned&&!this.dirty&&!this.pending)void fetch(this.url('/lease'),{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json','X-Workbench-Request':'1'},body:JSON.stringify({client_id:this.client,release:true})}).catch(()=>{});});
    window.addEventListener('visibilitychange',()=>void this.visibilityChanged().catch(e=>this.fail(e)));
    window.addEventListener('beforeunload',e=>{if(this.dirty||this.pending){e.preventDefault();e.returnValue='';}});
  }
  get dirty(){return this.generation!==this.savedGeneration;}
  url(suffix=''){return `/api/redline/${this.documentId}${suffix}?thread_id=${this.threadId}`;}
  status(text,error=false){if(this.host){const x=this.host.querySelector('[data-redline-status]');x.textContent=text;x.classList.toggle('error',error);}}
  async open(options) {
    if(this.opening)return this.opening;
    this.opening=this.openDocument(options).finally(()=>{this.opening=null;});return this.opening;
  }
  async openDocument({documentId,threadId,user,host}) {
    if(this.documentId===documentId&&this.threadId===threadId&&this.editor&&this.ready)return;
    await this.close();Object.assign(this,{documentId,threadId,user,host});
    host.hidden=false;this.railWasCollapsed=document.body.classList.contains('workspace-rail-collapsed');document.body.classList.add('redline-open','workspace-rail-collapsed');
    for(const key of ['viewOriginal','viewText','viewRedline'])document.getElementById(key)?.setAttribute('aria-pressed',String(key==='viewRedline'));
    host.innerHTML=`<div class="redline-actions"><div class="redline-heading"><strong>合同审改</strong><span data-redline-status role="status">正在打开工作副本…</span></div><button data-r-action="current" hidden>返回当前版本</button><button data-r-action="outline-toggle" aria-expanded="false" aria-controls="redlineOutline" disabled>☷ 目录</button><button data-r-action="format" aria-expanded="false" aria-controls="redlineToolbar">格式</button><button data-r-action="review-toggle" aria-expanded="false">审阅记录 <span data-review-count></span></button><details class="redline-download"><summary>下载 <span aria-hidden="true">⌄</span></summary><div><button data-r-action="export">修订版 DOCX<small>保留修订和批注</small></button><button data-r-action="clean">清洁版 DOCX<small>处理全部修订后可下载</small></button><button data-r-action="rescue">当前浏览器副本<small>保存失败时保留本地改动</small></button></div></details></div><div class="redline-notice" data-redline-notice role="status" hidden></div><div class="redline-selection"><span data-selection-hint>选中文字，交给 Agent 修改或添加批注</span><button data-r-action="quote" disabled>让 Agent 修改</button><button data-r-action="comment" disabled>添加批注</button><button data-r-action="save" hidden>重试保存</button></div><div id="redlineToolbar" hidden></div><div class="redline-main"><aside id="redlineOutline" class="redline-outline" data-redline-outline aria-label="工作稿目录" hidden><header><strong>目录</strong><button data-r-action="outline-close" aria-label="关闭工作稿目录">×</button></header><div data-outline-body></div></aside><div id="redlineDocument"></div><aside class="redline-review" aria-label="审阅记录"><nav aria-label="审阅内容"><button data-r-tab="changes" aria-pressed="true">修订 <span data-change-count>0</span></button><button data-r-tab="comments" aria-pressed="false">批注</button><button data-r-tab="versions" aria-pressed="false">版本</button></nav><div data-redline-list></div><div data-comment-composer hidden><textarea aria-label="批注内容" placeholder="输入批注或回复"></textarea><button data-r-action="submit-comment">保存批注</button><button data-r-action="cancel-comment">取消</button></div></aside></div>`;
    host.onclick=e=>{const button=e.target.closest('button');const card=e.target.closest('[data-review-id]');if(!button&&card){void this.locateReview(card.dataset.reviewKind,card.dataset.reviewId).catch(err=>this.onError(err.message));return;}if(!button||!Object.keys(button.dataset).some(k=>k.startsWith('r')))return;e.stopPropagation();void this.click(button).catch(err=>{this.onError(err.message);});};
    try {
      this.state=await api(this.url());this.version=this.state.version.id;
      try{await this.acquire();}catch(e){if(e.status!==409)throw e;this.lockMessage=e.message;}
      await this.mount();
      this.timer=setInterval(()=>void this.heartbeat().catch(e=>this.fail(e)),3000);
    } catch(e){clearInterval(this.timer);await this.release().catch(()=>{});this.destroyEditor();this.status(e.message,true);throw e;}
  }
  async acquire(){await api(this.url('/lease'),{method:'POST',body:{client_id:this.client}});this.owned=true;}
  async release(){if(this.owned){try{await api(this.url('/lease'),{method:'POST',body:{client_id:this.client,release:true}});}catch(e){if(e.status!==409)throw e;}this.owned=false;}}
  destroyEditor(){this.outline?.destroy();this.outline=null;clearTimeout(this.saveTimer);cancelAnimationFrame(this.reviewFrame);this.reviewFrame=null;this.ready=false;this.subscriptions.splice(0).forEach(f=>f());this.ui?.destroy();this.ui=null;this.editor?.destroy();this.editor=null;}
  async loadFile(version=this.previewVersion||this.version){
    const response=await fetch(this.url('/file')+'&version_id='+encodeURIComponent(version),{credentials:'same-origin',signal:AbortSignal.timeout(30000)});
    if(!response.ok)throw new Error('工作版本加载失败，请重试');
    return new File([await response.blob()],'contract.docx',{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
  }
  async mount(file) {
    this.loading=true;this.editor?.setDocumentMode('viewing');this.updateAccess();
    try{await this.mountDocument(file);if(this.tab==='versions')this.renderVersions();}catch(error){if(this.ready&&this.owned&&!this.previewVersion)this.editor.setDocumentMode('suggesting');throw error;}finally{this.loading=false;this.updateAccess();}
  }
  async mountDocument(file) {
    // Keep the current document visible while downloading; 1.46.3 requires a new instance.
    const [documentFile,{SuperDoc,createSuperDocUI}]=await Promise.all([file||this.loadFile(),import('./vendor/redline-editor.js')]);
    const surfaceBefore=this.host.querySelector('#redlineDocument'),scrollTop=surfaceBefore.scrollTop,scrollLeft=surfaceBefore.scrollLeft;
    this.destroyEditor();this.changeItems=null;this.renderKey=null;this.reviewEpoch=0;this.composing=false;this.importedComments.clear();this.reviewScrollPending=false;

    this.host.querySelector('#redlineDocument').replaceChildren();this.host.querySelector('#redlineToolbar').replaceChildren();
    this.pending=null;this.generation=0;this.savedGeneration=0;
    await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(new Error('编辑器打开超时，请重新打开审改')),45000);
      const failure=({error})=>{clearTimeout(timeout);reject(new Error(error?.message||'此文档无法在编辑器中打开'));};
      this.editor=new SuperDoc({selector:'#redlineDocument',toolbar:'#redlineToolbar',document:documentFile,documentMode:this.previewVersion||!this.owned?'viewing':'suggesting',role:this.previewVersion?'viewer':'editor',allowSelectionInViewMode:true,modules:{comments:{displayMode:'inline'},trackChanges:{visible:true}},comments:{visible:true},zoom:{mode:'fit-width'},user:{name:this.user.username,email:this.user.id+'@workbench.local'},telemetry:{enabled:false},onReady:()=>{
        try{this.ui=createSuperDocUI({superdoc:this.editor});this.ready=true;this.reviewFocus=null;this.reviewPinned=false;this.subscriptions.push(this.ui.trackChanges.observe(s=>{this.changeItems=s.items.map(x=>x.change);this.reviewChanged('changes',s.activeId);}));
        this.subscriptions.push(this.ui.comments.observe(s=>this.reviewChanged('comments',s.activeIds[0])));
        this.subscriptions.push(this.ui.selection.observe(()=>this.selectionChanged()));
        this.render();this.updateAccess();this.status(this.previewVersion?'历史版本 · 只读':this.owned?'已保存':'只读 · 等待编辑权限');clearTimeout(timeout);resolve();}catch(error){failure({error});}
      },onTransaction:e=>this.editorTransaction(e),onCommentsUpdate:e=>this.commentsUpdated(e),onContentError:failure,onException:e=>{if(!this.ready)failure(e);else this.fail(new Error(e.error?.message||'编辑器出现异常，请先下载当前副本'));}});
    });
    this.outline=new RedlineOutline(this.host,this.editor);
    const surface=this.host.querySelector('#redlineDocument');
    surface.scrollTop=scrollTop;surface.scrollLeft=scrollLeft;
    surface.oncompositionstart=()=>{this.composing=true;clearTimeout(this.saveTimer);};
    surface.oncompositionend=()=>{this.composing=false;if(this.dirty)this.scheduleSave();};
    // Native comment activation is intentionally separate from caret-derived IDs.
    // Retain panel focus through SDK repaint; real document interaction resumes follow-selection.
    surface.onpointerdown=surface.onkeydown=()=>{this.reviewPinned=false;};
    surface.onpointerup=e=>{
      // The SDK resolves public revision IDs, including clicks on deleted text.
      // Do not steal a non-empty selection being captured for another Agent request.
      if(!this.editor.activeEditor?.state.selection.empty)return;
      const hit=this.ui.trackChanges.getAt({x:e.clientX,y:e.clientY});
      if(hit)this.reviewChanged('changes',hit.id);
    };
  }
  commentsUpdated(event={}){
    // Imported comments are emitted as ADD (even after ready); tracked-change
    // comments are SDK projections of body revisions, already covered by docChanged.
    if(['pending','selected','active','loaded'].includes(event.type))return;
    const commentId=event.comment?.commentId??event.comment?.importedId;
    const imported=event.type==='add'&&event.comment?.docxCommentJSON&&commentId!=null&&!this.importedComments.has(String(commentId));
    if(imported)this.importedComments.add(String(commentId));
    if(event.type==='comments-list'||event.comment?.trackedChange||imported){
      this.reviewEpoch=(this.reviewEpoch||0)+1;this.scheduleReview();return;
    }
    this.changed();
  }
  scheduleReview(){
    if(!this.ready||this.reviewFrame!=null)return;
    this.reviewFrame=requestAnimationFrame(()=>{this.reviewFrame=null;this.render();if(this.reviewScrollPending){this.reviewScrollPending=false;this.scrollReviewCard();}});
  }
  editorTransaction({transaction}={}){
    // setEditable/mode changes emit update even without a content transaction.
    if(!transaction?.docChanged)return;
    this.outline?.invalidate();this.selection=null;this.changed();
  }
  selectionChanged(){
    this.outline?.followSelection();this.selection=null;
    try{
      const editor=this.editor?.activeEditor, pm=editor?.state?.selection;
      // Images and rectangular table selections are not clause text. Never keep a stale text target.
      if(pm&&!pm.empty&&!pm.node&&!('$anchorCell' in pm)){
        const selection=editor.doc.selection.current({includeText:true});
        if(!selection.empty&&selection.text?.trim())this.selection=selection;
      }
    }catch(error){if(error.code!=='INVALID_CONTEXT')console.warn('redline.selection unavailable',error.code||error.name);}
    this.updateAccess();
  }
  updateAccess(){
    if(!this.host)return;
    const outlineToggle=this.host.querySelector('[data-r-action=outline-toggle]');if(outlineToggle)outlineToggle.disabled=!this.ready||this.loading;
    const editable=this.ready&&this.owned&&!this.previewVersion&&!this.loading,changeCount=this.ready?this.list().length:0;
    this.host.querySelectorAll('[data-r-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.rTab===(this.tab||'changes'))));
    const notice=this.host.querySelector('[data-redline-notice]');
    if(notice){notice.hidden=!!this.owned||!!this.previewVersion;notice.textContent=this.lockMessage?.includes('Agent')?'Agent 正在保存修订，完成后自动恢复编辑。':'当前为只读：另一标签页或浏览器正在编辑。关闭那里的审改后，此页会自动恢复；异常退出最多等待 30 秒。';}
    for(const b of this.host.querySelectorAll('[data-r-accept],[data-r-reject],[data-r-group],[data-r-resolve],[data-r-reply],[data-r-alternative],[data-r-detached],[data-r-restore],[data-r-action="comment"],[data-r-action="submit-comment"],[data-r-action="export"],[data-r-action="clean"],[data-r-action="accept-all"],[data-r-action="reject-all"]')){
      b.disabled=!editable||(b.dataset.rAction==='clean'&&changeCount>0)||(['accept-all','reject-all'].includes(b.dataset.rAction)&&!changeCount)||(b.dataset.rRestore===this.version);
    }
    const quote=this.host.querySelector('[data-r-action="quote"]'),comment=this.host.querySelector('[data-r-action="comment"]');
    if(quote)quote.disabled=!editable||!this.selection?.text;
    if(comment)comment.disabled=!editable||!this.selection?.target;
    const hint=this.host.querySelector('[data-selection-hint]');if(hint)hint.textContent=this.selection?.text?'已选中条款 · '+this.selection.text.length+' 字':'选中文字，交给 Agent 修改或添加批注';
    const toolbar=this.host.querySelector('#redlineToolbar');if(toolbar)toolbar.inert=!editable;
  }
  async visibilityChanged(){
    if(!this.ready||this.previewVersion||this.closing||this.operating)return;
    if(document.hidden){
      await this.beating;
      if(this.owned){this.editor.setDocumentMode('viewing');await this.flush();await this.release();this.lockMessage=null;this.updateAccess();}
    }else await this.heartbeat();
  }
  scheduleSave(){clearTimeout(this.saveTimer);if(!this.composing)this.saveTimer=setTimeout(()=>void this.flush().catch(e=>this.fail(e)),1800);}
  changed(){if(!this.ready||!this.owned||this.previewVersion)return;this.generation++;this.changeItems=null;this.status('正在保存…');this.scheduleSave();this.scheduleReview();}
  fail(e){this.host?.querySelector('[data-r-action=save]')?.removeAttribute('hidden');this.status('保存未确认：'+e.message,true);if(this.editor&&!this.owned)this.editor.setDocumentMode('viewing');}
  async flush() {
    if(this.saving)return this.saving;
    if(!this.editor||!this.ready||(!this.dirty&&!this.pending))return;
    this.saving=(async()=>{
      clearTimeout(this.saveTimer);
      while(this.dirty||this.pending){
        if(!this.pending){
          const generation=this.generation;
          const blob=await this.editor.export({triggerDownload:false});
          if(!(blob instanceof Blob))throw new Error('编辑器未生成 DOCX');
          this.pending={blob,generation,operation:id(),base:this.version,events:this.reviewEvents.splice(0)};
        }
        const p=this.pending;
        const saved=await api(this.url('/file'),{method:'PUT',body:p.blob,headers:{'X-Editor-Id':this.client,'X-Document-Version':p.base,'X-Operation-Id':p.operation,'X-Review-Events':JSON.stringify(p.events)}});
        if(!saved.saved)throw new Error('服务器未确认保存');
        this.version=saved.version_id;this.savedGeneration=p.generation;this.pending=null;
      }
      this.state=await api(this.url());this.render();this.status('已保存');this.host?.querySelector('[data-r-action=save]')?.setAttribute('hidden','');
    })().finally(()=>{this.saving=null;});
    return this.saving;
  }
  async heartbeat() {
    if(this.beating||this.operating||this.closing||this.loading||this.composing||this.previewVersion||!this.editor||document.hidden)return this.beating;
    this.beating=(async()=>{try{
      if(!this.owned){
        try{await this.acquire();}catch(e){if(e.status===409){this.lockMessage=e.message;this.updateAccess();return;}throw e;}
        const state=await api(this.url());
        if(state.version.id!==this.version){
          if(this.dirty||this.pending)throw new Error('服务器已有新版本，本地改动保留；请下载当前副本后重新打开');
          const previous=new Set((this.state.operations||[]).map(o=>o.operation_id));
          const file=await this.loadFile(state.version.id);
          this.state=state;this.version=state.version.id;await this.mount(file);
          const operation=(state.operations||[]).find(o=>o.author_email&&!previous.has(o.operation_id)&&this.list().some(c=>c.authorEmail===o.author_email));
          const change=operation&&this.list().find(c=>c.authorEmail===operation.author_email);
          if(change)await this.locateReview('changes',change.id).catch(e=>this.onError(e.message));
        }else this.editor.setDocumentMode('suggesting');
        if(this.dirty||this.pending)await this.flush();
        this.lockMessage=null;this.updateAccess();this.status('已保存');
      }
      const lease=await api(this.url('/lease'),{method:'POST',body:{client_id:this.client}});
      if(lease.yield_requested){
        this.editor.setDocumentMode('viewing');await this.flush();await this.release();this.lockMessage='Agent';this.updateAccess();this.status('Agent 正在写入修订…');
      }
    }catch(e){this.owned=false;this.editor?.setDocumentMode('viewing');this.updateAccess();throw e;}})();
    try{return await this.beating;}finally{this.beating=null;}
  }
  list(){return this.changeItems??=(this.ui?.trackChanges.getSnapshot().items||[]).map(x=>x.change);}
  changeContext(change){
    const op=(this.state.operations||[]).find(o=>o.author_email&&o.author_email===change.authorEmail);
    const matches=(op?.changes||[]).filter(c=>(change.deletedText?c.quote?.includes(change.deletedText):true)&&(change.insertedText?c.replacement?.includes(change.insertedText):true));
    return matches.length===1?matches[0].quote:'';
  }
  showReview(kind){
    if(this.host.clientWidth<1100)this.outline?.toggle(false);
    this.tab=kind;this.host.classList.add('review-open');this.host.querySelector('[data-r-action=review-toggle]').setAttribute('aria-expanded','true');
  }
  reviewChanged(kind,id){
    if(!this.ready)return;
    if(this.reviewPinned){this.scheduleReview();return;}
    const changed=id&&(this.reviewFocus?.kind!==kind||this.reviewFocus?.id!==id);
    if(changed){this.reviewFocus={kind,id};this.tab=kind;if(!this.outline?.open||this.host?.clientWidth>=1100)this.showReview(kind);this.reviewScrollPending=true;}
    if(!id&&this.reviewFocus?.kind===kind)this.reviewFocus=null;
    this.scheduleReview();
  }
  scrollReviewCard(){
    const focus=this.reviewFocus;if(!focus)return;
    const card=[...this.host.querySelectorAll('[data-review-id]')].find(c=>c.dataset.reviewKind===focus.kind&&c.dataset.reviewId===focus.id);
    const panel=this.host.querySelector('.redline-review');
    if(!card||!panel)return;
    // Scroll only the sidebar, never the entire page or the document viewport.
    const r=card.getBoundingClientRect(),p=panel.getBoundingClientRect(),header=panel.querySelector('nav').offsetHeight;
    if(r.top<p.top+header||r.bottom>p.bottom)panel.scrollTop+=r.top-p.top-header-8;
  }
  async locateReview(kind,id){
    const ui=this.ui,navigation=this.reviewNavigation=(this.reviewNavigation||0)+1;this.showReview(kind);
    const result=await ui[kind==='changes'?'trackChanges':'comments'].scrollTo(id);
    if(ui!==this.ui||navigation!==this.reviewNavigation)return;
    if(!result?.success)throw new Error('此处暂时无法定位，原文可能已变化，请重新选择审阅记录。');
    if(!ui[kind==='changes'?'trackChanges':'comments'].setActive(id))throw new Error('此审阅记录已变化，请重新选择。');
    this.reviewPinned=true;this.reviewFocus={kind,id};this.render();this.scrollReviewCard();
  }
  render(){
    if(!this.ready)return;
    const items=this.list(),count=this.host.querySelector('[data-change-count]');if(count)count.textContent=items.length;
    const summary=this.host.querySelector('[data-review-count]');if(summary)summary.textContent=items.length?`(${items.length})`:'';
    this.updateAccess();
    // Selection changes update only card emphasis. Hidden panels build nothing.
    if(!this.host.classList.contains('review-open')||this.tab==='versions')return;
    const key=[this.tab||'changes',this.version,this.previewVersion,this.generation,this.reviewEpoch||0].join(':');
    if(this.renderKey===key){this.highlightReview();return;}
    this.renderKey=key;
    const target=this.host.querySelector('[data-redline-list]');
    if(this.tab==='comments'){
      const items=this.editor.activeEditor.doc.comments.list({includeResolved:true,limit:100}).items;
      target.innerHTML=items.map(c=>{const id=c.id||c.commentId,active=this.reviewFocus?.kind==='comments'&&this.reviewFocus.id===id;const anchor=c.anchoredText||items.find(p=>p.commentId===(c.rootCommentId||c.parentCommentId))?.anchoredText;return `<article class="redline-card ${active?'active':''}" data-review-kind="comments" data-review-id="${esc(id)}"><button class="redline-locate" data-r-comment-locate="${esc(c.rootCommentId||c.parentCommentId||id)}" aria-pressed="${active}">${esc(c.creatorName||'审阅人')} · ${c.status==='resolved'?'已解决':'批注'}<span>查看正文 ↗</span></button>${anchor?`<blockquote class="redline-anchor"><small>对应原文</small>${esc(anchor)}</blockquote>`:''}<p>${esc(c.text||'')}</p><button data-r-reply="${esc(id)}">回复</button><button data-r-resolve="${esc(id)}" data-status="${esc(c.status)}">${c.status==='resolved'?'重新打开':'解决'}</button></article>`;}).join('')||'<p class="redline-empty">暂无批注。选中合同内容可添加批注。</p>';
      for(const c of this.state.detached_comments||[])target.insertAdjacentHTML('beforeend',`<article class="redline-card"><small>原锚点已删除 · ${esc(c.creatorName)} · ${c.status==='resolved'?'已解决':'未解决'}</small><p>${esc(c.text)}</p><button data-r-preview="${esc(c.last_version)}">查看原位置</button> <button data-r-detached="${esc(c.id)}" data-status="${esc(c.status)}">${c.status==='resolved'?'重新打开':'解决'}</button></article>`);this.updateAccess();return;
    }
    const active=this.reviewFocus?.kind==='changes'?this.reviewFocus.id:null;
    target.innerHTML=`<div class="redline-bulk"><span>${items.length} 项待审</span><button data-r-action="accept-all" ${items.length?'':'disabled'}>全部接受</button><button data-r-action="reject-all" ${items.length?'':'disabled'}>全部拒绝</button></div>`+items.map((c,i)=>`<article class="redline-card ${active===c.id?'active':''}" data-review-kind="changes" data-review-id="${esc(c.id)}"><button class="redline-locate" data-r-locate="${esc(c.id)}" aria-pressed="${active===c.id}">修订 ${i+1} · ${esc(({insert:"新增",delete:"删除",replacement:"替换",format:"格式"})[c.type]||c.type)}<span>查看正文 ↗</span></button><small>${esc(c.author||'审阅人')}</small>${this.changeContext(c)?`<blockquote class="redline-anchor"><small>修改前条款</small>${esc(this.changeContext(c))}</blockquote>`:''}<p><del>${esc(c.deletedText||'')}</del> <ins>${esc(c.insertedText||c.excerpt||'')}</ins></p><button data-r-accept="${esc(c.id)}">接受</button><button data-r-reject="${esc(c.id)}">拒绝</button><button data-r-alternative="${esc(c.id)}">换个表述</button></article>`).join('')+(items.length?'':'<p class="redline-empty">暂无待审修订。可以直接编辑，或让 Agent 修改条款。</p>');
    for(const op of (this.state.operations||[]).filter(o=>o.changes?.length).slice(0,5)){
      const section=document.createElement('details');section.className='redline-reasons';section.innerHTML=`<summary>${esc(op.summary||'Agent 修改说明')}</summary>${op.author_email&&items.some(c=>c.authorEmail===op.author_email)?`<button data-r-group="${esc(op.operation_id)}" data-decision="accept">接受这组</button> <button data-r-group="${esc(op.operation_id)}" data-decision="reject">拒绝这组</button>`:''}`+op.changes.map(c=>`<p><b>${esc(c.quote)}</b><br>${esc(c.reason||'按用户要求修改')}<br>${(c.sources||[]).map(s=>esc(typeof s==='string'?s:JSON.stringify(s))).join('<br>')}</p>`).join('');target.append(section);
    }
    this.updateAccess();
  }
  highlightReview(){
    for(const card of this.host.querySelectorAll('[data-review-id]')){
      const active=this.reviewFocus?.kind===card.dataset.reviewKind&&this.reviewFocus?.id===card.dataset.reviewId;
      card.classList.toggle('active',active);card.querySelector('.redline-locate')?.setAttribute('aria-pressed',String(active));
    }
  }
  async click(b){
    if(b.dataset.rAction==='outline-toggle'){
      if(!this.ready||this.loading)return;
      const open=!this.outline.open;
      if(open&&this.host.clientWidth<1100){this.host.classList.remove('review-open');this.host.querySelector('[data-r-action=review-toggle]').setAttribute('aria-expanded','false');}
      this.outline.toggle(open);return;
    }
    if(b.dataset.rAction==='outline-close'){this.outline?.toggle(false);this.host.querySelector('[data-r-action=outline-toggle]').focus();return;}
    if(b.dataset.rAction==='outline-retry'){this.outline?.refresh();return;}
    if(b.dataset.rHeading){await this.outline?.locate(b.dataset.rHeading);if(window.matchMedia('(max-width:1099px)').matches)this.outline?.toggle(false);return;}
    if(b.dataset.rHistory){this.importantVersions=b.dataset.rHistory==='important';this.historyLimit=20;this.renderVersions();return;}
    if(b.dataset.rAction==='more-versions'){this.historyLimit=(this.historyLimit||20)+20;this.renderVersions();return;}
    if(b.dataset.rAction==='mark-version'){
      if(this.loading)throw new Error('正在加载工作版本，请稍后再标记');
      await this.flush();const vid=this.previewVersion||this.version;
      this.importantVersions=false;this.historyLimit=Math.max(20,(this.state.versions||[]).findIndex(v=>v.id===vid)+1);await this.versions();this.nameVersion(vid);return;
    }
    if(b.dataset.rName){this.nameVersion(b.dataset.rName,b);return;}
    if(b.dataset.rAction==='cancel-version-name'){b.closest('[data-version-form]').remove();return;}
    if(b.dataset.rAction==='save-version-name'||b.dataset.rUnmark){
      const form=b.closest('[data-version-form]'),vid=b.dataset.rUnmark||form.dataset.versionForm;
      const label=b.dataset.rUnmark?'':form.querySelector('input').value.trim();
      if(!b.dataset.rUnmark&&!label)throw new Error('请输入版本名称');
      b.disabled=true;
      try{await api(this.url('/versions/'+encodeURIComponent(vid)+'/label'),{method:'PATCH',body:{label,revision:Number(b.dataset.rUnmark?b.dataset.labelRevision:form.dataset.labelRevision)}});await this.versions();}
      finally{b.disabled=false;}return;
    }
    const write=b.dataset.rReply||b.dataset.rAlternative||b.dataset.rAction==='quote'||b.dataset.rAccept||b.dataset.rReject||b.dataset.rGroup||b.dataset.rResolve||b.dataset.rDetached||b.dataset.rRestore||['comment','submit-comment','accept-all','reject-all','export','clean'].includes(b.dataset.rAction);
    if(write&&this.loading)throw new Error('正在加载工作版本，请稍后再编辑');
    if(write)this.reviewPinned=false;
    if(write&&!this.owned)throw new Error('当前窗口只读，等待编辑权限恢复后可操作');
    if(this.previewVersion&&![b.dataset.rAction==='current',!!b.dataset.rTab,b.dataset.rAction==='review-toggle',!!b.dataset.rPreview,!!b.dataset.rLocate,!!b.dataset.rCommentLocate].some(Boolean))throw new Error('历史版本只读，请返回当前版本后操作');
    if(b.dataset.rPreview){await this.flush();await this.release();this.previewVersion=b.dataset.rPreview;this.tab='versions';this.host.querySelector('[data-r-action=current]').hidden=false;await this.mount();await this.versions();return;}
    if(b.dataset.rDetached){await this.operation({action:'discussion',id:b.dataset.rDetached,resolved:b.dataset.status!=='resolved'});return;}
    if(b.dataset.rGroup){const op=(this.state.operations||[]).find(o=>o.operation_id===b.dataset.rGroup);const ids=this.list().filter(c=>c.authorEmail===op?.author_email).map(c=>c.id);if(!ids.length)throw new Error('这组修订已变化，请重新读取');this.reviewEvents.push({decision:b.dataset.decision,ids,operation_id:op.operation_id});for(const revision of ids)check(this.ui.trackChanges[b.dataset.decision](revision));this.changed();await this.flush();return;}
    if(b.dataset.rTab){this.tab=b.dataset.rTab;if(this.tab==='versions')await this.versions();else this.render();return;}
    if(b.dataset.rLocate){await this.locateReview('changes',b.dataset.rLocate);return;}
    if(b.dataset.rCommentLocate){await this.locateReview('comments',b.dataset.rCommentLocate);return;}
    if(b.dataset.rAccept||b.dataset.rReject){const key=b.dataset.rAccept?'rAccept':'rReject';this.reviewEvents.push({decision:key==='rAccept'?'accept':'reject',ids:[b.dataset[key]]});check(this.ui.trackChanges[key==='rAccept'?'accept':'reject'](b.dataset[key]));this.changed();await this.flush();return;}
    if(b.dataset.rRestore){await this.operation({action:'restore',restore_version:b.dataset.rRestore});return;}
    if(b.dataset.rAlternative){const change=this.editor.activeEditor.doc.trackChanges.get({id:b.dataset.rAlternative});this.onQuote({document_id:this.documentId,version_id:this.version,change_id:b.dataset.rAlternative,text:change.after?.text||change.insertedText||change.excerpt||'',instruction:'请重新读取此修订对应条款，换成更温和的表述，替换这项待审建议。'});return;}
    if(b.dataset.rReply){this.composer({parentId:b.dataset.rReply});return;}
    if(b.dataset.rResolve){check(this.editor.activeEditor.doc.comments.patch({commentId:b.dataset.rResolve,status:b.dataset.status==='resolved'?'active':'resolved'}));this.changed();return;}
    const action=b.dataset.rAction;
    if(action==='format'){const toolbar=this.host.querySelector('#redlineToolbar');toolbar.hidden=!toolbar.hidden;b.setAttribute('aria-expanded',String(!toolbar.hidden));return;}
    if(action==='review-toggle'){if(!this.host.classList.contains('review-open')&&this.host.clientWidth<1100)this.outline?.toggle(false);const open=this.host.classList.toggle('review-open');b.setAttribute('aria-expanded',String(open));if(open){if(this.tab==='versions')await this.versions();else this.render();}return;}
    if(action==='current'){this.previewVersion=null;this.host.querySelector('[data-r-action=current]').hidden=true;await this.acquire();this.state=await api(this.url());this.version=this.state.version.id;this.tab='versions';await this.mount();return;}
    if(action==='save'){await this.flush();return;}
    if(action==='quote'){const selection=this.selection;if(!selection?.text)throw new Error('请先选中需要修改的合同内容');await this.flush();this.onQuote({document_id:this.documentId,version_id:this.version,text:selection.text,target:selection.target});return;}
    if(action==='comment'){if(!this.selection?.target)throw new Error('请先选中批注对应的合同内容');this.composer({target:this.selection.target});return;}
    if(action==='submit-comment'){const text=this.host.querySelector('textarea').value.trim();if(!text)return;check(this.editor.activeEditor.doc.comments.create({...this.commentTarget,text}));this.host.querySelector('[data-comment-composer]').hidden=true;this.changed();return;}
    if(action==='cancel-comment'){this.host.querySelector('[data-comment-composer]').hidden=true;return;}
    if(action==='accept-all'||action==='reject-all'){this.reviewEvents.push({decision:action==='accept-all'?'accept':'reject',ids:this.list().map(c=>c.id)});check(this.ui.trackChanges[action==='accept-all'?'acceptAll':'rejectAll']());this.changed();await this.flush();return;}
    if(action==='rescue'){await this.editor.export({exportedName:'合同-当前浏览器副本'});return;}
    if(action==='export'||action==='clean'){
      if(action==='clean'&&this.list().length)throw new Error('请先处理剩余修订，再下载清洁版');
      await this.flush();const result=await api(this.url('/operations'),{method:'POST',body:{action:'export',clean:action==='clean',base_version:this.version,request_id:id()}});this.onArtifact(result);const a=document.createElement('a');a.href=result.download_url;a.download='';a.click();
    }
  }
  composer(target){this.host.classList.add('review-open');this.host.querySelector('[data-r-action=review-toggle]').setAttribute('aria-expanded','true');this.tab='comments';this.render();this.commentTarget=target;const c=this.host.querySelector('[data-comment-composer]');c.hidden=false;c.querySelector('textarea').value='';c.querySelector('textarea').focus();}
  renderVersions(){
    if(!this.host||this.tab!=='versions')return;
    this.host.querySelector('[data-redline-list]').innerHTML=versionHistoryHTML(this.state.versions,{current:this.version,preview:this.previewVersion,
      fileURL:vid=>this.url('/file')+'&version_id='+encodeURIComponent(vid),important:this.importantVersions,limit:this.historyLimit||20});
    this.updateAccess();
  }
  async versions(){
    this.renderKey=null;await this.flush();const did=this.documentId,tid=this.threadId,state=await api(this.url());
    if(this.documentId!==did||this.threadId!==tid)return;
    this.state=state;this.renderVersions();
  }
  nameVersion(vid,button){
    const v=this.state.versions.find(v=>v.id===vid);if(!v)return;
    const card=button?.closest('[data-version-id]')||[...this.host.querySelectorAll('[data-version-id]')].find(c=>c.dataset.versionId===vid);
    if(!card)return;
    this.host.querySelector('[data-version-form]')?.remove();
    const form=document.createElement('div');form.className='redline-version-form';form.dataset.versionForm=vid;form.dataset.labelRevision=String(v.label_revision);
    form.innerHTML=`<label>重要版本名称<input aria-label="重要版本名称" maxlength="80" value="${esc(v.label||'')}" placeholder="例如：内部审核完成稿"></label><small>只标记此保存记录，不创建新的合同版本。</small><div><button data-r-action="save-version-name">保存名称</button><button data-r-action="cancel-version-name">取消</button></div>`;
    button?.closest('details')?.removeAttribute('open');card.append(form);const input=form.querySelector('input');input.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();form.querySelector('[data-r-action=save-version-name]').click();}};
    input.focus();input.select();
  }
  async operation(body){this.operating=true;try{await this.beating;await this.flush();this.editor.setDocumentMode('viewing');await this.release();try{const result=await api(this.url('/operations'),{method:'POST',body:{...body,base_version:this.version,request_id:id()}});this.state=await api(this.url());this.version=this.state.version.id;await this.acquire();await this.mount();return result;}finally{if(this.owned)this.editor.setDocumentMode('suggesting');}}finally{this.operating=false;this.updateAccess();}}
  async close(){
    if(!this.documentId)return;this.closing=true;try{await this.beating;await this.flush();await this.release();clearInterval(this.timer);clearTimeout(this.saveTimer);
    this.destroyEditor();this.documentId=null;this.selection=null;document.getElementById('viewRedline')?.setAttribute('aria-pressed','false');
    if(this.host){this.host.hidden=true;this.host.replaceChildren();}document.body.classList.remove('redline-open');if(!this.railWasCollapsed)document.body.classList.remove('workspace-rail-collapsed');this.previewVersion=null;}finally{this.closing=false;}
  }
}
