import test from 'node:test';
import assert from 'node:assert/strict';
import requestParams from '../runtime/plugins/request-params.js';
import {PROVIDER_PRESETS,parseExtraBody} from '../static/provider-presets.js';
test('extra JSON validates objects and preserves false, nesting, and numbers',()=>{
 assert.deepEqual(parseExtraBody(''),{});
 assert.deepEqual(parseExtraBody('{"thinking":{"type":"disabled"},"temperature":0}'),{thinking:{type:'disabled'},temperature:0});
 for(const input of ['[]','null','bad','{"stream":false}','{"model":"other"}'])assert.throws(()=>parseExtraBody(input));
 assert.equal(PROVIDER_PRESETS.find(p=>p.id==='minimax').kind,'anthropic');
});
test('request adapter merges wire body for both protocols and leaves discovery untouched',async()=>{
 for(const path of ['/v1/chat/completions','/v1/messages']){
  let received;
  const config={provider:{custom:{options:{workbenchExtraBody:{temperature:0.2,thinking:{type:'enabled',budget_tokens:1024}},fetch:async(...args)=>{received=args;return 'response';}}}}};
  await (await requestParams()).config(config);
  const init={method:'POST',body:JSON.stringify({model:'one',messages:[{role:'user',content:'hi'}],stream:true,temperature:1}),headers:{authorization:'test'}};
  assert.equal(await config.provider.custom.options.fetch(path,init),'response');
  const body=JSON.parse(received[1].body);
  assert.equal(body.temperature,0.2);assert.equal(body.thinking.budget_tokens,1024);assert.equal(body.model,'one');assert.equal(body.stream,true);
  assert.equal(received[1].headers,init.headers);
  await config.provider.custom.options.fetch('/v1/models',{method:'GET'});
  assert.deepEqual(received[1],{method:'GET'});
 }
});
