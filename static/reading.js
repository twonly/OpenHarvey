import {esc} from './markdown.js';
const $=id=>document.getElementById(id);

export function setupArtifactStrip(){
  const strip=$('artifactStrip'),tabs=$('artifactTabs'),prev=$('artifactPrev'),next=$('artifactNext');
  let activeId=null,start=null,dragged=false;
  const edges=()=>{prev.disabled=tabs.scrollLeft<=1;next.disabled=tabs.scrollLeft+tabs.clientWidth>=tabs.scrollWidth-1;};
  const measure=()=>{
    const overflow=tabs.scrollWidth>strip.clientWidth+1;
    prev.hidden=next.hidden=!overflow;
    edges();
  };
  new ResizeObserver(measure).observe(strip);
  tabs.addEventListener('scroll',edges,{passive:true});
  prev.onclick=()=>tabs.scrollBy({left:-Math.max(120,tabs.clientWidth*.8),behavior:'smooth'});
  next.onclick=()=>tabs.scrollBy({left:Math.max(120,tabs.clientWidth*.8),behavior:'smooth'});
  tabs.addEventListener('pointerdown',e=>{
    dragged=false;
    if(e.pointerType!=='mouse'||e.button!==0||tabs.scrollWidth<=tabs.clientWidth)return;
    start={x:e.clientX,left:tabs.scrollLeft};
  });
  tabs.addEventListener('pointermove',e=>{
    if(!start)return;
    const dx=e.clientX-start.x;
    if(!dragged&&Math.abs(dx)<5)return;
    dragged=true;tabs.setPointerCapture(e.pointerId);tabs.classList.add('dragging');
    tabs.scrollLeft=start.left-dx;
  });
  const stop=()=>{start=null;tabs.classList.remove('dragging');};
  tabs.addEventListener('pointerup',stop);tabs.addEventListener('pointercancel',stop);
  tabs.addEventListener('lostpointercapture',stop);
  tabs.addEventListener('pointerleave',()=>{if(!dragged)stop();});
  tabs.addEventListener('click',e=>{if(dragged){e.preventDefault();e.stopImmediatePropagation();dragged=false;}},true);
  return {update(id){
    const changed=id!==activeId;activeId=id;
    requestAnimationFrame(()=>{
      measure();
      if(changed){
        const active=tabs.querySelector('[aria-pressed="true"]');
        if(active){const a=active.getBoundingClientRect(),b=tabs.getBoundingClientRect();if(a.left<b.left)tabs.scrollLeft+=a.left-b.left;else if(a.right>b.right)tabs.scrollLeft+=a.right-b.right;}
      }
      edges();
    });
  }};
}

