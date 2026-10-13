import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {create} from 'zustand';
import * as react from 'react';
import * as jsx from 'react/jsx-runtime';
import {renderToStaticMarkup} from 'react-dom/server';
import * as contract from '../src/lib/shortlineReview.ts';

const day='2026-07-23',id='a'.repeat(32),hash='b'.repeat(64),ids=contract.reviewIds('daily');
const preview={schema_version:'shortline-segmented-review.v1',mode:'daily',trade_date:day,bundle_id:hash,days:[day],selection_mode:'CURRENT_STORED_POSTHOC',point_in_time_claim:'NONE',canonical_authority:false,model_calls_performed:0,max_model_calls:6,available:true,sections:ids.map(x=>({id:x,label:x,evidence_count:1,gaps:[],omitted_count:0,source_identities:[hash],origins:['FIXTURE']})),limitations:[]};
const result=()=>({schema_version:'shortline-segmented-review.v1',generation_id:id,mode:'daily',trade_date:day,bundle:{schema_version:'shortline-segmented-review.v1',mode:'daily',trade_date:day,days:[day],bundle_id:hash,sections:ids.map(x=>({id:x,label:x,evidence:[],gaps:[],omitted_count:0})),selection_mode:'CURRENT_STORED_POSTHOC',point_in_time_claim:'NONE',canonical_authority:false},stages:[...ids,'summary'].map(x=>({id:x,label:x,status:'generated',text:'synthetic',audit:{status:'no_detected_issue_not_verified',reason_codes:[],unknown_reference_count:0,arithmetic_warning_count:0,unbound_number_count:0,fact_verification:'NOT_PERFORMED'},reason_codes:[],evidence_ids:[],bundle_id:hash})),created_at:'2026-07-23T08:00:00Z',model_provider:'fixture',model_name:'fixture',status:'generated_unverified',fact_verification:'NOT_PERFORMED'});
function load(relative,dependencies){const exports={};const source=readFileSync(new URL(relative,import.meta.url),'utf8');const code=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;vm.runInNewContext(code,{exports,AbortController,crypto:{randomUUID:()=>id},require:n=>{if(n in dependencies)return dependencies[n];throw Error('unexpected import '+n)}});return exports;}
class ApiError extends Error{}
const complete=on=>{for(const x of [...ids,'summary']){on({type:'stage',id:x,label:x});on({type:'stage_done',stage:{id:x,bundle_id:hash}});}on({type:'done',generation_id:id,bundle_id:hash});};
function task(stream,request=async()=>result()) {return load('../src/stores/shortlineReviewTaskStore.ts',{'zustand':{create},'@/lib/api':{request,ApiError},'@/lib/ndjson':{streamNdjson:stream},'@/stores/dailyReviewAiTaskStore':{makeStreamLlmConfig:x=>x},'@/lib/shortlineReview':contract}).useShortlineReviewTaskStore;}

test('manual six-call plan completes only after immutable version readback',async()=>{
 let requests=0;const store=task(async(url,body,on)=>{requests++;assert.equal(url,'/api/shortline-review/generate');assert.equal(body.bundle_id,hash);complete(on);});
 assert.equal(requests,0);await store.getState().start(preview,{model:'fixture'});assert.equal(requests,1);assert.equal(store.getState().result.generation_id,id);assert.equal(store.getState().running,false);
});
test('cancel and late completions cannot replace current task',async()=>{
 let resume;let aborted=false;const store=task(async(_u,_b,on,signal)=>{signal.addEventListener('abort',()=>aborted=true);await new Promise(r=>resume=r);complete(on);});
 const run=store.getState().start(preview,{model:'fixture'});store.getState().cancel();resume();await run;
 assert.equal(aborted,true);assert.equal(store.getState().result,null);assert.equal(store.getState().running,false);
});
test('incomplete, reordered and wrong restored identities fail closed',async()=>{
 for(const stream of [async()=>{},async(_u,_b,on)=>{on({type:'stage_done',stage:{id:'summary',bundle_id:hash}});complete(on);}]){
  const store=task(stream);await store.getState().start(preview,{model:'fixture'});assert.equal(store.getState().result,null);assert.ok(store.getState().error);
 }
 const store=task(async(_u,_b,on)=>complete(on),async()=>({...result(),trade_date:'2026-07-24'}));await store.getState().start(preview,{model:'fixture'});assert.equal(store.getState().result,null);
});
test('production card exposes manual budget and never auto-generates on render',()=>{
 const store=task(async()=>assert.fail('render must not start model'));
 const {ShortlineReviewCard}=load('../src/components/dailyReview/ShortlineReviewCard.tsx',{'react':react,'react/jsx-runtime':jsx,'@/components/ui/GlassCard':{GlassCard:({children,...p})=>react.createElement('div',p,children)},'@/lib/api':{request:async()=>[]},'@/lib/llm':{loadLlm:()=>null},'@/lib/shortlineReview':contract,'@/stores/shortlineReviewTaskStore':{useShortlineReviewTaskStore:store}});
 const html=renderToStaticMarkup(react.createElement(ShortlineReviewCard,{tradeDate:day}));assert.match(html,/最多6次/);assert.match(html,/查看生成材料/);assert.match(html,/暂无已保存版本/);assert.match(html,/PIT未证明/);
 const page=readFileSync(new URL('../src/pages/DailyReview.tsx',import.meta.url),'utf8');assert.ok(page.includes('<ShortlineReviewCard tradeDate={dr?.trade_date ?? null} />'));assert.ok(page.includes('<ShortlineReviewCard tradeDate={snap.trade_date ?? null} />'));
});


