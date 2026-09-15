import test from 'node:test';
import assert from 'node:assert/strict';
import {outlineHTML,watchDocumentOutline} from '../static/document-navigation.js';

test('pending, linked TOC and no-directory states are distinct',()=>{
  assert.match(outlineHTML({status:'pending'}),/正在识别目录/);
  assert.doesNotMatch(outlineHTML({status:'pending'}),/未提供/);
  assert.match(outlineHTML({status:'ready',entries:[]}),/原文未提供可用目录。/);
  assert.match(outlineHTML({status:'ready',source:'pdf-toc-links',entries:[{title:'2.1 建设内容',level:2,page:7}]}),/来自 PDF 目录页/);
});

test('polling waits for completion and then stops',async()=>{
  let calls=0,updates=[];
  const result={status:'ready',entries:[{title:'Payment',page:7}]};
  let complete;const done=new Promise(resolve=>complete=resolve);
  const stop=watchDocumentOutline(async()=>++calls===1?{status:'pending'}:result,value=>{updates.push(value);complete();},1);
  try{
    await done;
    await new Promise(resolve=>setTimeout(resolve,15));
    assert.equal(calls,2);assert.deepEqual(updates,[result]);
  }finally{stop();}
});

test('switching documents aborts polling and ignores a late old result',async()=>{
  let resolve,signal,started;const ready=new Promise(r=>started=r);const updates=[];
  const stop=watchDocumentOutline(s=>{signal=s;started();return new Promise(r=>resolve=r);},value=>updates.push(value),1);
  await ready;stop();resolve({status:'ready',entries:[{title:'Old document'}]});
  await new Promise(r=>setTimeout(r,5));
  assert.equal(signal.aborted,true);assert.deepEqual(updates,[]);
});

test('network failures finish with unavailable rather than an endless spinner',async()=>{
  let calls=0,complete;const done=new Promise(resolve=>complete=resolve);
  const stop=watchDocumentOutline(async()=>{calls++;throw new Error('offline');},complete,1);
  try{assert.equal((await done).unavailable,true);assert.equal(calls,3);}finally{stop();}
});
