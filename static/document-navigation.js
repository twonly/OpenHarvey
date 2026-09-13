import {esc} from './markdown.js';
const $=id=>document.getElementById(id);

// Keep offsets in the original UTF-16 text, even when case folding expands a
// character. Ignoring layout whitespace lets a PDF keyword span wrapped lines.
export function searchIndex(text){
  let value='',offsets=[];
  for(let i=0;i<text.length;){
    const character=String.fromCodePoint(text.codePointAt(i)),end=i+character.length;
    if(!/\s/u.test(character)){
      const folded=character.toLowerCase();value+=folded;
      for(let j=0;j<folded.length;j++)offsets.push([i,end]);
    }
    i=end;
  }
  return {value,offsets};
}

export function searchMatches(index,query){
  const needle=searchIndex(query).value,matches=[];
  if(!needle)return matches;
  for(let at=index.value.indexOf(needle);at>=0;at=index.value.indexOf(needle,at+needle.length)){
    matches.push([index.offsets[at][0],index.offsets[at+needle.length-1][1]]);
  }
  return matches;
}

export function outlineHTML(outline){
  const entries=outline?.entries||[];
  if(!entries.length)return `<p class="outline-empty">${outline?.unavailable?'目录暂时无法读取。': '原文未提供可用目录。'}<small>支持 Word 标题层级、PDF 书签和 Markdown 标题。</small></p>`;
  return `<p class="outline-caption">${{'word-headings':'来自 Word 标题','pdf-bookmarks':'来自 PDF 书签','markdown-headings':'来自 Markdown 标题'}[outline.source]||'文档目录'}</p><ol>${entries.map((entry,i)=>`<li><button type="button" data-outline="${i}" style="--outline-depth:${Math.max(0,Math.min(8,Number(entry.level)-1||0))}" title="${esc(entry.title)}"><span>${esc(entry.title)}</span>${entry.page?`<small>${Number(entry.page)} 页</small>`:''}</button></li>`).join('')}</ol>`;
}