test('whole transport guards reject malformed rendered fields and permit recovery',()=>{
 assert.equal(contract.ownsPreview(preview,day,'daily'),true);
 for(const mutate of [p=>p.days={},p=>p.sections[0].label={},p=>p.sections[0].gaps=[{}],p=>p.sections[0].origins=[{}]]){
  const bad=structuredClone(preview);mutate(bad);assert.equal(contract.ownsPreview(bad,day,'daily'),false);
 }
 const valid=result();assert.equal(contract.ownsReview(valid,day,'daily'),true);
 for(const mutate of [v=>v.stages[0].label={},v=>v.model_name={},v=>v.created_at='2026-02-30T00:00:00Z',v=>v.bundle.sections[0].evidence=[{}],v=>v.stages[0].audit.reason_codes=[{}]]){
  const bad=structuredClone(valid);mutate(bad);assert.equal(contract.ownsReview(bad,day,'daily'),false);
 }
 const meta={generation_id:id,mode:'daily',trade_date:day,created_at:valid.created_at,status:valid.status};
 assert.equal(contract.ownsVersionList([meta],day,'daily'),true);assert.equal(contract.ownsVersionList([{...meta,created_at:{}}],day,'daily'),false);
 assert.equal(contract.ownsReview(valid,day,'daily'),true);
});

test('production JSX rejects malformed preview and list then recovers to valid preview',async()=>{
 let state=[],cursor=0,effects=[],reply=structuredClone(preview),list=[{generation_id:id,mode:'daily',trade_date:day,created_at:{},status:'generated_unverified'}];
 const hooks={...react,useState:initial=>{const i=cursor++;if(!(i in state))state[i]=initial;return[state[i],v=>{state[i]=v}]},useRef:initial=>{const i=cursor++;if(!(i in state))state[i]={current:initial};return state[i]},useEffect:fn=>{effects.push(fn)}};
 const store=()=>({key:null,running:false,result:null,error:'',start:()=>assert.fail('no model'),cancel:()=>{}});
 const {ShortlineReviewCard}=load('../src/components/dailyReview/ShortlineReviewCard.tsx',{'react':hooks,'react/jsx-runtime':jsx,'@/components/ui/GlassCard':{GlassCard:({children,...p})=>react.createElement('div',p,children)},'@/lib/api':{request:async url=>url.includes('/versions?')?list:reply},'@/lib/llm':{loadLlm:()=>null},'@/lib/shortlineReview':contract,'@/stores/shortlineReviewTaskStore':{useShortlineReviewTaskStore:store}});
 const render=()=>{cursor=0;return ShortlineReviewCard({tradeDate:day})};
 const nodes=x=>!x||typeof x!=='object'?[]:[x,...react.Children.toArray(x.props?.children).flatMap(nodes)];
 let tree=render();effects[0]();await new Promise(r=>setTimeout(r,0));tree=render();assert.match(renderToStaticMarkup(tree),/历史版本暂不可读取/);
 reply.days={};nodes(tree).find(x=>x.type==='button'&&x.props.children==='查看生成材料').props.onClick();await new Promise(r=>setTimeout(r,0));tree=render();assert.match(renderToStaticMarkup(tree),/材料预览暂不可用/);
 reply=structuredClone(preview);nodes(tree).find(x=>x.type==='button'&&x.props.children==='查看生成材料').props.onClick();await new Promise(r=>setTimeout(r,0));tree=render();assert.match(renderToStaticMarkup(tree),/本次材料范围/);assert.doesNotMatch(renderToStaticMarkup(tree),/材料预览暂不可用/);
 list=[{generation_id:id,mode:'daily',trade_date:day,created_at:result().created_at,status:'generated_unverified'}];effects.at(-1)();await new Promise(r=>setTimeout(r,0));tree=render();
 reply=result();reply.created_at={};nodes(tree).find(x=>x.type==='select'&&x.props['aria-label']==='选择复盘版本').props.onChange({target:{value:id}});await new Promise(r=>setTimeout(r,0));tree=render();assert.match(renderToStaticMarkup(tree),/版本身份或内容无法核对/);
 reply=result();nodes(tree).find(x=>x.type==='select'&&x.props['aria-label']==='选择复盘版本').props.onChange({target:{value:id}});await new Promise(r=>setTimeout(r,0));tree=render();assert.match(renderToStaticMarkup(tree),/事实核验未执行/);assert.doesNotMatch(renderToStaticMarkup(tree),/版本身份或内容无法核对/);
});

