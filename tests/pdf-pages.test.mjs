import test from 'node:test';
import assert from 'node:assert/strict';
import {loadPdfPages,pdfBatch,pdfWidth} from '../static/pdf-pages.js';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(fetcher,total=7){
  const calls=[],revoked=[],listeners={};let observer;
  const pages=Array.from({length:total},(_,i)=>{
    const image={},status={hidden:false,innerHTML:''};
    return {dataset:{page:String(i+1)},clientWidth:600,image,status,querySelector:q=>q==='img'?image:status,getBoundingClientRect:()=>({top:i*800,bottom:(i+1)*800})};
  });
  const host={clientWidth:600,getBoundingClientRect:()=>({top:0,bottom:600}),querySelectorAll:()=>pages,addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:name=>delete listeners[name]};
  const options={fetch:async(...args)=>{calls.push(args);return fetcher(...args);},
    URL:{createObjectURL:()=>`blob:${Math.random()}`,revokeObjectURL:url=>revoked.push(url)},
    IntersectionObserver:class{constructor(cb){this.cb=cb;observer=this;}observe(){}disconnect(){this.closed=true;}},
    ResizeObserver:class{observe(){}disconnect(){}}};
  const stop=loadPdfPages(host,{id:'doc',pages},'thread',options);
  const intersect=numbers=>observer.cb(pages.map((page,i)=>({target:page,isIntersecting:numbers.includes(i+1)})));
  return {calls,pages,stop,intersect,revoked,listeners,observer};
}
function response(url){
  const q=new URL(url,'http://local').searchParams,start=Number(q.get('start')),count=Number(q.get('count'));
  return {ok:true,json:async()=>({width:Number(q.get('width')),pages:Array.from({length:count},(_,i)=>({page:start+i,png:btoa('PNG')}))})};
}
test('batch boundaries and physical resolution stay bounded',()=>{
  assert.deepEqual(pdfBatch(1,122),{start:1,count:3});
  assert.deepEqual(pdfBatch(100,122),{start:100,count:3});
  assert.deepEqual(pdfBatch(122,122),{start:121,count:2});
  assert.equal(pdfWidth(900,2),1920);assert.equal(pdfWidth(1300,3),2880);
});
test('nearby pages share one batch; navigation requests only the destination batch',async()=>{
  const f=fixture(response);
  try{
    f.intersect([1,2]);await tick();
    assert.equal(f.calls.length,1);assert.match(f.calls[0][0],/start=1&count=3/);
    assert.match(f.calls[0][0],/thread_id=thread/);
    assert.ok(f.pages[2].image.src);assert.equal(f.pages[3].image.src,undefined);
    f.intersect([2,3]);await tick();assert.equal(f.calls.length,1);
    f.intersect([7]);await tick();assert.equal(f.calls.length,2);assert.match(f.calls[1][0],/start=7&count=1/);
  }finally{f.stop();}
  assert.equal(f.revoked.length,4);assert.equal(f.observer.closed,true);
});
test('only one batch runs and switching documents aborts and ignores a late response',async()=>{
  let finish;const f=fixture(url=>new Promise(resolve=>finish=()=>resolve(response(url))));
  f.intersect([1,4,7]);assert.equal(f.calls.length,1);
  f.stop();finish();await tick();
  assert.equal(f.calls[0][1].signal.aborted,true);
  assert.equal(f.calls.length,1);assert.equal(f.pages[0].image.src,undefined);
});
test('visible destination loads before nearby prefetch pages',async()=>{
 const f=fixture(response);
 try{
  f.pages[0].getBoundingClientRect=()=>({top:-800,bottom:0});
  f.pages[3].getBoundingClientRect=()=>({top:0,bottom:800});
  f.intersect([1,4]);await tick();assert.match(f.calls[0][0],/start=4&count=3/);
 }finally{f.stop();}
});
test('failed batches expose retry without an automatic request loop',async()=>{
  let failed=true;const f=fixture(url=>failed?{ok:false}:response(url));
  try{
    f.intersect([1]);await tick();assert.equal(f.calls.length,1);assert.match(f.pages[0].status.innerHTML,/data-retry-page/);
    f.intersect([1]);await tick();assert.equal(f.calls.length,1);
    failed=false;
    f.listeners.click({target:{closest:selector=>selector==='.pdf-page'?f.pages[0]:{}}});
    await tick();assert.equal(f.calls.length,2);assert.ok(f.pages[0].image.src);
  }finally{f.stop();}
});
