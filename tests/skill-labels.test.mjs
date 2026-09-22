import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {skillLabel,skillPrompt,skillMessage,skillCommand,withoutSkillCommand} from '../static/skill-labels.js';
import {userMessageHTML} from '../static/ui-utils.js';
import {queueHTML} from '../static/message-queue.js';
const name='u-aa658ff9-tech-clause',skills=[{name,label:'识别技术条款'}];
test('business label replaces native commands in history, pending messages and queue',()=>{
 const text=`/${name}\n请使用 ${name} 处理当前合同并保存结果。`;
 for(const html of [userMessageHTML(text,[],[],skills),userMessageHTML(skillPrompt(name,skills),[],[],skills,name),queueHTML({items:[{id:'1',status:'queued',body:{text,skill:name}}]},[],skills)]){
  assert.match(html,/识别技术条款/);assert.ok(!html.includes(name));
 }
 assert.equal(skillMessage(`/${name}\n重点看验收`,name,skills),'重点看验收');
 assert.equal(skillMessage(`讨论标识 ${name} 的命名`,name,skills),`讨论标识 ${name} 的命名`);
});
test('missing or unsafe labels are safe and never expose native identifier',()=>{
 assert.equal(skillLabel(name),'所选 Skill');
 assert.ok(!userMessageHTML(`/${name}\n正文`).includes(name));
 assert.ok(userMessageHTML(`/${name}\n正文`,[],[],[{name,label:'<img onerror=alert(1)>'}]).includes('&lt;img'));
 assert.equal(skillLabel('contract-summary'),'合同摘要');
});
test('selecting and removing a skill preserves typed instructions with a removable label',()=>{
 const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
 const elements={input:{value:'重点看验收',focus(){}},selectedSkill:{}};
 const context={selectedSkill:null,skillCatalog:skills,$:id=>elements[id],skillLabel,esc:x=>x,icon:()=>'',ui:(s,...v)=>s.reduce((a,p,i)=>a+p+(v[i]||''),''),hideSkillPicker(){},saveDraft(){}};
 const set=source.slice(source.indexOf('function setSkill('),source.indexOf('\n}',source.indexOf('function setSkill('))+2);
 const pick=source.slice(source.indexOf('function pickSkill('),source.indexOf('\n',source.indexOf('function pickSkill(')));
 runInNewContext(set+'\n'+pick+`\npickSkill('${name}')`,context);
 assert.equal(context.selectedSkill,name);assert.equal(elements.input.value,'重点看验收');
 assert.match(elements.selectedSkill.innerHTML,/识别技术条款/);assert.ok(!elements.selectedSkill.innerHTML.includes(name));
 runInNewContext('setSkill(null)',context);assert.equal(context.selectedSkill,null);assert.equal(elements.input.value,'重点看验收');assert.equal(elements.selectedSkill.hidden,true);
 elements.input.value='/tech';runInNewContext(`pickSkill('${name}')`,context);assert.equal(elements.input.value,'');assert.equal(skillPrompt(context.selectedSkill,skills),'请使用“识别技术条款”处理当前合同并保存结果。');
 assert.equal(skillCommand(`/${name} 重点看验收`)[1],name);
});
test('configuration generates native identifier instead of asking user to manage it',()=>{
 const source=readFileSync(new URL('../static/settings-ui.js',import.meta.url),'utf8');
 assert.ok(!source.includes('调用名称'));assert.ok(!source.includes('name="name"'));assert.match(source,/Skill 名称/);
});

test('typed native slash command converts to a business chip without losing instructions',()=>{
 const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
 const input={value:`/${name} 重点看验收`},context={skillCatalog:skills,skillCommand,withoutSkillCommand,$:()=>input,setSkill:s=>context.selected=s,saveDraft(){},renderSkillPicker(){}};
 const start=source.indexOf("$('input').oninput=");
 runInNewContext(source.slice(start,source.indexOf('\n',start)),context);
 input.oninput();assert.equal(context.selected,name);assert.equal(input.value,'重点看验收');
 input.value='补充说明';input.oninput();assert.equal(context.selected,name);assert.equal(input.value,'补充说明');
});
