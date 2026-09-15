import english from './locales/en.js';

// Only application-authored literals enter these functions. Interpolated values
// (contract text, names, messages, paths, IDs) are never translated.
export const normalizeLanguage=value=>value==='en'?'en':'zh-CN';
export function requestedLanguage(search=''){
  const value=new URLSearchParams(search).get('lang');
  return value==='en'||value==='zh-CN'?value:null;
}
let language='zh-CN';
try{
  const hint=requestedLanguage(globalThis.location?.search||'');
  let guest;try{guest=globalThis.localStorage?.getItem('workbench-ui-language')||globalThis.localStorage?.getItem('workbench-guest-language');}catch{}
  language=normalizeLanguage(hint||guest||(typeof document!=='undefined'&&globalThis.navigator?.language?.startsWith('en')?'en':'zh-CN'));
}catch{}
export const getLanguage=()=>language;
export function t(source){
  if(language!=='en'||typeof source!=='string')return source;
  if(Object.hasOwn(english,source.trim()))return source.replace(source.trim(),english[source.trim()]);
  return source.split(/([<>"'\n\r])/).map(part=>{
    const key=part.trim();return key&&Object.hasOwn(english,key)?part.replace(key,english[key]):part;
  }).join('');
}
export function ui(strings,...values){
  return strings.reduce((result,part,i)=>result+t(part)+(i<values.length?values[i]:''),'');
}
// Module-level label dictionaries must remain responsive to language changes.
export const labels=values=>new Proxy(values,{get:(target,key)=>typeof target[key]==='string'?t(target[key]):Array.isArray(target[key])?target[key].map(t):target[key]});
export function setLanguage(value,{guest=false}={}){
  const next=normalizeLanguage(value),changed=next!==language;language=next;
  try{globalThis.localStorage?.setItem('workbench-ui-language',next);if(guest)globalThis.localStorage?.setItem('workbench-guest-language',next);}catch{}
  if(typeof document!=='undefined'){
    document.documentElement.lang=next;
    localizePage();
    if(changed)document.dispatchEvent(new CustomEvent('ui-language-changed',{detail:next}));
  }
  return next;
}

// Capture the static HTML shell exactly once. Never scan dynamic content or
// observe arbitrary DOM text. A changed node belongs to its renderer instead.
const staticSlots=[];
export function capturePage(root=document){
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  for(let node;node=walker.nextNode();){
    if(node.parentElement?.closest('script,style,pre,code,textarea,[data-no-i18n]'))continue;
    if(/[\u3400-\u9fff]/u.test(node.nodeValue))staticSlots.push({node,source:node.nodeValue,last:node.nodeValue});
  }
  for(const node of root.querySelectorAll('[title],[placeholder],[aria-label],[alt],meta[name="description"]')){
    for(const attr of ['title','placeholder','aria-label','alt',...(node.matches('meta')?['content']:[])]){
      const source=node.getAttribute(attr);if(source&&/[\u3400-\u9fff]/u.test(source))staticSlots.push({node,attr,source,last:source});
    }
  }
  localizePage();
}
export function localizePage(){
  for(const slot of staticSlots){
    const {node,attr,source,last}=slot;
    if(!node.isConnected)continue;
    const current=attr?node.getAttribute(attr):node.nodeValue;
    if(current!==last)continue;
    const next=t(source);if(attr)node.setAttribute(attr,next);else node.nodeValue=next;slot.last=next;
  }
  if(typeof document!=='undefined')document.documentElement.lang=language;
}
if(typeof document!=='undefined')capturePage();
