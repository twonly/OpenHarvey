import test from 'node:test';
import assert from 'node:assert/strict';
import {api,confirmSession} from '../static/api.js';

test('session verification distinguishes invalid credentials from a server outage',async()=>{
 for(const [status,expected] of [[200,'valid'],[401,'expired'],[502,'unavailable']]){
  assert.equal(await confirmSession(async(path,options)=>{assert.equal(path,'/api/me');assert.equal(options.cache,'no-store');return new Response('{}',{status});}),expected);
 }
});

test('a delayed 401 does not discard a valid current login; writes are not replayed',async()=>{
 const old={fetch:globalThis.fetch,document:globalThis.document,File:globalThis.File};
 const events=[];globalThis.document={dispatchEvent:e=>events.push(e.type)};globalThis.File=class {};
 try{
  let calls=[];
  globalThis.fetch=async(path,options)=>{calls.push([path,options.method]);return new Response(JSON.stringify({ok:true}),{status:calls.length===1?401:200,headers:{'content-type':'application/json'}});};
  assert.deepEqual(await api('/api/workspaces'),{ok:true});
  assert.deepEqual(calls.map(c=>c[0]),['/api/workspaces','/api/me','/api/workspaces']);assert.deepEqual(events,[]);
  calls=[];
  await assert.rejects(api('/api/threads/x/messages',{method:'POST',body:{text:'hello'}}),e=>e.status===503);
  assert.equal(calls.length,2);assert.deepEqual(events,[]);
  globalThis.fetch=async()=>new Response('{}',{status:401});
  await assert.rejects(api('/api/workspaces'),e=>e.status===401);assert.deepEqual(events,['session-expired']);
  events.length=0;calls=[];
  globalThis.fetch=async()=>{calls.push(1);return new Response('{}',{status:calls.length===1?401:503});};
  await assert.rejects(api('/api/workspaces'),e=>e.status===503);assert.deepEqual(events,[]);
 }finally{Object.assign(globalThis,old);}
});
