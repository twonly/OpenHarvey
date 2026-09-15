import test from 'node:test';
import assert from 'node:assert/strict';
import {t,ui,setLanguage,getLanguage,labels} from '../static/i18n.js';
import english from '../static/locales/en.js';
import {conversationHTML} from '../static/ui-utils.js';
import {riskBoard,decisions,riskCounts} from '../static/risk-ui.js';
import {citations} from '../static/markdown.js';
import {threadListHTML} from '../static/thread-ui.js';
import {toolHTML,todosHTML} from '../static/agent-ui.js';

test('literal localization leaves interpolated document text and names untouched',()=>{
 setLanguage('en');
 const text='保存 <script>bad</script> 合同助手';
 assert.equal(ui`<b>保存</b><p>${text}</p>`,`<b>Save</b><p>${text}</p>`);
 assert.equal(t('Unknown text'), 'Unknown text');
 assert.equal(t(' title="删除附件" '),' title="Delete attachment" ');
 const map=labels({title:'设置'});assert.equal(map.title,'Settings');
 setLanguage('zh-CN');assert.equal(map.title,'设置');
 assert.equal(ui`已选 ${3} 项`,'已选 3 项');
 assert.equal(getLanguage(),'zh-CN');
});

test('English conversation controls retain native messages, tool IDs and source terms',()=>{
 setLanguage('en');
 const content='合同助手：保存、删除是原文。';
 const html=conversationHTML({messages:[{info:{id:'m',role:'assistant',time:{completed:1}},parts:[{type:'text',text:content}]}],status:{type:'idle'},documents:[]});
 assert.ok(html.includes(content));assert.ok(html.includes('Contract assistant'));
 const threads=threadListHTML([{id:'thread',title:'保存',activity:'running'}],'thread');
 assert.match(threads,/保存/);assert.match(threads,/Running/);assert.match(threads,/data-thread="thread"/);
 const tool=toolHTML({id:'p',tool:'read',state:{status:'completed',detail:'中文工具原文'}},false,new Set());
 assert.match(tool,/Read source/);assert.match(tool,/中文工具原文/);
 setLanguage('zh-CN');
});

test('English risk labels never change feedback values, filters or risk counts',()=>{
 setLanguage('en');
 const data={id:'r',findings:[{risk_id:'R1',risk_name:'保存',verdict:'命中',reason:'中文分析保持原样',severity:'高'}]};
 const html=riskBoard(data,[]);
 assert.match(html,/Risk identified/);assert.match(html,/中文分析保持原样/);
 assert.match(html,/data-verdict="命中"/);assert.match(html,/value="接受风险"[^>]*>Accept risk</);
 assert.equal(decisions[0],'待处理');assert.equal(riskCounts(data.findings)['命中'],1);
 setLanguage('zh-CN');
});

test('English source positions keep exact IDs, hashes and quotation previews',()=>{
 setLanguage('en');
 const doc={id:'aaaaaaaaaaaa',filename:'合同.txt',source_hash:'hash',locations:{B1:{ordinal:2,preview:'保存'},B2:{ordinal:3,preview:'删除'}}};
 const html=citations('【Daaaaaaaaaaaa:B1-B2】',[doc]);
 assert.match(html,/Paragraphs 2–3/);assert.match(html,/data-doc="aaaaaaaaaaaa"/);assert.match(html,/data-hash="hash"/);assert.match(html,/保存/);
 setLanguage('zh-CN');
});

test('English catalog has no empty entries and contains the main workflow',()=>{
 for(const [key,value]of Object.entries(english)){assert.ok(key.trim());assert.ok(value.trim(),key);}
 for(const key of ['登录','合同空间','界面语言','保存设置','读取原文','新建 Skill','风险库','模型与服务'])assert.ok(english[key],key);
});

test('editing preferences clears empty fields while retaining unrelated values',async()=>{
 const {readFile}=await import('node:fs/promises');
 const source=await readFile(new URL('../static/settings-ui.js',import.meta.url),'utf8');
 const code=source.slice(source.indexOf('export function preferenceValues'),source.indexOf('export function setupSettings')).replace('export ','');
 const build=new Function(code+';return preferenceValues;')();
 const original={background:'old',model:'provider/model',verbosity:'detailed',ui_language:'zh-CN'};
 assert.deepEqual(build(original,[['background',''],['model',''],['ui_language','en']]),{verbosity:'detailed',ui_language:'en',onboarding_completed:true});
 assert.equal(original.background,'old');
});

test('HTML entry points load imported JavaScript as modules',async()=>{
 const {readFile}=await import('node:fs/promises');
 for(const page of ['index','spaces','ops','guide','demo']){
  const html=await readFile(new URL('../static/'+page+'.html',import.meta.url),'utf8');
  for(const match of html.matchAll(/<script\b([^>]*src="\/static\/([^"?]+)(?:\?[^\"]*)?"[^>]*)>/g)){
   const source=await readFile(new URL('../static/'+match[2],import.meta.url),'utf8');
   if(/^import /m.test(source))assert.match(match[1],/type="module"/,page+' / '+match[2]);
  }
 }
});

