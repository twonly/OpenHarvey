import {t as tr,ui} from './i18n.js';

const builtin={'contract-summary':'合同摘要','contract-review':'风险审查','contract-redline':'条款修改'};
export function skillLabel(name,skills=[]){
  const item=skills.find(s=>s.name===name),label=item?.label||item?.content?.label;
  return label&&label!==name?label:tr(builtin[name]||'所选 Skill');
}
export function skillCommand(text){return String(text||'').match(/^\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)/);}
export function withoutSkillCommand(text,name){
  const command=skillCommand(text);
  return command&&command[1]===name?text.slice(command[0].length):text;
}
export function skillPrompt(name,skills=[]){return ui`请使用“${skillLabel(name,skills)}”处理当前合同并保存结果。`;}
// Only migrate the exact application-generated prompt, never replace arbitrary user text.
export function skillMessage(text,name,skills=[]){
  if(!name)return text;
  const body=withoutSkillCommand(text,name);
  return body===`请使用 ${name} 处理当前合同并保存结果。`?skillPrompt(name,skills):body;
}