export function setupReading(){
  const pane=$('contextPane');let mode='stacked';
  const hidden=new Set();
  const visible=name=>{
    const rect=$(name==='source'?'docPane':'artPane').getBoundingClientRect();
    return rect.width>0&&rect.height>0;
  };
  const sync=()=>{
    for(const name of ['source','artifact'])$(name==='source'?'toggleSource':'toggleArtifact').setAttribute('aria-expanded',String(visible(name)));
  };
  const setPane=(name,visible)=>{
    if(visible)hidden.delete(name);else hidden.add(name);
    if(mode!=='stacked')apply('stacked');
    pane.dataset.sourceHidden=String(hidden.has('source'));
    pane.dataset.artifactHidden=String(hidden.has('artifact'));
    document.querySelector('main').classList.toggle('context-closed',hidden.size===2);
    if(innerWidth<=1020)document.body.classList.toggle('context-mobile',hidden.size<2);
    for(const key of ['source','artifact']){
      const button=$(key==='source'?'toggleSource':'toggleArtifact');
      button.setAttribute('aria-expanded',String(!hidden.has(key)));
      button.title=(hidden.has(key)?'显示':'隐藏')+(key==='source'?'合同原文':'产出物');
    }
  };
  const apply=value=>{
    const positions=['sourceContent','artBody','compareBody'].map(id=>{
      const el=$(id),top=el.getBoundingClientRect().top;
      const anchor=[...el.querySelectorAll('.pdf-page,.source-block,section.docx')].find(node=>node.getBoundingClientRect().bottom>top);
      const rect=anchor?.getBoundingClientRect();
      return {el,scroll:el.scrollTop,anchor,offset:rect?(top-rect.top)/rect.height:0};
    });
    mode=value;pane.dataset.layout=mode;
    document.body.classList.toggle('reading-wide',mode!=='stacked');
    document.querySelectorAll('button[data-layout]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.layout===mode)));
    document.querySelectorAll('.pane-expand').forEach(b=>{const label=b.dataset.layout===mode?'还原工作区':b.dataset.layout==='source'?'放大合同文档':'放大产出物';b.setAttribute('aria-label',label);b.title=label;});
    $('contextSplit').setAttribute('aria-orientation',mode==='compare'?'vertical':'horizontal');
    document.querySelectorAll('.document-more').forEach(menu=>menu.open=false);
    requestAnimationFrame(()=>positions.forEach(({el,scroll,anchor,offset})=>{
      const rect=anchor?.getBoundingClientRect();
      el.scrollTop=rect?el.scrollTop+rect.top-el.getBoundingClientRect().top+offset*rect.height:scroll;
    }));
  };
  document.querySelectorAll('button[data-layout]').forEach(b=>b.onclick=()=>apply(b.dataset.layout===mode?'stacked':b.dataset.layout));
  for(const name of ['source','artifact']){
    $(name==='source'?'toggleSource':'toggleArtifact').onclick=()=>setPane(name,!visible(name));
    document.querySelector(`[data-close-pane="${name}"]`).onclick=()=>{setPane(name,false);$(name==='source'?'toggleSource':'toggleArtifact').focus();};
  }
  const observer=new MutationObserver(sync);
  for(const target of [document.body,document.querySelector('main'),pane])observer.observe(target,{attributes:true,attributeFilter:['class','data-layout','data-source-hidden','data-artifact-hidden']});
  window.addEventListener('resize',sync);requestAnimationFrame(sync);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.defaultPrevented&&mode!=='stacked'){e.preventDefault();apply('stacked');}});
  document.addEventListener('click',e=>{document.querySelectorAll('.document-more').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;});});
  document.querySelectorAll('.document-more').forEach(menu=>menu.addEventListener('keydown',e=>{if(e.key==='Escape'&&mode==='stacked'){menu.open=false;menu.querySelector('summary').focus();e.preventDefault();}}));
  let drag=false;const split=$('contextSplit');
  const sideBySide=()=>mode==='compare'&&innerWidth>700;
  const change=value=>{const axis=sideBySide()?'width':'height',size=Math.max(20,Math.min(80,value));pane.style.setProperty('--source-'+axis,size+'%');split.setAttribute('aria-valuenow',String(Math.round(size)));};
  split.onpointerdown=e=>{drag=true;split.setPointerCapture(e.pointerId);document.body.classList.add('resizing');};
  split.onpointermove=e=>{if(!drag)return;const rect=pane.getBoundingClientRect();change(sideBySide()?(e.clientX-rect.left)/rect.width*100:(e.clientY-$('docPane').getBoundingClientRect().top)/pane.clientHeight*100);};
  const stop=()=>{drag=false;document.body.classList.remove('resizing');};split.onpointerup=stop;split.onpointercancel=stop;
  split.onkeydown=e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home'].includes(e.key))return;e.preventDefault();const axis=sideBySide()?'width':'height',current=parseFloat(pane.style.getPropertyValue('--source-'+axis))||50;change(e.key==='Home'?50:current+(['ArrowDown','ArrowRight'].includes(e.key)?3:-3));};
  return {showSource(){setPane('source',true);},showArtifact(){setPane('artifact',true);apply('artifact');},reset(){apply('stacked');}};
}

export function pdfMarkup(doc,tid){
  const pages=new Map();for(const seg of doc.segments){if(!pages.has(seg.page))pages.set(seg.page,[]);pages.get(seg.page).push(seg);}
  return doc.pages.map((p,i)=>`<div class="pdf-page" data-page="${i+1}" style="aspect-ratio:${p.w}/${p.h}"><img loading="lazy" draggable="false" src="/api/documents/${doc.id}/pages/${i+1}${tid?'?thread_id='+tid:''}" alt="第 ${i+1} 页"><div class="pdf-text-layer">${(pages.get(i+1)||[]).filter(s=>s.bbox).map(s=>{const b=s.bbox;return `<span data-block="${s.id}" data-font-height="${(b[3]-b[1])/p.w}" style="left:${b[0]/p.w*100}%;top:${b[1]/p.h*100}%;width:${(b[2]-b[0])/p.w*100}%;height:${(b[3]-b[1])/p.h*100}%"><span>${esc(s.text)}</span></span>`;}).join('')}</div></div>`).join('');
}