test('English demo keeps loading text and forwards its language to the agent',async()=>{
 const {readFile}=await import('node:fs/promises');const {runInNewContext}=await import('node:vm');
 const source=(await readFile(new URL('../static/demo.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
 const elements={status:{textContent:''},startDemo:{hidden:true},demoSpinner:{hidden:false}},calls=[];let destination;
 setLanguage('en');
 runInNewContext(source,{tr:t,getLanguage,document:{getElementById:id=>elements[id]},location:{replace:url=>destination=url},api:path=>new Promise(resolve=>calls.push({path,resolve}))});
 assert.equal(elements.status.textContent,t('正在准备独立的试用空间…'));
 calls[0].resolve({});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(elements.status.textContent,t('正在载入虚构合同示例…'));assert.ok(!/[\u3400-\u9fff]/.test(elements.status.textContent));
 calls[1].resolve({workspace_id:'test-workspace'});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(destination,'/agent?lang=en#test-workspace');setLanguage('zh-CN');
});

test('explicit English entry overrides an older Chinese account preference and survives login',async()=>{
 const {readFile}=await import('node:fs/promises');const {runInNewContext}=await import('node:vm');
 const {requestedLanguage}=await import('../static/i18n.js');
 assert.equal(requestedLanguage('?lang=fr'),null);assert.equal(requestedLanguage('?lang=en'),'en');
 const source=(await readFile(new URL('../static/language-ui.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'').replaceAll('export ','');
 const calls=[],listeners={},logout={hidden:true};let chosen;
 const ctx={getLanguage:()=>chosen,setLanguage:value=>chosen=value,t,requestedLanguage,URL,URLSearchParams,history:{replaceState:(state,title,url)=>{assert.equal(url,'/agent#workspace');}},location:{search:'?lang=en',href:'https://example.com/agent?lang=en#workspace'},localStorage:{getItem:()=> 'zh-CN'},document:{getElementById:()=>logout,querySelectorAll:()=>[],addEventListener:(event,fn)=>listeners[event]=fn},fetch:async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {ok:true,json:async()=>({ui_language:'en'})};}};
 runInNewContext(source+';this.applyLanguage=accountLanguage;',ctx);
 await ctx.applyLanguage({ui_language:'zh-CN'});assert.equal(chosen,'en');assert.equal(calls.length,1);assert.equal(calls[0].body.ui_language,'en');
 listeners['session-expired']();assert.equal(chosen,'en');
 calls.length=0;ctx.location.search='';await ctx.applyLanguage({ui_language:'en'});assert.equal(chosen,'en');assert.equal(calls.length,0);assert.equal(logout.hidden,false);
 await ctx.applyLanguage({ui_language:'en',account_kind:'demo'});assert.equal(logout.hidden,true);
 await ctx.applyLanguage({ui_language:'en',account_kind:'personal'});assert.equal(logout.hidden,false);
});


test('system default conversation titles translate without changing custom titles or stored records',async()=>{
 const {threadTitle}=await import('../static/thread-ui.js');
 const record={id:'t',title:'新对话'};setLanguage('en');
 assert.equal(threadTitle(record.title),'New conversation');assert.match(threadListHTML([record],'t'),/New conversation/);
 for(const title of ['保存','新对话：采购合同','My review'])assert.equal(threadTitle(title),title);
 assert.equal(record.title,'新对话');setLanguage('zh-CN');assert.equal(threadTitle(record.title),'新对话');
});

test('first paint selects English before modules load, including refresh and unavailable storage',async()=>{
 const {readFile}=await import('node:fs/promises');const {runInNewContext}=await import('node:vm');
 const boot=await readFile(new URL('../static/locale-boot.js',import.meta.url),'utf8');
 for(const [search,cached,expected,blocked]of [['?lang=en','zh-CN','en'],['','en','en'],['?lang=zh-CN','en','zh-CN'],['?lang=en',null,'en',true]]){
  const document={documentElement:{}};
  runInNewContext(boot,{document,location:{search},URLSearchParams,navigator:{language:'zh-CN'},localStorage:{getItem:()=>{if(blocked)throw new Error('blocked');return cached;}}});
  assert.equal(document.documentElement.lang,expected);
 }
 for(const page of ['index.html','spaces.html']){
  const html=await readFile(new URL('../static/'+page,import.meta.url),'utf8');
  assert.ok(html.indexOf('/static/locale-boot.js')<html.indexOf('<body'));
  assert.match(html,/data-initial-locale="en">Opening/);assert.match(html,/id="logout" hidden/);
 }
});

test('sign out reaches the complete login page in the current language after server acknowledgement',async()=>{
 const {readFile}=await import('node:fs/promises');const {runInNewContext}=await import('node:vm');
 const source=await readFile(new URL('../static/account-ui.js',import.meta.url),'utf8');
 const fn=source.slice(source.indexOf('export async function signOut()'),source.indexOf('export async function setupAuth')).replace('export ','');
 const calls=[];let reject=false;
 const ctx={api:async(path)=>{calls.push(path);if(reject)throw new Error('offline');},sessionStorage:{clear:()=>calls.push('clear')},location:{replace:url=>calls.push(url)},getLanguage:()=> 'en'};
 runInNewContext(fn,ctx);await ctx.signOut();assert.deepEqual(calls,['/api/logout','clear','/login?lang=en']);
 calls.length=0;reject=true;await assert.rejects(ctx.signOut(),/offline/);assert.deepEqual(calls,['/api/logout']);
});