export function setupDocumentNavigation(onNavigate,onError){
  const host=$('sourceContent'),input=$('sourceSearch'),outline=$('sourceOutline');
  let doc=null,index=searchIndex(''),chunks=[],ranges=[],current=-1,timer=null,ready=false,revision=0;
  const supported=!!globalThis.CSS?.highlights&&!!globalThis.Highlight;
  const clearHighlights=()=>{
    if(supported){CSS.highlights.delete('source-search');CSS.highlights.delete('source-search-current');}
    host.querySelectorAll('.search-current-fallback').forEach(el=>el.classList.remove('search-current-fallback'));
  };
  const controls=()=>{
    const hasQuery=!!searchIndex(input.value).value;
    $('sourceSearchCount').textContent=hasQuery?(ready?(ranges.length?`${current+1} / ${ranges.length}`:'无匹配'):'正在加载…'):'';
    $('sourceSearchCount').title=hasQuery&&ready?`当前文档共 ${ranges.length} 处匹配`:'';
    $('sourceSearchPrev').disabled=$('sourceSearchNext').disabled=!ranges.length||!ready;
    $('sourceSearchClear').hidden=!input.value;
    input.disabled=!doc;
    $('sourceOutlineToggle').disabled=!doc;$('sourceSearchToggle').disabled=!doc;
  };
  const scrollRange=range=>{
    const rect=range.getBoundingClientRect(),bounds=host.getBoundingClientRect();
    let left=host.scrollLeft;
    if(rect.left<bounds.left)left+=rect.left-bounds.left-12;
    else if(rect.right>bounds.right)left+=Math.min(rect.left-bounds.left-12,rect.right-bounds.right+12);
    host.scrollTo({top:host.scrollTop+rect.top-bounds.top-host.clientHeight/2+rect.height/2,
      left:Math.max(0,left)});
  };
  const paintCurrent=(scroll=true)=>{
    host.querySelectorAll('.search-current-fallback').forEach(el=>el.classList.remove('search-current-fallback'));
    if(supported)CSS.highlights.delete('source-search-current');
    const range=ranges[current];
    if(range){
      if(supported){const active=new Highlight(range);active.priority=1;CSS.highlights.set('source-search-current',active);}
      else range.startContainer.parentElement?.classList.add('search-current-fallback');
      if(scroll){
        $('sourceNavigationStatus').hidden=true;
        host.querySelectorAll('[data-block].highlight').forEach(el=>el.classList.remove('highlight'));
        outline.querySelectorAll('[aria-current]').forEach(el=>el.removeAttribute('aria-current'));
        scrollRange(range);
      }
    }
    controls();
  };
  const point=(offset,isEnd=false)=>{
    // Binary search keeps very common keywords fast on long contracts.
    let low=0,high=chunks.length-1;
    while(low<high){const mid=(low+high)>>1;if(chunks[mid].end<offset||(!isEnd&&chunks[mid].end===offset))low=mid+1;else high=mid;}
    const chunk=chunks[low];return [chunk.node,offset-chunk.start];
  };
  const run=(preserve=false)=>{
    clearTimeout(timer);timer=null;clearHighlights();ranges=[];
    if(ready&&chunks.length){
      for(const [start,end] of searchMatches(index,input.value)){
        const range=document.createRange();range.setStart(...point(start));range.setEnd(...point(end,true));ranges.push(range);
      }
    }
    current=ranges.length?(preserve?Math.max(0,Math.min(current,ranges.length-1)):0):-1;
    if(supported&&ranges.length){const all=new Highlight();for(const range of ranges)all.add(range);CSS.highlights.set('source-search',all);}
    paintCurrent();
  };
  const setOutlineOpen=open=>{outline.hidden=!open;$('sourceOutlineToggle').setAttribute('aria-expanded',String(open));};
  const setSearchOpen=open=>{
    $('sourceTools').hidden=!open;$('sourceSearchToggle').setAttribute('aria-expanded',String(open));
    if(open){input.focus();input.select();}
  };
  $('sourceSearchToggle').onclick=()=>setSearchOpen($('sourceTools').hidden);
  $('sourceSearchClose').onclick=()=>{setSearchOpen(false);$('sourceSearchToggle').focus();};
  $('sourceOutlineToggle').onclick=()=>setOutlineOpen(outline.hidden);
  $('sourceOutlineClose').onclick=()=>{setOutlineOpen(false);$('sourceOutlineToggle').focus();};
  outline.onclick=async e=>{
    const button=e.target.closest('[data-outline]'),entry=doc?.outline?.entries[Number(button?.dataset.outline)];
    if(!button||!entry||!ready)return;
    const version=revision;
    try{
      await onNavigate(entry);
      if(version!==revision)return;
      outline.querySelectorAll('[aria-current]').forEach(el=>el.removeAttribute('aria-current'));
      button.setAttribute('aria-current','location');
      if(host.parentElement.clientWidth<600)setOutlineOpen(false);
    }catch(error){onError(error.message);}
  };
  const move=step=>{if(!ready)return;if(timer){run();return;}if(ranges.length){current=(current+step+ranges.length)%ranges.length;paintCurrent();}};
  $('sourceSearchPrev').onclick=()=>move(-1);$('sourceSearchNext').onclick=()=>move(1);
  const clear=()=>{input.value='';run();input.focus();};
  $('sourceSearchClear').onclick=clear;
  input.addEventListener('input',e=>{clearTimeout(timer);timer=null;if(!e.isComposing)timer=setTimeout(()=>{timer=null;run();},120);});
  input.addEventListener('compositionend',()=>{clearTimeout(timer);timer=null;run();});
  input.addEventListener('keydown',e=>{
    if(e.isComposing)return;
    if(e.key==='Enter'){e.preventDefault();move(e.shiftKey?-1:1);}
    if(e.key==='Escape'&&$('contextPane').dataset.layout==='stacked'){e.preventDefault();e.stopPropagation();setSearchOpen(false);$('sourceSearchToggle').focus();}
  });
  $('docPane').addEventListener('keydown',e=>{
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'&&doc){e.preventDefault();setSearchOpen(true);}
    if(e.key==='Escape'&&$('contextPane').dataset.layout==='stacked'&&!outline.hidden){e.preventDefault();setOutlineOpen(false);$('sourceOutlineToggle').focus();}
  });
  const loading=()=>{ready=false;clearTimeout(timer);timer=null;ranges=[];chunks=[];index=searchIndex('');clearHighlights();controls();};
  return {
    setDocument(value){
      if(doc?.id===value?.id&&doc?.source_hash===value?.source_hash)return;
      revision++;doc=value;input.value='';current=-1;loading();
      $('sourceOutlineBody').innerHTML=outlineHTML(doc?.outline);
      setSearchOpen(false);if(!doc)setOutlineOpen(false);
    },
    loading,
    refresh(){
      chunks=[];let text='';
      const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT,{acceptNode(node){
        const parent=node.parentElement;
        return parent&&!parent.closest('style,script,small,[data-search-skip]')&&parent.closest('.source-block [data-block],.pdf-text-layer [data-block],section.docx article')?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT;
      }});
      while(walker.nextNode()){
        const node=walker.currentNode;if(!node.textContent.length)continue;
        chunks.push({node,start:text.length,end:text.length+node.textContent.length});text+=node.textContent;
      }
      index=searchIndex(text);ready=true;run(true);
    }
  };
}
