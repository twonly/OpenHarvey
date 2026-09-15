import {t as tr} from './i18n.js';
let ready;
function script(src){
  return new Promise((resolve,reject)=>{
    const node=document.createElement('script');node.src=src;
    node.onload=resolve;node.onerror=()=>{node.remove();reject(new Error(tr('Word 预览组件加载失败')));};
    document.head.append(node);
  });
}
export function prepareWordPreview(){
  ready??=(async()=>{
    if(!window.JSZip)await script('/static/vendor/jszip-3.10.1.min.js');
    if(!window.docx)await script('/static/vendor/docx-preview-0.3.6.min.js');
  })().catch(error=>{ready=null;throw error;});
  return ready;
}
export async function renderWord(blob,host){
  await prepareWordPreview();
  await window.docx.renderAsync(blob,host,null,{inWrapper:true,useBase64URL:true,breakPages:true,ignoreLastRenderedPageBreak:false});
}
