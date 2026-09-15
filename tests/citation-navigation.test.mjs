import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {t as tr,ui} from '../static/i18n.js';
const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const reading=readFileSync(new URL('../static/reading.js',import.meta.url),'utf8');
const cut=(s,a,b)=>s.slice(s.indexOf(a),s.indexOf(b,s.indexOf(a)));
function fixture(){
 const frames=[],nodes={};
 const classes=()=>({add(){},remove(){},toggle(){}});
 const $=id=>nodes[id]??={dataset:{},style:{setProperty(){},getPropertyValue(){}},classList:classes(),scrollTop:0,clientHeight:500,
  setAttribute(){},getBoundingClientRect:()=>({top:0,bottom:500,width:800,height:500}),querySelectorAll:()=>[],addEventListener(){}};
 const document={body:{classList:classes()},querySelector:s=>$(s),querySelectorAll:()=>[],addEventListener(){}};
 const context={$,document,window:{addEventListener(){}},MutationObserver:class{observe(){}},innerWidth:1400,requestAnimationFrame:cb=>frames.push(cb),tr,ui};
 runInNewContext('function setup(){'+cut(reading,"  const pane=$('contextPane');",'\nexport function pdfMarkup')+'\ncontroller=setup();',context);
 const frame=()=>{for(const cb of frames.splice(0))cb();};
 return {...context,context,frame};
}
test('opening source retains comparison mode and does not restore the stacked workspace',()=>{
 const {$,context}=fixture();
 // Exercise the same mode action as a user pressing the layout button.
 runInNewContext("",context);
 // A second factory exposes apply only to drive the UI action in this isolated DOM.
 const code='function setup(){'+cut(reading,"  const pane=$('contextPane');",'\nexport function pdfMarkup').replace('return {showSource()', 'return {apply,showSource()')+'\ncontroller=setup();';
 runInNewContext(code,context);
 context.controller.apply('compare');context.controller.showSource();
 assert.equal($('contextPane').dataset.layout,'compare');assert.equal($('contextPane').dataset.sourceHidden,'false');
 context.controller.apply('source');context.controller.showSource();assert.equal($('contextPane').dataset.layout,'source');
 context.controller.apply('artifact');context.controller.showSource();assert.equal($('contextPane').dataset.layout,'compare');
});
test('citation waits for layout restoration then scrolls only its source container',async()=>{
 const {$,context,frame}=fixture();let highlighted=false;
 const target={classList:{add:()=>{highlighted=true;}},getBoundingClientRect:()=>({top:1100,height:20})};
 const host=$('sourceContent');host.querySelector=()=>target;host.scrollTo=({top})=>{host.scrollTop=top;};
 Object.assign(context,{epoch:1,citationEpoch:0,sourceRendered:true,sourceRequest:null,reading:context.controller,
  state:{documents:[{id:'d',source_hash:'hash'}]},source:{id:'d',source_hash:'hash',filename:'contract',segments:[{id:'B0',text:'target'}]},renderSource:async()=>{}});
 runInNewContext(cut(app,'async function navigateCitation(','\nasync function openArtifact'),context);
 context.requestAnimationFrame(()=>{host.scrollTop=40;});
 const navigation=context.navigateCitation('d','B0','hash');assert.equal(highlighted,false);
 frame();await navigation;assert.equal(highlighted,true);assert.equal(host.scrollTop,900);
});
test('a citation from a previous conversation cannot scroll the newly selected document',async()=>{
 const {$,context,frame}=fixture();let resolve;
 Object.assign(context,{epoch:1,citationEpoch:0,sourceRendered:false,sourceRequest:null,reading:context.controller,source:null,
 state:{documents:[{id:'d',source_hash:'hash'}]},loadSource:()=>new Promise(r=>{resolve=r;})});
 runInNewContext(cut(app,'async function navigateCitation(','\nasync function openArtifact'),context);
 const navigation=context.navigateCitation('d','B0','hash');context.epoch=2;resolve();await navigation;
 frame();assert.equal($('sourceContent').scrollTop,0);
});
