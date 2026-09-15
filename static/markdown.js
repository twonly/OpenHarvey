import {t as tr,ui,getLanguage} from './i18n.js';
export const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// IDs and hashes remain machine-readable navigation keys, never display labels.
export function citations(escaped,documents=[],allowBare=true){
  const valid=new Map(documents.map(d=>[d.id,d]));
  return escaped.replace(/【(?:D([a-f0-9]{12}):)?B(\d+)(?:-B(\d+))?】/g,(_,id,block,end=block)=>{
    if(!id){
      if(!allowBare||documents.length!==1)return tr('<span class="invalid-citation" title="引用缺少来源文件，无法唯一定位">来源待核对</span>');
      id=documents[0].id;
      if(!documents[0].locations)return tr('<span class="invalid-citation" title="缺少段落定位数据">来源待核对</span>');
    }
    const doc=valid.get(id),location=doc?.locations?.['B'+block],last=doc?.locations?.['B'+end];
    const start=Number(block),stop=Number(end);
    if(!doc||!Number.isSafeInteger(start)||!Number.isSafeInteger(stop)||stop<start||stop-start>100000||(doc.locations&&(!location||!last||!Array.from({length:stop-start+1},(_,i)=>doc.locations['B'+(start+i)]).every(Boolean))))return tr('<span class="invalid-citation" title="材料已移除或引用位置不存在">引用暂不可用</span>');
    const a=location?.ordinal||start+1,b=last?.ordinal||stop+1;
    const where=getLanguage()==='en'
      ?(location?.page&&last?.page?(location.page===last.page?`Page ${location.page}`:`Pages ${location.page}–${last.page}`):(a===b?`Paragraph ${a}`:`Paragraphs ${a}–${b}`))
      :(location?.page&&last?.page?(location.page===last.page?`第 ${location.page} 页`:`第 ${location.page}–${last.page} 页`):(a===b?`第 ${a} 段`:`第 ${a}–${b} 段`));
    const name=doc.thread_id?(doc.filename||tr('附件')):tr('查看原文');
    const position=(location?.page?'PDF · ':'')+where;
    const preview=location?.preview?'\n'+location.preview:'';
    return ui`<button class="citation" data-doc="${id}" data-block="B${block}" data-end="B${end}" data-hash="${esc(doc.source_hash)}" title="${esc(doc.filename||name)} · ${position}${stop>start?tr(' · 连续 ')+(stop-start+1)+tr(' 段'):''}，点击查看原文${esc(preview)}"><span class="citation-name">${esc(name)}</span><span aria-hidden="true"> · </span><span>${position}</span></button>`;
  });
}

export function markdown(text,documents=[]){
  const explicit=[...String(text||'').matchAll(/【D([a-f0-9]{12}):B/g)].map(m=>m[1]);
  const allowBare=documents.length===1&&explicit.every(id=>id===documents[0].id);
  function inline(s){
    return citations(esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>'),documents,allowBare);
  }
  let html='',table=[],code=null;
  function flush(){if(table.length){
    const rows=table.filter(row=>!row.every(c=>/^:?-+:?$/.test(c.replace(/\s/g,''))));
    html+='<table>'+rows.map((r,i)=>'<tr>'+r.map(c=>`<${i?'td':'th'}>${inline(c)}</${i?'td':'th'}>`).join('')+'</tr>').join('')+'</table>';table=[];
  }}
  for(const line of String(text||'').split('\n')){
    if(line.startsWith('```')){flush();if(code!==null){html+='<pre><code>'+esc(code.join('\n'))+'</code></pre>';code=null;}else code=[];continue;}
    if(code!==null){code.push(line);continue;}
    if(/^\s*\|.*\|\s*$/.test(line)){table.push(line.trim().slice(1,-1).split('|').map(s=>s.trim()));continue;}
    flush();
    const heading=line.match(/^(#{1,4})\s+(.+)/);
    if(heading)html+=`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`;
    else if(/^[-*]\s/.test(line))html+='<ul><li>'+inline(line.slice(2))+'</li></ul>';
    else if(line.startsWith('> '))html+='<blockquote>'+inline(line.slice(2))+'</blockquote>';
    else if(line.trim())html+='<p>'+inline(line)+'</p>';
  }
  flush();if(code!==null)html+='<pre>'+esc(code.join('\n'))+'</pre>';return html;
}
