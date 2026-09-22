import test from 'node:test';
import assert from 'node:assert/strict';
import {todosHTML,todoSignature} from '../static/agent-ui.js';
import {availableModel,modelOptionsHTML} from '../static/model-picker.js';

const todos=[{content:'Read source',status:'in_progress'},{content:'Save report',status:'pending'}];
function state(){return {todos:structuredClone(todos),status:{type:'idle'},messages:[{info:{id:'u1',role:'user'},parts:[]},{info:{id:'a1',role:'assistant',parentID:'u1',finish:'tool-calls'},parts:[{id:'p1',type:'tool',tool:'todowrite',state:{status:'completed'}}]}]};}
test('trial depletion picks first usable model, preserves a usable choice, and handles empty catalog',()=>{
 const c={selected:'trial/one',trial_remaining:0,models:[{id:'trial/one',label:'Trial'},{id:'own/first',label:'First'},{id:'own/second',label:'Second'}]};
 assert.equal(availableModel(c),'own/first');
 assert.equal(availableModel(c,'own/second'),'own/second');
 assert.equal(availableModel({...c,trial_remaining:1}),'trial/one');
 assert.equal(availableModel({...c,models:c.models.slice(0,1)}),null);
 assert.equal(availableModel({...c,models:[]}),null);
 assert.match(modelOptionsHTML(c),/value="trial\/one" disabled/);
});
test('normal final answer retires stale progress without marking any task complete',()=>{
 const s=state();s.messages.push({info:{id:'a2',role:'assistant',finish:'stop',time:{completed:1}},parts:[]});
 assert.equal(todosHTML(s),'');assert.deepEqual(s.todos,todos);
});
test('failed or length-limited runs retain a dismissible plan and resume action',()=>{
 for(const info of [{error:{name:'APIError'},finish:'stop'},{finish:'length'},{}]){
  const s=state();s.messages.push({info:{id:'a2',role:'assistant',time:{completed:1},...info},parts:[]});
  const html=todosHTML(s);assert.match(html,/data-dismiss-todos/);assert.match(html,/data-resume-todos/);assert.match(html,/已中断/);
 }
});
test('dismissal survives reload and status events; new native plan reappears',()=>{
 const s=state();s.dismissed_todos=todoSignature(s);
 assert.equal(todosHTML(JSON.parse(JSON.stringify(s))),'');
 s.status.type='busy';assert.equal(todosHTML(s),'');
 s.messages[1].parts[0].id='new-tool-call';assert.match(todosHTML(s),/任务清单/);
});
test('previous-turn plan does not become active in an unrelated new request',()=>{
 const s=state();s.messages.push({info:{id:'u2',role:'user'},parts:[]});s.status.type='busy';
 assert.equal(todosHTML(s),'');
});
test('resume never bypasses native permissions, questions, active execution or queued messages',()=>{
 for(const patch of [{questions:[{id:'q'}]},{permissions:[{id:'p'}]},{status:{type:'busy'}},{queue:{active:true}},{queue:{items:[{id:'queued'}]}}]){
  assert.doesNotMatch(todosHTML({...state(),...patch}),/data-resume-todos/);
 }
 for(const status of ['idle','busy']){
  const html=todosHTML({...state(),status:{type:status},permissions:[{id:'p'}]});
  assert.match(html,/等待你的许可/);assert.doesNotMatch(html,/已中断|bui-spin/);
 }
});