export function fitPdfText(host){
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
  // Read page geometry once before writing styles; long PDFs must not force a
  // synchronous layout for every text line on every resize frame.
  const pages=[...host.querySelectorAll('.pdf-page')].map(page=>[page,page.clientWidth]);
  for(const [page,width] of pages){
    if(!width||Number(page.dataset.textWidth)===width)continue;
    page.dataset.textWidth=String(width);
    for(const line of page.querySelectorAll('.pdf-text-layer>[data-block]')){
      const font=Number(line.dataset.fontHeight)*width,text=line.firstElementChild;
      ctx.font=`${font}px sans-serif`;text.style.fontSize=font+'px';
      text.style.transform=`scaleX(${parseFloat(line.style.width)/100*width/Math.max(1,ctx.measureText(text.textContent).width)})`;
    }
  }
}

export function setupQuotes(context,onChange,onError,onAdd=()=>{}){
  let quotes=[],selection=null;const host=$('sourceContent'),toolbar=$('sourceSelectionToolbar');
  const render=()=>{$('sourceQuoteTray').innerHTML=quotes.map((q,i)=>`<div class="quote-chip"><button data-quote-open="${i}"><b>${esc(q.filename)} · 已圈选</b><span>${esc(q.text)}</span></button><button data-quote-remove="${i}" aria-label="移除原文引用">×</button></div>`).join('');onChange(quotes);};
  const hide=()=>{selection=null;toolbar.hidden=true;};
  document.addEventListener('selectionchange',()=>{
    const selected=window.getSelection(),{source,tid}=context();
    if(!source||!tid||!selected?.rangeCount||selected.isCollapsed)return hide();
    const range=selected.getRangeAt(0);
    if(!host.contains(range.startContainer)||!host.contains(range.endContainer))return hide();
    const pieces=[],ids=[];
    for(const el of host.querySelectorAll('[data-block]')){
      if(!range.intersectsNode(el))continue;
      const part=document.createRange();part.selectNodeContents(el);
      if(part.compareBoundaryPoints(Range.START_TO_START,range)<0)part.setStart(range.startContainer,range.startOffset);
      if(part.compareBoundaryPoints(Range.END_TO_END,range)>0)part.setEnd(range.endContainer,range.endOffset);
      if(part.toString().trim()){pieces.push(part.toString());ids.push(el.dataset.block);}
    }
    if(!pieces.length)return hide();
    selection={document_id:source.id,source_hash:source.source_hash,filename:source.filename,block_ids:ids,text:pieces.join('\n').trim(),tid};
    const rect=range.getBoundingClientRect();toolbar.hidden=false;
    toolbar.style.left=Math.max(8,Math.min(innerWidth-170,rect.left))+'px';toolbar.style.top=Math.max(8,Math.min(innerHeight-50,rect.bottom+6))+'px';
  });
  $('addSourceQuote').onpointerdown=e=>e.preventDefault();
  $('addSourceQuote').onclick=()=>{if(!selection||selection.tid!==context().tid)return;if(quotes.length>=5)return onError('每条消息最多引用 5 处原文。');if(selection.text.length>10000)return onError('圈选内容过长，请选择 10000 字以内的条款。');quotes.push(selection);render();hide();window.getSelection()?.removeAllRanges();document.body.classList.remove('context-mobile');onAdd();$('input').focus();};
  $('sourceQuoteTray').onclick=e=>{const remove=e.target.closest('[data-quote-remove]');if(remove){quotes.splice(Number(remove.dataset.quoteRemove),1);render();}};
  return {get:()=>quotes,set:items=>{quotes=items||[];render();hide();},removeDocument:id=>{quotes=quotes.filter(q=>q.document_id!==id);render();},hide};
}
