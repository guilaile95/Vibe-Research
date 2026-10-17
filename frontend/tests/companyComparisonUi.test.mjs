import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
// Actual production JSX and effects, offline synthetic transport only.
function harness(options = {}) {
 const states=[], refs=[], effects=[]; let cursor=0, pending=[], scheduled=true;
 const calls=[], prompts=[], listeners=new Map();
 let subject={market:'US',symbol:'AAPL'};
 const config={provider:'deepseek',model:'synthetic',baseURL:'https://fixture.example/synthetic',apiKey:'synthetic-no-secret'};
 const choices=s=>[{...s,bundle_id:(s.market==='US'?'a':'b').repeat(32),bundle_sha256:'c'.repeat(64),archive_cutoff:'2026-09-30',captured_at:'2026-10-01T00:00:00Z',available_source_count:options.empty?0:1,missing_source_count:1,limitations:[]}];
 const receipt=()=>({model:{provider:'deepseek',name:'synthetic'},started_at:'2026-10-01T00:00:00Z',limits:{max_model_calls:1,max_seconds:90,max_output_tokens:2500},as_of:'2026-09-30',status:'COMPLETED',run_id:'d'.repeat(32),pair_sha256:'e'.repeat(64),subjects:[{...subject,bundle_id:'a'.repeat(32),expected_bundle_sha256:'c'.repeat(64)},{market:'HK',symbol:'00700',bundle_id:'b'.repeat(32),expected_bundle_sha256:'c'.repeat(64)}],evidence:[{sources:[]},{sources:[]}],output:{subjects:[{summary:'FIRST',citations:[],missingness:['UNKNOWN'],caveats:['UNVERIFIED']},{summary:'SECOND',citations:[],missingness:['UNKNOWN'],caveats:['UNVERIFIED']}]}});
 const react={
  useState(init){const i=cursor++;if(!(i in states))states[i]=typeof init==='function'?init():init;return[states[i],v=>{const next=typeof v==='function'?v(states[i]):v;if(!Object.is(next,states[i])){states[i]=next;scheduled=true;}}];},
  useRef(init){const i=cursor++;return refs[i]??={current:init};},
  useEffect(fn,deps){const i=cursor++;if(!effects[i]||deps.some((v,j)=>v!==effects[i].deps[j]))pending.push(()=>{effects[i]?.cleanup?.();effects[i]={deps,cleanup:fn()};});},
 };
 const modules={
  react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'},
  '@/lib/llm':{loadLlm:()=>options.cli?{...config,provider:'cli-codex'}:config,LLM_CHANGED_EVENT:'vr-llm-change'},
  '@/lib/companyComparison':{
   comparisonDayValid:v=>v==='2026-09-30',
   comparisonSubjectValid:s=>!!s.symbol,
   readComparisonBundles:async(s,date,signal)=>{calls.push({kind:'list',s,date,signal});return choices(s);},
   readComparisonBundle:async(c,signal)=>{calls.push({kind:'bundle',c,signal});return{...c,subject:{market:c.market,symbol:c.symbol}};},
   readComparisonEvidence:async(record,index,evidenceId,signal)=>{calls.push({kind:'evidence',record,index,evidenceId,signal});const bundle={subject:record.subjects[index],bundle_id:record.subjects[index].bundle_id,bundle_sha256:record.subjects[index].expected_bundle_sha256,captured_at:'2026-10-01T00:00:00Z',sources:[{evidence_id:'frozen_source',payload:'<script>untrusted frozen payload</script>'}]};return options.evidence?options.evidence(bundle,signal):bundle;},
   generateComparison:(bundles,date,llm,signal)=>{calls.push({kind:'generate',bundles,date,llm,signal});return options.generate?options.generate(receipt(),signal):Promise.resolve(receipt());},
   readComparisonRunPage:async(first,second,date,signal,before)=>{calls.push({kind:'history',first,second,date,signal,before});return {records:options.history?await options.history(receipt(),signal):[receipt()],next_cursor:options.nextCursor??null};},
  },
 };
 const exports={};
 const js=ts.transpileModule(readFileSync(new URL('../src/components/research/CompanyComparisonCard.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(js,{exports,require:n=>modules[n],AbortController,Error,URL,confirm:p=>{prompts.push(p);return options.confirmResult!==false;},window:{addEventListener:(n,fn)=>listeners.set(n,fn),removeEventListener:n=>listeners.delete(n)}});
 const render=()=>{cursor=0;scheduled=false;const tree=exports.CompanyComparisonCard({subject});const run=pending;pending=[];run.forEach(fn=>fn());return tree;};
 const settle=()=>{let n=0;let tree=render();while(scheduled&&n++<20)tree=render();assert.ok(n<20);return tree;};
 return{calls,prompts,render:settle,receipt,changeSubject:s=>{subject=s;return settle();},emit:()=>listeners.get('vr-llm-change')?.(),unmount:()=>effects.forEach(e=>e?.cleanup?.())};
}
function nodes(t){if(t==null||typeof t!=='object')return[];if(Array.isArray(t))return t.flatMap(nodes);if(typeof t.type==='function')return nodes(t.type(t.props));return[t,...nodes(t.props?.children)];}
function text(t){if(t==null||typeof t==='boolean')return'';if(typeof t!=='object')return String(t);if(Array.isArray(t))return t.map(text).join('');if(typeof t.type==='function')return text(t.type(t.props));return text(t.props?.children);}
const button=(h,label)=>nodes(h.render()).find(n=>n.type==='button'&&text(n)===label);
const field=(h,label)=>nodes(h.render()).find(n=>n.props?.['aria-label']===label);
const click=(h,label)=>{const b=button(h,label);assert.ok(b);assert.equal(!!b.props.disabled,false);return b.props.onClick();};
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
async function ready(h){
 h.render();
 field(h,'对比市场').props.onChange({target:{value:'HK'}});
 field(h,'对比代码').props.onChange({target:{value:'00700'}});
 field(h,'对比归档截止日').props.onChange({target:{value:'2026-09-30'}});
 click(h,'读取两股已有资料（不调用模型）');await tick();
 if(!h.calls[0])throw Error('lists were not requested');
}
function select(h){field(h,'对比资料1').props.onChange({target:{value:'a'.repeat(32)}});field(h,'对比资料2').props.onChange({target:{value:'b'.repeat(32)}});}
const start='确认一次调用预算并开始对比';
test('mount never fetches; explicit paired read does not invoke model',async()=>{
 const h=harness();h.render();assert.equal(h.calls.length,0);await ready(h);
 assert.deepEqual(h.calls.map(c=>c.kind),['list','list']);assert.equal(button(h,start).props.disabled,true);
});
test('empty or zero-availability choices stay disabled',async()=>{
 const h=harness({empty:true});await ready(h);select(h);
 assert.equal(button(h,start).props.disabled,true);
 assert.match(text(h.render()),/没有可用的已冻结资料/);
});
test('declined budget and unsupported CLI never read bundles or generate',async()=>{
 for(const options of [{confirmResult:false},{cli:true}]){
  const h=harness(options);await ready(h);select(h);click(h,start);await tick();
  assert.deepEqual(h.calls.map(c=>c.kind),['list','list']);
 }
});
test('explicit confirmation states bounded cost and never discloses key',async()=>{
 const h=harness();await ready(h);select(h);click(h,start);await tick();
 assert.equal(h.calls.filter(c=>c.kind==='generate').length,1);
 assert.match(h.prompts[0],/最多1次模型调用、90秒、2500输出token/);
 assert.match(h.prompts[0],/fixture.example/);assert.doesNotMatch(h.prompts[0],/synthetic-no-secret/);
 assert.match(text(h.render()),/FIRST/);assert.match(text(h.render()),/单位、报告期可比性尚未建立/);
});
test('cancel ignores late success and requires explicit manual retry',async()=>{
 const d=deferred();const h=harness({generate:()=>d.promise});await ready(h);select(h);click(h,start);await tick();
 click(h,'取消对比');const call=h.calls.find(c=>c.kind==='generate');assert.equal(call.signal.aborted,true);
 d.resolve(h.receipt());await tick();assert.doesNotMatch(text(h.render()),/FIRST/);assert.match(text(h.render()),/已取消/);
 assert.equal(h.calls.filter(c=>c.kind==='generate').length,1);
});
test('selected-stock navigation aborts and ignores old finalizer',async()=>{
 const d=deferred();const h=harness({generate:()=>d.promise});await ready(h);select(h);click(h,start);await tick();
 h.changeSubject({market:'A',symbol:'600000'});assert.equal(h.calls.find(c=>c.kind==='generate').signal.aborted,true);
 d.resolve(h.receipt());await tick();assert.doesNotMatch(text(h.render()),/FIRST/);
 assert.equal(field(h,'对比资料1'),undefined);
});
test('model configuration change cancels in-flight generation',async()=>{
 const d=deferred();const h=harness({generate:()=>d.promise});await ready(h);select(h);click(h,start);await tick();h.emit();
 assert.equal(h.calls.find(c=>c.kind==='generate').signal.aborted,true);d.resolve(h.receipt());await tick();
 assert.doesNotMatch(text(h.render()),/FIRST/);assert.match(text(h.render()),/模型配置已变化/);
});
test('history is explicit and stale history cannot refill changed date or stock',async()=>{
 const d=deferred();const h=harness({history:()=>d.promise});await ready(h);
 assert.equal(h.calls.some(c=>c.kind==='history'),false);
 click(h,'读取该配对历史');h.changeSubject({market:'A',symbol:'600000'});
 d.resolve([h.receipt()]);await tick();assert.doesNotMatch(text(h.render()),/FIRST/);
});
test('unmount aborts pending work without model retry',async()=>{
 const d=deferred();const h=harness({generate:()=>d.promise});await ready(h);select(h);click(h,start);await tick();h.unmount();
 assert.equal(h.calls.find(c=>c.kind==='generate').signal.aborted,true);
 d.resolve(h.receipt());await tick();assert.equal(h.calls.filter(c=>c.kind==='generate').length,1);
});

test('same-render double click starts one call and cancelled old finalizer cannot clear retry',async()=>{
 const first=deferred(), second=deferred();let n=0;
 const h=harness({generate:()=>++n===1?first.promise:second.promise});
 await ready(h);select(h);
 const startButton=button(h,start);
 startButton.props.onClick();startButton.props.onClick();await tick();
 assert.equal(h.calls.filter(c=>c.kind==='generate').length,1);
 assert.equal(h.prompts.length,1);
 click(h,'取消对比');click(h,start);await tick();
 assert.equal(h.calls.filter(c=>c.kind==='generate').length,2);
 first.resolve(h.receipt());await tick();
 assert.ok(button(h,'取消对比'));assert.doesNotMatch(text(h.render()),/FIRST/);
 assert.equal(h.calls.filter(c=>c.kind==='generate')[1].signal.aborted,false);
 second.resolve(h.receipt());await tick();assert.match(text(h.render()),/FIRST/);
});

// Exercise production JSX so every native field, including dynamically loaded bundle
// selectors and disabled fields, retains explicit theme colors and picker scheme.
test('native comparison controls preserve theme colors before, after load, and while busy',async()=>{
 const d=deferred();const h=harness({generate:()=>d.promise});
 const check=count=>{
  const controls=nodes(h.render()).filter(n=>['input','select'].includes(n.type));
  assert.equal(controls.length,count);
  for(const control of controls){
   const classes=new Set(control.props.className.split(/\s+/));
   for(const token of ['border-border','bg-background','text-foreground','[color-scheme:dark]','[.light_&]:[color-scheme:light]'])
    assert.ok(classes.has(token),`${control.props['aria-label']} is missing ${token}`);
  }
  return controls;
 };
 check(3);await ready(h);check(5);select(h);click(h,start);await tick();
 assert.ok(check(5).every(control=>control.props.disabled));
 click(h,'取消对比');d.resolve(h.receipt());await tick();check(5);
});

test('comparison foreground/background tokens meet normal-text contrast in both themes',()=>{
 const css=readFileSync(new URL('../src/index.css',import.meta.url),'utf8');
 const luminance=percent=>{const value=percent/100;return value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4;};
 for(const selector of [':root','.light']){
  const block=css.slice(css.indexOf(`${selector} {`)).split('}')[0];
  // The current shared palette is neutral HSL. Fail rather than silently miscalculate a colored replacement.
  const token=name=>{const match=block.match(new RegExp(`--${name}: 0 0% ([\\d.]+)%`));assert.ok(match,`${selector} ${name}`);return luminance(Number(match[1]));};
  const values=[token('foreground'),token('background')].sort((a,b)=>a-b);
  assert.ok((values[1]+0.05)/(values[0]+0.05)>=4.5,`${selector} comparison text contrast`);
 }
});

test('frozen source drilldown is explicit read-only and close does not regenerate',async()=>{
 const h=harness();await ready(h);select(h);click(h,start);await tick();
 assert.equal(h.calls.filter(c=>c.kind==='evidence').length,0);
 click(h,'查看 US:AAPL 冻结资料包');await tick();
 assert.equal(h.calls.filter(c=>c.kind==='evidence').length,1);
 assert.match(text(h.render()),/<script>untrusted frozen payload<\/script>/);
 assert.match(text(h.render()),/实际费用：未知/);
 assert.match(text(h.render()),/配置上限：1次调用 \/ 90秒 \/ 2500输出token/);
 const pre=nodes(h.render()).find(n=>n.type==='pre');assert.equal(typeof pre.props.children,'string');assert.equal(pre.props.dangerouslySetInnerHTML,undefined);
 click(h,'关闭来源详情');assert.doesNotMatch(text(h.render()),/untrusted frozen payload/);
 assert.equal(h.calls.filter(c=>c.kind==='generate').length,1);
});
test('cancelled or navigated source read cannot restore stale payload or clear a newer owner',async()=>{
 const first=deferred(),second=deferred();let n=0,bundles=[];
 const h=harness({evidence:b=>{bundles.push(b);return ++n===1?first.promise:second.promise;}});
 await ready(h);select(h);click(h,start);await tick();
 click(h,'查看 US:AAPL 冻结资料包');click(h,'取消对比');
 click(h,'查看 HK:00700 冻结资料包');
 first.resolve(bundles[0]);await tick();
 assert.ok(button(h,'取消对比'));assert.doesNotMatch(text(h.render()),/untrusted frozen payload/);
 assert.equal(h.calls.filter(c=>c.kind==='evidence')[0].signal.aborted,true);
 h.changeSubject({market:'A',symbol:'600000'});
 second.resolve(bundles[1]);await tick();
 assert.doesNotMatch(text(h.render()),/untrusted frozen payload/);
 assert.equal(h.calls.filter(c=>c.kind==='generate').length,1);
});
