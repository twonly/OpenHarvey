import {esc} from './markdown.js';

export function readOutline(doc){
  const blocks=[];
  for(let offset=0;;){
    const page=doc.blocks.list({offset,limit:500,includeText:true});
    blocks.push(...page.blocks);offset+=page.blocks.length;
    if(offset>=page.total)break;
    if(!page.blocks.length)throw new Error('目录读取不完整，请重试');
  }
  const entries=blocks.filter(b=>b.nodeType==='heading'&&b.headingLevel&&b.text?.trim()).map(b=>({
    id:b.nodeId,level:b.headingLevel,ordinal:b.ordinal,title:(b.numbering?.marker?b.numbering.marker+' ':'')+b.text.trim(),
    address:{kind:'block',nodeType:b.nodeType,nodeId:b.nodeId},
  }));
  const ordinals=new Map(blocks.filter(b=>!b.isEmpty&&b.text?.trim()&&['paragraph','heading','listItem'].includes(b.nodeType)).map(b=>[b.nodeId,b.ordinal])),renderOrdinals=new Map(ordinals);
  // The pagination renderer uses SD node IDs; API navigation uses paragraph IDs.
  // Resolve that relationship through the engine projection, never by matching text or DOM offsets.
  for(let offset=0;;){
    const page=doc.find({select:{type:'node',kind:'block'},offset,limit:500});
    for(const item of page.items){const ordinal=ordinals.get(item.address.nodeId);if(item.node?.id&&ordinal!=null)renderOrdinals.set(item.node.id,ordinal);}
    offset+=page.items.length;if(offset>=page.total)break;
    if(!page.items.length)throw new Error('目录位置读取不完整，请重试');
  }
  return {blocks,entries,renderOrdinals};
}
export function headingAt(entries,ordinal){
  let low=0,high=entries.length;
  while(low<high){const mid=(low+high)>>>1;if(entries[mid].ordinal<=ordinal)low=mid+1;else high=mid;}
  return low?entries[low-1].id:null;
}

