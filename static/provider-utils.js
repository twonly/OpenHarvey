import {t as tr} from './i18n.js';
export function addDiscoveredModel(models,id){
  if(models.some(m=>m.id===id))return models;
  const result=models.map(m=>({...m})),blank=result.findIndex(m=>!m.id.trim());
  const model={id,label:id,context:128000,output:8192,enabled:true};
  if(blank>=0)result[blank]={...result[blank],id,label:result[blank].label||id};else result.push(model);
  return result;
}

export async function waitForOperation(id,{read,active=()=>true,pause=()=>new Promise(resolve=>setTimeout(resolve,1000)),limit=600}){
  for(let i=0;i<limit&&active();i++){
    const result=await read(id);
    if(result.status==='completed'||result.status==='failed')return result;
    if(result.status!=='running')throw Error(tr('无法读取操作状态，请重新打开配置查看。'));
    await pause();
  }
  if(active())throw Error(tr('状态查询超时，请刷新页面查看结果，或重新测试连接。'));
  return null;
}
