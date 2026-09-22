// Isolated DOCX worker. Only the Python host supplies paths; no network or LLM.
import {Editor} from 'superdoc/super-editor';
import fs from 'node:fs/promises';

export function checked(result) {
  const receipt = result?.receipt ?? result;
  if (receipt?.success !== true) throw new Error(receipt?.failure?.message || '文档引擎未确认操作成功');
  return receipt;
}

async function all(list, extra={}) {
  const items=[];
  for (;;) {
    const page=await list({...extra,limit:100,offset:items.length});
    items.push(...page.items);
    if (items.length>=page.total) return items;
    if (!page.items.length) throw new Error('文档列表不完整');
  }
}

// SuperDoc 1.46.3 search treats tracked deletions as barriers, so a visible
// sentence spanning old/new runs can fail query.match. Supplement native matches
// using the Document API's visible block projection and public block-local offsets.
// Never infer offsets for embedded objects/fields or use DOM/OOXML addresses.
async function visibleMatches(doc, quote) {
  if(typeof quote!=='string'||!quote.trim())throw new Error('需要当前版本的逐字原文');
  const native=await doc.query.match({select:{type:'text',pattern:quote,caseSensitive:true},require:'any',limit:10000});
  if(/[\r\n]/.test(quote))return native;
  const items=[...native.items];
  const blocks=await all(p=>doc.find({...p,select:{type:'node',kind:'block'}}));
  for(const {node,address} of blocks){
    if(!['paragraph','heading'].includes(address.nodeType))continue;
    const content=node?.paragraph||node?.heading;
    if(!content?.inlines?.every(n=>n.kind==='run'&&typeof n.run?.text==='string'))continue;
    const text=content.inlines.map(n=>n.run.text).join('');
    let start=text.indexOf(quote);
    while(start!==-1){
      const end=start+quote.length,blockId=address.nodeId;
      if(!items.some(m=>m.target?.start.blockId===blockId&&m.target.start.offset===start&&m.target.end.blockId===blockId&&m.target.end.offset===end))
        items.push({id:`visible:${items.length}`,address,snippet:text,target:{kind:'selection',start:{kind:'text',blockId,offset:start},end:{kind:'text',blockId,offset:end}}});
      start=text.indexOf(quote,start+1);
    }
  }
  return {...native,items,total:Math.max(native.total,items.length)};
}

export async function execute(input) {
  let editor, doc;
  try {
    editor=await Editor.open(await fs.readFile(input.source),{user:input.author,telemetry:{enabled:false},isCommentsEnabled:true});
    doc=editor.doc;
    const receipts=[];
    const find=async change=>{
      if (typeof change.quote!=='string'||!change.quote.trim()) throw new Error('需要当前版本的逐字原文');
      const q=await visibleMatches(doc,change.quote);
      const items=q.items.filter(x=>!change.block_id||x.address?.nodeId===change.block_id);
      if(!items.length) throw new Error('TARGET_NOT_FOUND：当前可见文本中未找到此原文。请读取最新条款；未决删除的文字不参与搜索。');
      if(items.length!==1||q.total>q.items.length) throw new Error('AMBIGUOUS_TARGET：原文存在多处匹配，请指定 block_id。');
      if(change.context&&!items[0].snippet.includes(change.context)) throw new Error('条款上下文已变化，请重新读取');
      return items[0];
    };
    if(input.action==='find') return {ok:true,text_view:'visible',matches:await visibleMatches(doc,input.quote)};
    if(input.action==='apply') {
      if(!Array.isArray(input.changes)||!input.changes.length||input.changes.length>50) throw new Error('每次修改需要 1–50 个目标');
      // v1.46.3 cannot round-trip paragraph-boundary revisions reliably. Reject
      // the entire operation before replacing any text or superseding suggestions.
      if(input.changes.some(c=>c.type==='merge_paragraphs'||/[\r\n]/.test(c.quote||'')||/[\r\n]/.test(c.replacement||'')))
        throw new Error('UNSUPPORTED_PARAGRAPH_MERGE：当前引擎无法可靠保存跨段落合并或拆分的原生修订。本次未修改文档；请在 Word/WPS 中调整段落，不要拆成删除重写或反复尝试。');
      for(const change of input.changes) {
        // Earlier operations remain in this disposable copy only. No output is
        // saved if any later operation fails; atomicity is at the file boundary.
        if(change.supersedes?.length) for(const id of change.supersedes) receipts.push(checked(await doc.trackChanges.decide({decision:'reject',target:{kind:'id',id}})));
        if(!['replace','delete','insert_before','insert_after',undefined].includes(change.type))throw new Error('不支持的修改类型');
        const match=await find(change);
        if(match.target.start.blockId!==match.target.end.blockId) throw new Error('UNSUPPORTED_PARAGRAPH_MERGE：跨段落修订暂不支持，本次未保存。');
        const params={target:match.target};
        let result;
        if(change.type==='delete') result=await doc.delete(params,{changeMode:'tracked'});
        else if(['insert_before','insert_after'].includes(change.type)) {
          const point=change.type==='insert_before'?match.target.start:match.target.end;
          result=await doc.insert({...params,target:{...match.target,start:point,end:point},value:change.replacement},{changeMode:'tracked'});
        } else result=await doc.replace({...params,text:change.replacement},{changeMode:'tracked'});
        receipts.push(checked(result));
      }
    } else if(input.action==='decide') {
      if(!['accept','reject'].includes(input.decision)) throw new Error('无效修订决定');
      const ids=input.ids;
      if(!Array.isArray(ids)||!ids.length) throw new Error('请明确选择修订');
      for(const id of ids) receipts.push(checked(await doc.trackChanges.decide({decision:input.decision,target:{kind:'id',id}})));
    } else if(input.action==='comment') {
      if(input.operation==='create') receipts.push(checked(await doc.comments.create({text:input.text,target:(await find(input)).target})));
      else if(input.operation==='reply') receipts.push(checked(await doc.comments.create({text:input.text,parentId:input.id})));
      else if(input.operation==='resolve'||input.operation==='reopen') receipts.push(checked(await doc.comments.patch({commentId:input.id,status:input.operation==='resolve'?'resolved':'active'})));
      else if(input.operation==='delete') receipts.push(checked(await doc.comments.delete({commentId:input.id})));
      else throw new Error('无效批注操作');
    } else if(!['inspect','export'].includes(input.action)) throw new Error('无效文档操作');

    const changes=await all(p=>doc.trackChanges.list(p));
    let comments=await all(p=>doc.comments.list(p),{includeResolved:true});
    if(input.action==='export'&&input.clean) {
      if(changes.length) throw new Error('还有未处理修订，请先接受或拒绝后再导出清洁版');
      for(const comment of comments) checked(await doc.comments.delete({commentId:comment.id}));
      comments=await all(p=>doc.comments.list(p),{includeResolved:true});
      if(comments.length) throw new Error('批注尚未清理，不能生成清洁版');
    }
    const text=await doc.getText({});
    if(input.output) {
      await fs.writeFile(input.output,await editor.exportDocx());
    }
    return {ok:true,text_view:'visible',text,changes,comments,receipts};
  } finally {editor?.destroy();}
}

if(process.argv[1]===new URL(import.meta.url).pathname) {
  let raw=''; for await(const chunk of process.stdin) raw+=chunk;
  try {process.stdout.write(JSON.stringify(await execute(JSON.parse(raw))));}
  catch(e) {process.stdout.write(JSON.stringify({ok:false,error:e.message}));process.exitCode=1;}
}
