import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const section=(start,end)=>app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start)));

test('continuous 200-events/sec input renders throughout instead of waiting for silence',()=>{
 let now=0,next=0;const timers=new Map(),renders=[];
 const context={renderTimer:null,setTimeout(fn,delay){const id=++next;timers.set(id,{fn,at:now+delay});return id;},renderMessages(){renders.push(now);}};
 runInNewContext(section('function scheduleMessages(','\nfunction renderDocs'),context);
 for(now=0;now<1000;now++){
  if(now%5===0)context.scheduleMessages();
  for(const [id,timer] of timers)if(timer.at<=now){timers.delete(id);timer.fn();}
 }
 assert.ok(renders.length>=45,`Only ${renders.length} frames rendered`);
 assert.ok(renders[0]<=20);
 assert.ok(renders.at(-1)>=960);
});

test('text streaming updates just the active block and keeps reading position',()=>{
 const active={innerHTML:'old'},history={querySelector:selector=>selector==='[data-text-part="p"]'?active:null};
 Object.defineProperty(history,'innerHTML',{set(){throw Error('Replaced the entire conversation');}});
 const scroll={scrollHeight:1000,scrollTop:100,clientHeight:200};
 const context={renderTimer:null,clearTimeout(){},$:id=>id==='messageHistory'?history:scroll,streamingParts:new Map([['p','new text']]),fullRender:false,CSS:{escape:s=>s},state:{documents:[]},markdown:s=>'<p>'+s+'</p>'};
 runInNewContext(section('function renderMessages(','\nfunction renderRequests'),context);
 context.renderMessages(true);
 assert.equal(active.innerHTML,'<p>new text</p>');
 assert.equal(scroll.scrollTop,100);
 assert.equal(context.streamingParts.size,0);
});
