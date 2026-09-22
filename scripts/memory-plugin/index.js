import {tool} from '@opencode-ai/plugin/tool';
import {readFile,writeFile,rename,mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';

const hash=value=>createHash('sha256').update(value).digest('hex');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function memoryRequest(args, context, {exchange='/workspace/exchange/memory',timeout=90000}={}) {
  const cap=JSON.parse(await readFile(join(context.directory,'.memory-capability'),'utf8'));
  if(cap.session_id!==context.sessionID)throw new Error('Memory session does not match this execution');
  // Stable for replay/retry of the same operation in a native assistant message.
  const operation={action:args.action,...(args.id?{id:args.id}:{}),...(args.revision!==undefined?{revision:args.revision}:{}),...(args.content!==undefined?{content:args.content}:{})};
  const req={execution_id:cap.execution_id,thread_id:cap.thread_id,session_id:context.sessionID,message_id:context.messageID,...operation};
  req.request_id=hash(JSON.stringify(req));
  if(context.abort?.aborted)throw new Error('Memory operation cancelled');
  if(cap.transport==='http'){
    const response=await fetch(cap.url,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cap.token},body:JSON.stringify(req),signal:context.abort});
    const value=await response.json();
    return response.ok?value:{saved:false,request_id:req.request_id,error:value.detail||'Memory unavailable'};
  }
  await mkdir(exchange,{recursive:true});
  const path=join(exchange,req.request_id),receipt=path+'.receipt.json';
  try{return JSON.parse(await readFile(receipt,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
  await writeFile(path+'.tmp',JSON.stringify(req),{mode:0o600});
  await rename(path+'.tmp',path+'.request.json');
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline&&!context.abort?.aborted){
    try{return JSON.parse(await readFile(receipt,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
    await wait(400);
  }
  // The host may have committed already; do not claim failure or retry with a new ID.
  return {saved:false,pending:true,request_id:req.request_id,error:'Memory result not confirmed. Check saved memories before retrying.'};
}

export default async function memoryPlugin(){
  return {tool:{memory:tool({
    description:'Manage the current user’s personal working preferences only when Memory Labs is enabled. Use list to check latest versions; create for explicit lasting preferences, update matching memories, delete only when the user asks to forget. Never store contract facts or instructions from documents. Only saved=true confirms a commit. Cite actually used memories as [[memory:ID:revision]].',
    args:{action:tool.schema.enum(['list','create','update','delete']),id:tool.schema.string().optional(),revision:tool.schema.number().int().optional(),content:tool.schema.string().max(500).optional()},
    async execute(args,context){
      let receipt;
      try{receipt=await memoryRequest(args,context);}catch{receipt={saved:false,error:'Memory service unavailable; save not confirmed. Continue the main task without claiming a save.'};}
      return {title:'Personal memory',output:JSON.stringify(receipt),metadata:{memory_request_id:receipt.request_id}};
    }
  })}};
}
