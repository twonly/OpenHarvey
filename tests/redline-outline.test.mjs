import test from 'node:test';
import assert from 'node:assert/strict';
import {readOutline,headingAt,RedlineOutline} from '../static/redline-outline.js';
const heading=(id,ordinal,title='付款约定',level=1)=>({nodeId:id,nodeType:'heading',ordinal,text:title,headingLevel:level});
test('outline uses current visible headings and native IDs, preserving duplicate titles and levels',()=>{
 const items=[heading('a',0),{nodeId:'body',nodeType:'paragraph',ordinal:1,text:'第一章 看似标题的正文'},heading('b',2,'付款约定',2),heading('deleted',3,''),heading('c',4,'修改后的标题')];
 const doc={find:()=>({total:items.length,items:items.map(b=>({address:{nodeId:b.nodeId},node:{id:'layout-'+b.nodeId}}))}),blocks:{list:({offset,includeText})=>{assert.equal(includeText,true);return {total:items.length,blocks:items.slice(offset,offset+2)};}}};
 const result=readOutline(doc);assert.deepEqual(result.entries.map(e=>e.id),['a','b','c']);assert.equal(result.renderOrdinals.get('layout-b'),2);assert.equal(result.entries[1].level,2);assert.equal(result.entries[2].title,'修改后的标题');
 assert.deepEqual(result.entries[1].address,{kind:'block',nodeType:'heading',nodeId:'b'});
 assert.equal(headingAt(result.entries,1),'a');assert.equal(headingAt(result.entries,2),'b');assert.equal(headingAt(result.entries,-1),null);
});
test('incomplete block pagination fails explicitly rather than presenting a partial outline',()=>{
 assert.throws(()=>readOutline({blocks:{list:()=>({total:10,blocks:[]})}}),/不完整/);
});
function controller(){const c=Object.create(RedlineOutline.prototype);Object.assign(c,{entries:[{id:'a',address:{kind:'block',nodeId:'a',nodeType:'heading'}}],dirty:false,highlight(id){this.selected=id;},invalidate(){this.invalidated=true;}});return c;}
test('navigation uses a native address, checks failure and ignores a superseded reply',async()=>{
 const c=controller();let finish;c.superdoc={navigateTo:target=>{assert.equal(target.nodeId,'a');return new Promise(resolve=>finish=resolve);}};
 const old=c.locate('a');c.navigation++;finish(true);await old;assert.equal(c.selected,undefined);
 c.superdoc.navigateTo=async()=>false;await assert.rejects(c.locate('a'),/无法定位/);assert.equal(c.invalidated,true);assert.equal(c.selected,undefined);assert.equal(c.pinned,false);
 c.superdoc.navigateTo=async()=>true;await c.locate('a');assert.equal(c.selected,'a');assert.equal(c.pinned,true);
});
test('a removed heading is re-read before navigation and never located by matching another title',async()=>{
 const c=controller();c.dirty=true;c.refresh=()=>{c.entries=[];c.dirty=false;};c.superdoc={navigateTo:()=>{throw Error('must not navigate');}};
 await assert.rejects(c.locate('a'),/标题已变化/);
});
test('hidden outline invalidates without scanning the document or scheduling a rebuild',()=>{
 const c=controller();c.host={classList:{contains:()=>false}};c.invalidate=RedlineOutline.prototype.invalidate;c.invalidate();assert.equal(c.dirty,true);assert.equal(c.timer,undefined);
});