for(const lateError of [false,true])test(`clearing selected version invalidates late ${lateError?'error':'success'} from production card`,async()=>{
 let state=[],cursor=0,effect,resolve,reject;
 const hooks={...react,useState:initial=>{const i=cursor++;if(!(i in state))state[i]=initial;return[state[i],v=>{state[i]=v}]},useRef:initial=>{const i=cursor++;if(!(i in state))state[i]={current:initial};return state[i]},useEffect:fn=>{effect=fn}};
 const {ShortlineReviewCard}=load('../src/components/dailyReview/ShortlineReviewCard.tsx',{'react':hooks,'react/jsx-runtime':jsx,'@/components/ui/GlassCard':{GlassCard:({children,...p})=>react.createElement('div',p,children)},'@/lib/api':{request:url=>url.includes('/versions?')?Promise.resolve([]):new Promise((a,b)=>{resolve=a;reject=b;})},'@/lib/llm':{loadLlm:()=>null},'@/lib/shortlineReview':contract,'@/stores/shortlineReviewTaskStore':{useShortlineReviewTaskStore:()=>({key:null,running:false,result:null,error:''})}});
 const render=()=>{cursor=0;return ShortlineReviewCard({tradeDate:day})};
 const nodes=x=>!x||typeof x!=='object'?[]:[x,...react.Children.toArray(x.props?.children).flatMap(nodes)];
 render();effect();await new Promise(r=>setTimeout(r,0));let tree=render();
 const select=()=>nodes(tree).find(x=>x.type==='select'&&x.props['aria-label']==='选择复盘版本');
 select().props.onChange({target:{value:id}});tree=render();select().props.onChange({target:{value:''}});
 if(lateError)reject(Error('late old request'));else resolve(result());
 await new Promise(r=>setTimeout(r,0));tree=render();
 assert.equal(select().props.value,'');assert.doesNotMatch(renderToStaticMarkup(tree),/事实核验未执行|版本身份或内容无法核对/);
});

