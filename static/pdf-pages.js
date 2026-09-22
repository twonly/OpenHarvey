import {t as tr} from './i18n.js';
import {loadingHTML} from './loading-ui.js';

export function pdfBatch(page,total){
  const start=Math.floor((page-1)/3)*3+1;
  return {start,count:Math.min(3,total-start+1)};
}
export function pdfWidth(width,dpr=1){
  const target=width*dpr;
  return [960,1920,2880].find(value=>value>=target)||2880;
}

// Only nearby pages are requested; one three-page batch is in flight at a time.
export function loadPdfPages(host,doc,tid,options={}){
  const fetcher=options.fetch||globalThis.fetch;
  const URLs=options.URL||globalThis.URL;
  const Observe=options.IntersectionObserver||globalThis.IntersectionObserver;
  const Resize=options.ResizeObserver||globalThis.ResizeObserver;
  const controller=new AbortController(),nearby=new Set(),loaded=new Map(),urls=new Map(),failed=new Set();
  const pages=[...host.querySelectorAll('.pdf-page')];
  let stopped=false,busy=false,timer=null;
  const width=()=>pdfWidth(pages[0]?.clientWidth||host.clientWidth||960,globalThis.devicePixelRatio||1);
  function enqueue(){
    if(stopped||busy)return;
    const resolution=width();
    const candidates=[...nearby].filter(page=>loaded.get(page)!==resolution&&!failed.has(`${page}:${resolution}`));
    const bounds=host.getBoundingClientRect();
    const page=candidates.find(number=>{
      const rect=pages[number-1].getBoundingClientRect();
      return rect.bottom>bounds.top&&rect.top<bounds.bottom;
    })??candidates[0];
    if(page===undefined)return;
    busy=true;
    const {start,count}=pdfBatch(page,doc.pages.length);
    void (async()=>{
      try{
        const query=new URLSearchParams({start:String(start),count:String(count),width:String(resolution)});
        if(tid)query.set('thread_id',tid);
        const response=await fetcher(`/api/documents/${doc.id}/pages?${query}`,{signal:controller.signal});
        if(!response.ok)throw new Error('PDF preview unavailable');
        const result=await response.json();
        if(stopped)return;
        if(result.width!==resolution||result.pages?.length!==count||result.pages.some((item,i)=>item.page!==start+i||typeof item.png!=='string'))throw new Error('Incomplete PDF batch');
        for(const item of result.pages){
          const bytes=Uint8Array.from(atob(item.png),value=>value.charCodeAt(0));
          const url=URLs.createObjectURL(new Blob([bytes],{type:'image/png'}));
          const image=pages[item.page-1].querySelector('img');
          image.src=url;
          if(urls.has(item.page))URLs.revokeObjectURL(urls.get(item.page));
          urls.set(item.page,url);loaded.set(item.page,resolution);
        }
      }catch(error){
        if(stopped||error.name==='AbortError')return;
        for(let number=start;number<start+count;number++){
          failed.add(`${number}:${resolution}`);
          const status=pages[number-1].querySelector('.pdf-page-loading');
          status.hidden=false;
          status.innerHTML=tr('<p>此页加载失败。<button data-retry-page>重新加载</button></p>');
        }
      }finally{busy=false;enqueue();}
    })();
  }
  const observer=new Observe(entries=>{
    for(const entry of entries){const page=Number(entry.target.dataset.page);if(entry.isIntersecting)nearby.add(page);else nearby.delete(page);}
    enqueue();
  },{root:host,rootMargin:'600px 0px'});
  for(const page of pages)observer.observe(page);
  const resize=new Resize(()=>{clearTimeout(timer);timer=setTimeout(enqueue,100);});
  resize.observe(host);
  const retry=event=>{
    if(!event.target.closest('[data-retry-page]'))return;
    const element=event.target.closest('.pdf-page'),number=Number(element.dataset.page);
    for(const key of failed)if(key.startsWith(`${number}:`))failed.delete(key);
    loaded.delete(number);nearby.add(number);
    element.querySelector('.pdf-page-loading').innerHTML=loadingHTML(tr('正在加载页面…'));
    enqueue();
  };
  host.addEventListener('click',retry);
  return ()=>{
    stopped=true;controller.abort();clearTimeout(timer);observer.disconnect();resize.disconnect();host.removeEventListener('click',retry);
    for(const url of urls.values())URLs.revokeObjectURL(url);
    urls.clear();
  };
}
