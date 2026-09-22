import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import plugin from '../runtime/plugins/memory.js';
import {memoryReferencesHTML,memoryReceiptHTML} from '../static/memory-ui.js';
import {setLanguage} from '../static/i18n.js';
import {conversationHTML} from '../static/ui-utils.js';

test('bundled native tool sends scoped identity, stable retries and never returns the credential',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'memory-plugin-')),prior=globalThis.fetch,requests=[];
 try{
  await writeFile(join(directory,'.memory-capability'),JSON.stringify({execution_id:'execution',thread_id:'thread',session_id:'ses_test',token:'TEST_CAPABILITY',transport:'http',url:'http://local/internal/memory'}));
  globalThis.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({saved:true,request_id:JSON.parse(options.body).request_id,action:'create',item:{id:'memory',revision:1,content:'Short answers'}})};};
  const native=(await plugin()).tool.memory,context={directory,sessionID:'ses_test',messageID:'msg_test',abort:new AbortController().signal};
  const first=await native.execute({action:'create',content:'Short answers'},context);
  const second=await native.execute({action:'create',content:'Short answers'},context);
  assert.equal(first.output,second.output);assert.equal(requests.length,2);
  const payload=JSON.parse(requests[0].options.body);
  assert.equal(payload.message_id,'msg_test');assert.equal(payload.session_id,'ses_test');assert.equal(payload.execution_id,'execution');assert.equal(payload.user_id,undefined);
  assert.equal(requests[0].options.headers.Authorization,'Bearer TEST_CAPABILITY');assert.ok(!JSON.stringify(first).includes('TEST_CAPABILITY'));
  const denied=await native.execute({action:'create',content:'Short answers'},{...context,sessionID:'other'});
  assert.equal(JSON.parse(denied.output).saved,false);assert.equal(requests.length,2);
  globalThis.fetch=async()=>({ok:false,json:async()=>({detail:'Personal memory is paused'})});
  assert.equal(JSON.parse((await native.execute({action:'list'},context)).output).saved,false);
 }finally{globalThis.fetch=prior;await rm(directory,{recursive:true,force:true});}
});

test('memory UI renders only verified receipts, retains history and escapes preference text',()=>{
 setLanguage('en');
 const item={id:'a'.repeat(24),content:'<script>alert(1)</script>',revision:1,current_revision:2,source:'conversation',updated:1};
 const receipt=memoryReceiptHTML({state:{status:'completed',output:'{"saved":true}'}});
 assert.ok(!receipt.includes('Memory saved'));assert.match(receipt,/not yet confirmed/);
 const saved=memoryReceiptHTML({memory_receipt:{saved:true,action:'create',item}});
 assert.match(saved,/Memory saved/);assert.match(saved,/Updated since this answer/);assert.ok(!saved.includes('<script>'));
 const refs=memoryReferencesHTML([{memory_references:[item,item]}]);
 assert.match(refs,/Referenced memories · 1/);
 const deleted=memoryReferencesHTML([{memory_references:[{...item,current_revision:null}]}]);
 assert.match(deleted,/Deleted/);assert.ok(!deleted.includes('data-memory-edit'));
 const html=conversationHTML({messages:[{info:{id:'msg',role:'assistant',time:{completed:1}},parts:[{type:'text',text:'Answer',memory_references:[item]}]}],status:{type:'idle'},documents:[]});
 assert.match(html,/Referenced memories/);setLanguage('zh-CN');
});