for(const value of ['',id])test(`version ${value?'selection':'clear'} releases superseded preview loading`,async()=>{
 let state=[],cursor=0,effect,release;
 const hooks={...react,useState:initial=>{const i=cursor++;if(!(i in state))state[i]=initial;return[state[i],v=>{state[i]=v}]},useRef:initial=>{const i=cursor++;if(!(i in state))state[i]={current:initial};return state[i]},useEffect:fn=>{effect=fn}};
 const {ShortlineReviewCard}=load('../src/components/dailyReview/ShortlineReviewCard.tsx',{'react':hooks,'react/jsx-runtime':jsx,'@/components/ui/GlassCard':{GlassCard:({children,...p})=>react.createElement('div',p,children)},'@/lib/api':{request:url=>url.includes('/preview?')?new Promise(r=>release=r):Promise.resolve(url.includes('/versions?')?[]:result())},'@/lib/llm':{loadLlm:()=>null},'@/lib/shortlineReview':contract,'@/stores/shortlineReviewTaskStore':{useShortlineReviewTaskStore:()=>({key:null,running:false,result:null,error:''})}});
 const render=()=>{cursor=0;return ShortlineReviewCard({tradeDate:day})};const nodes=x=>!x||typeof x!=='object'?[]:[x,...react.Children.toArray(x.props?.children).flatMap(nodes)];
 render();effect();await new Promise(r=>setTimeout(r,0));let tree=render();nodes(tree).find(x=>x.type==='button'&&x.props.children==='查看生成材料').props.onClick();tree=render();assert.ok(nodes(tree).find(x=>x.type==='button'&&x.props.children==='读取材料…').props.disabled);
 nodes(tree).find(x=>x.type==='select'&&x.props['aria-label']==='选择复盘版本').props.onChange({target:{value}});release(preview);await new Promise(r=>setTimeout(r,0));tree=render();
 assert.equal(nodes(tree).find(x=>x.type==='button'&&x.props.children==='查看生成材料')?.props.disabled,false);
});

test('production cancelled replacement clears preview and requires explicit reread without model retry',async()=>{
 let state=[],cursor=0,pendingEffects=[],dependencies=[],cleanups=[],requests=0,release;
 const store=task(async()=>{requests++;await new Promise(resolve=>release=resolve);});
 store.setState({key:`daily:${day}`,result:result()});
 const hooks={...react,
  useState:initial=>{const i=cursor++;if(!(i in state))state[i]=initial;return[state[i],v=>{state[i]=typeof v==='function'?v(state[i]):v}]},
  useRef:initial=>{const i=cursor++;if(!(i in state))state[i]={current:initial};return state[i]},
  useEffect:(fn,deps)=>{const i=cursor++;if(!dependencies[i]||deps.some((v,j)=>v!==dependencies[i][j])){dependencies[i]=deps;pendingEffects.push(()=>{cleanups[i]?.();cleanups[i]=fn();});}},
 };
 const {ShortlineReviewCard}=load('../src/components/dailyReview/ShortlineReviewCard.tsx',{'react':hooks,'react/jsx-runtime':jsx,'@/components/ui/GlassCard':{GlassCard:({children,...p})=>react.createElement('div',p,children)},'@/lib/api':{request:async url=>url.includes('/preview?')?structuredClone(preview):[]},'@/lib/llm':{loadLlm:()=>({model:'fixture'})},'@/lib/shortlineReview':contract,'@/stores/shortlineReviewTaskStore':{useShortlineReviewTaskStore:()=>store.getState()}});
 const render=()=>{cursor=0;return ShortlineReviewCard({tradeDate:day})};
 const commit=async()=>{let tree=render();for(const effect of pendingEffects.splice(0))effect();await new Promise(setImmediate);return render();};
 const nodes=x=>!x||typeof x!=='object'?[]:[x,...react.Children.toArray(x.props?.children).flatMap(nodes)];
 const button=(tree,text)=>nodes(tree).find(x=>x.type==='button'&&react.Children.toArray(x.props.children).join('')===text);
 let tree=await commit();
 button(tree,'查看生成材料').props.onClick();tree=await commit();
 assert.equal(button(tree,'手动生成（最多6次）').props.disabled,false,renderToStaticMarkup(tree));
 button(tree,'手动生成（最多6次）').props.onClick();tree=await commit();
 assert.equal(requests,1);assert.equal(store.getState().result,null);
 button(tree,'取消当前分段任务').props.onClick();release();tree=await commit();
 assert.equal(store.getState().running,false);
 assert.equal(button(tree,'手动生成（最多6次）').props.disabled,true);
 assert.doesNotMatch(renderToStaticMarkup(tree),/本次材料范围/);
 assert.equal(button(tree,'查看生成材料').props.disabled,false);
 button(tree,'查看生成材料').props.onClick();tree=await commit();
 assert.equal(button(tree,'手动生成（最多6次）').props.disabled,false);
 assert.equal(requests,1,'explicit material reread never implicitly invokes another model');
});