export class RedlineOutline {
  constructor(host,superdoc){
    this.host=host;this.superdoc=superdoc;this.surface=host.querySelector('#redlineDocument');this.panel=host.querySelector('[data-redline-outline]');
    this.body=this.panel.querySelector('[data-outline-body]');this.dirty=true;this.entries=[];this.ordinals=new Map();this.visible=new Set();
    this.onScroll=()=>{if(this.open)this.scheduleViewport();};
    this.onInteract=()=>{this.pinned=false;};
    for(const type of ['wheel','touchstart','pointerdown','keydown'])this.surface.addEventListener(type,this.onInteract,{passive:true});
    this.surface.addEventListener('scroll',this.onScroll,{capture:true,passive:true});
    this.intersections=new IntersectionObserver(changes=>{for(const c of changes){if(c.isIntersecting)this.visible.add(c.target);else this.visible.delete(c.target);}this.scheduleViewport();},{root:this.surface});
    this.mutations=new MutationObserver(changes=>{if(this.open&&changes.some(c=>[...c.addedNodes,...c.removedNodes].some(n=>n.nodeType===1&&(n.matches('[data-block-id]')||n.querySelector('[data-block-id]')))))this.scheduleNodes();});
    this.mutations.observe(this.surface,{subtree:true,childList:true});
    if(this.open)this.refresh();
  }
  get open(){return this.host.classList.contains('outline-open');}
  toggle(open=!this.open){
    this.host.classList.toggle('outline-open',open);this.panel.hidden=!open;
    this.host.querySelector('[data-r-action=outline-toggle]').setAttribute('aria-expanded',String(open));
    if(open){if(this.dirty)this.refresh();else this.observeNodes();}
    else{this.intersections.disconnect();this.visible.clear();clearTimeout(this.timer);}
  }
  invalidate(){this.dirty=true;if(this.open){clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),600);}}
  refresh(){
    clearTimeout(this.timer);if(this.destroyed||!this.open)return;
    try{
      const {blocks,entries,renderOrdinals}=readOutline(this.superdoc.activeEditor.doc);this.entries=entries;this.ordinals=new Map(blocks.map(b=>[b.nodeId,b.ordinal]));this.renderOrdinals=renderOrdinals;this.dirty=false;
      const html=entries.length?'<p class="outline-caption">当前工作稿 · Word 标题</p><ol>'+entries.map(e=>`<li><button data-r-heading="${esc(e.id)}" style="--outline-depth:${Math.min(8,e.level-1)}" title="${esc(e.title)}"><span>${esc(e.title)}</span></button></li>`).join('')+'</ol>':'<p class="outline-empty">当前工作稿没有可用标题。<small>目录使用编辑器识别的 Word 标题层级，不从正文猜测章节。</small></p>';
      if(this.html!==html){this.html=html;this.body.innerHTML=html;}
      this.highlight(this.active);this.observeNodes();
    }catch(error){this.dirty=true;this.html=null;this.body.innerHTML='<p class="outline-empty" role="status">目录暂时无法读取。<small>可以继续编辑合同，或点击重试。</small></p><button data-r-action="outline-retry">重试目录</button>';}
  }
  highlight(id){
    if(!this.entries.some(e=>e.id===id))id=null;
    this.active=id;
    const current=this.body.querySelector('[aria-current]');if(current?.dataset.rHeading===id)return;
    current?.removeAttribute('aria-current');
    const button=[...this.body.querySelectorAll('[data-r-heading]')].find(b=>b.dataset.rHeading===id);
    if(button){button.setAttribute('aria-current','location');const r=button.getBoundingClientRect(),p=this.body.getBoundingClientRect();if(r.top<p.top||r.bottom>p.bottom)this.body.scrollTop+=r.top-p.top-8;}
  }
  followSelection(){
    if(!this.open||this.dirty||!this.entries.length)return;
    try{const target=this.superdoc.activeEditor.doc.selection.current().target;
      const ordinal=this.ordinals.get(target?.segments?.[0]?.blockId);if(ordinal!=null){this.pinned=true;this.highlight(headingAt(this.entries,ordinal));}
    }catch{} // Image/header selections need no body outline target.
  }
  scheduleNodes(){if(this.nodesFrame!=null)return;this.nodesFrame=requestAnimationFrame(()=>{this.nodesFrame=null;this.observeNodes();});}
  observeNodes(){
    if(this.destroyed||!this.open)return;
    // Rendered block IDs are used only to observe the viewport. Navigation always uses the Document API address.
    this.intersections.disconnect();this.visible.clear();
    for(const node of this.surface.querySelectorAll('[data-block-id]'))if(this.renderOrdinals.has(node.dataset.blockId))this.intersections.observe(node);
  }
  scheduleViewport(){
    if(this.frame!=null||!this.open)return;
    this.frame=requestAnimationFrame(()=>{this.frame=null;if(this.destroyed||this.dirty||this.pinned||!this.open)return;
      const root=this.surface.getBoundingClientRect();let first=Infinity;
      for(const node of this.visible){const rect=node.getBoundingClientRect();if(rect.bottom>root.top+8&&rect.top<root.bottom)first=Math.min(first,this.renderOrdinals.get(node.dataset.blockId)??Infinity);}
      if(Number.isFinite(first))this.highlight(headingAt(this.entries,first));
    });
  }
  async locate(id){
    if(this.dirty)this.refresh();const entry=this.entries.find(e=>e.id===id);
    if(!entry||this.dirty)throw new Error('标题已变化，请刷新目录后重新选择');
    const navigation=this.navigation=(this.navigation||0)+1;
    this.pinned=true;
    const success=await this.superdoc.navigateTo(entry.address);
    if(this.destroyed||navigation!==this.navigation)return;
    if(!success){this.pinned=false;this.invalidate();throw new Error('此标题暂时无法定位，请刷新目录后重试');}
    this.highlight(id);
  }
  destroy(){this.destroyed=true;clearTimeout(this.timer);cancelAnimationFrame(this.frame);cancelAnimationFrame(this.nodesFrame);this.intersections.disconnect();this.mutations.disconnect();this.surface.removeEventListener('scroll',this.onScroll,true);for(const type of ['wheel','touchstart','pointerdown','keydown'])this.surface.removeEventListener(type,this.onInteract);}
}
