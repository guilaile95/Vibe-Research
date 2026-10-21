import assert from 'node:assert/strict';import test from 'node:test';import vm from 'node:vm';import ts from 'typescript';import {readFileSync} from 'node:fs';
function harness({confirmResult=true,capture,generate,history=async()=>[],evidence}={}){const slots=[];let cursor=0;let pending=[];let subject;const calls=[],notes=[],prompts=[];const bundle={bundle_id:'a'.repeat(32),bundle_sha256:'b'.repeat(64),subject:{market:'A',symbol:'600519'},captured_at:'synthetic',sources:[]};const record={run_id:'c'.repeat(32),status:'COMPLETED',stages:[],model:{},subject:bundle.subject};const react={useState(init){const i=cursor++;if(!(i in slots))slots[i]=init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useRef(init){const i=cursor++;return slots[i]??={current:init};},useEffect(effect,deps){const i=cursor++;const old=slots[i];if(!old||deps.some((d,j)=>d!==old.deps[j])){pending.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:effect()};});}}};const exports={};const modules={'./ReverseDcfCard':{ReverseDcfCard:()=>null},react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/llm':{loadLlm:()=>({provider:'deepseek',model:'fixture',baseURL:'https://provider.example/v1',apiKey:'private-fixture'})},'@/lib/notes':{addNote:(...args)=>notes.push(args)},'@/lib/companyResearch':{STAGE_LABELS:{profile:'概况'},captureCompanyResearch:async(...args)=>{calls.push(['capture',...args]);return capture?capture(...args):bundle;},generateCompanyResearch:async(...args)=>{calls.push(['generate',...args]);return generate?generate(...args):record;},readCompanyResearchPage:async(subject,signal,cursor)=>{calls.push(['history',signal,subject,cursor]);const result=await history(signal,subject,cursor);return Array.isArray(result)?{records:result,diagnostics:[],unassigned_corrupt_count:0,next_cursor:null}:result;},readCompanyResearchEvidence:async(...args)=>{calls.push(['evidence',...args]);return evidence?evidence(...args):bundle;},researchNote:()=>'Synthetic draft only'}};const code=ts.transpileModule(readFileSync(new URL('../src/components/research/CompanyResearchPanel.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;vm.runInNewContext(code,{exports,require:n=>modules[n],AbortController,Error,URL,confirm:p=>{prompts.push(p);return confirmResult;}});return{calls,notes,prompts,unmount(){for(const slot of slots)slot?.cleanup?.();},render(nextSubject){subject=nextSubject??subject??bundle.subject;cursor=0;pending=[];let result=exports.CompanyResearchPanel({subject});if(pending.length){pending.forEach(f=>f());cursor=0;pending=[];result=exports.CompanyResearchPanel({subject});}return result;}};}
function nodes(t){return t==null||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];}function text(t){return t==null||typeof t==='boolean'?'':typeof t!=='object'?String(t):Array.isArray(t)?t.map(text).join(''):text(t.props?.children);}function button(t,label){return nodes(t).find(n=>n.type==='button'&&text(n).includes(label));}const tick=()=>new Promise(r=>setImmediate(r));
test('render never fetches or calls model; declined budget sends no model request',async()=>{const h=harness({confirmResult:false});assert.equal(h.calls.length,0);assert.equal(button(h.render(),'确认预算').props.disabled,true);button(h.render(),'采集并冻结').props.onClick();await tick();assert.equal(h.calls.length,1);button(h.render(),'确认预算').props.onClick();await tick();assert.equal(h.calls.length,1);assert.match(h.prompts[0],/最多 6 次/);assert.match(h.prompts[0],/provider.example/);assert.doesNotMatch(h.prompts[0],/private-fixture/);});
test('completed report requires explicit separate save, repeated clicks save once',async()=>{const h=harness();button(h.render(),'采集并冻结').props.onClick();await tick();const start=button(h.render(),'确认预算');start.props.onClick();start.props.onClick();await tick();assert.equal(h.calls.filter(c=>c[0]==='generate').length,1);assert.equal(h.notes.length,0);const save=button(h.render(),'保存完整草稿');save.props.onClick();save.props.onClick();assert.equal(h.notes.length,1);});
test('cancelled generation aborts and ignores late final report',async()=>{let finish;const h=harness({generate:()=>new Promise(r=>{finish=r;})});button(h.render(),'采集并冻结').props.onClick();await tick();button(h.render(),'确认预算').props.onClick();button(h.render(),'取消研究').props.onClick();assert.equal(h.calls[1][4].aborted,true);finish({run_id:'late',status:'COMPLETED'});await tick();assert.equal(button(h.render(),'保存完整草稿'),undefined);assert.equal(h.notes.length,0);});
test('capture and generation errors keep recovery action and never save partial result',async()=>{const h=harness({generate:async()=>{throw new Error('INCOMPLETE');}});button(h.render(),'采集并冻结').props.onClick();await tick();button(h.render(),'确认预算').props.onClick();await tick();assert.match(text(h.render()),/INCOMPLETE/);assert.equal(button(h.render(),'确认预算').props.disabled,false);assert.equal(button(h.render(),'保存完整草稿'),undefined);});

const historyRow = id => ({run_id:id,status:'COMPLETED',started_at:'synthetic',completed_stage_count:6,subject:{market:'A',symbol:'600519'}});
const frozen = {bundle_id:'frozen',bundle_sha256:'fixture',subject:{market:'A',symbol:'600519'},captured_at:'synthetic',sources:[{payload:'<script>alert(1)</script>'}]};
async function loadHistory(h){button(h.render(),'读取已有研究记录').props.onClick();await tick();}
test('history evidence is explicit, separate from capture/model and rendered as text',async()=>{
 const h=harness({history:async()=>[historyRow('one')],evidence:async()=>frozen});
 await loadHistory(h);assert.deepEqual(h.calls.map(c=>c[0]),['history']);
 button(h.render(),'查看该记录冻结资料包').props.onClick();await tick();
 assert.deepEqual(h.calls.map(c=>c[0]),['history','evidence']);
 const view=nodes(h.render()).find(n=>n.props?.['data-testid']==='company-research-frozen-evidence');
 assert.match(text(view),/frozen/);assert.match(text(view),/事实与数字未核验/);
 assert.ok(nodes(view).some(n=>n.type==='pre'&&typeof n.props.children==='string'&&n.props.children.includes('<script>')));
 assert.equal(nodes(view).some(n=>n.type==='script'||n.props?.dangerouslySetInnerHTML),false);
 assert.equal(h.notes.length,0);
 button(h.render(),'关闭冻结资料').props.onClick();assert.doesNotMatch(text(h.render()),/原始冻结证据/);
});
test('selecting another run aborts previous read and ignores late success',async()=>{
 let finish;const h=harness({history:async()=>[historyRow('one'),historyRow('two')],evidence:row=>row.run_id==='one'?new Promise(r=>{finish=r;}):Promise.resolve({...frozen,bundle_id:'second'})});
 await loadHistory(h);button(h.render(),'资料包 · one').props.onClick();button(h.render(),'资料包 · two').props.onClick();await tick();
 assert.equal(h.calls.find(c=>c[0]==='evidence')[2].aborted,true);
 finish({...frozen,bundle_id:'stale'});await tick();assert.match(text(h.render()),/second/);assert.doesNotMatch(text(h.render()),/stale/);
});
for(const change of ['close','history','date','subject','unmount'])test(`pending saved read is fenced on ${change}`,async()=>{
 let finish;const h=harness({history:async()=>[historyRow('one')],evidence:()=>new Promise(r=>{finish=r;})});
 await loadHistory(h);button(h.render(),'查看该记录冻结资料包').props.onClick();
 if(change==='close')button(h.render(),'关闭冻结资料').props.onClick();
 if(change==='history')await loadHistory(h);
 if(change==='date')nodes(h.render()).find(n=>n.type==='input').props.onChange({target:{value:'2026-09-30'}});
 if(change==='subject')h.render({market:'US',symbol:'AAPL'});
 if(change==='unmount')h.unmount();
 assert.equal(h.calls.find(c=>c[0]==='evidence')[2].aborted,true);
 finish({...frozen,bundle_id:'stale'});await tick();assert.doesNotMatch(text(h.render()),/stale|原始冻结证据/);
});
test('late failure cannot replace newer evidence; current errors are sanitized and retryable',async()=>{
 let reject;let count=0;const h=harness({history:async()=>[historyRow('one')],evidence:()=>{count++;if(count===1)return new Promise((_,r)=>{reject=r;});if(count===3)throw new Error('secret https://private.example trace');return Promise.resolve(frozen);}});
 await loadHistory(h);button(h.render(),'查看该记录冻结资料包').props.onClick();button(h.render(),'查看该记录冻结资料包').props.onClick();await tick();reject(new Error('stale secret'));await tick();assert.match(text(h.render()),/原始冻结证据/);assert.doesNotMatch(text(h.render()),/secret/);
 button(h.render(),'查看该记录冻结资料包').props.onClick();await tick();assert.match(text(h.render()),/冻结资料读取失败/);assert.doesNotMatch(text(h.render()),/原始冻结证据|secret|private.example/);
 button(h.render(),'查看该记录冻结资料包').props.onClick();await tick();assert.match(text(h.render()),/原始冻结证据/);
});
for(const change of ['date','subject','unmount'])test(`history list pending is fenced on ${change}`,async()=>{
 let finish;const h=harness({history:()=>new Promise(r=>{finish=r;})});
 button(h.render(),'读取已有研究记录').props.onClick();
 if(change==='date')nodes(h.render()).find(n=>n.type==='input').props.onChange({target:{value:'2026-09-30'}});
 if(change==='subject')h.render({market:'US',symbol:'AAPL'});
 if(change==='unmount')h.unmount();
 assert.equal(h.calls.find(c=>c[0]==='history')[1].aborted,true);
 finish([historyRow('stale-history')]);await tick();assert.doesNotMatch(text(h.render()),/stale-history/);
});
test('starting a new capture cancels the history evidence read',async()=>{
 let finish;const h=harness({history:async()=>[historyRow('one')],evidence:()=>new Promise(r=>{finish=r;})});
 await loadHistory(h);button(h.render(),'查看该记录冻结资料包').props.onClick();button(h.render(),'采集并冻结').props.onClick();await tick();
 assert.equal(h.calls.find(c=>c[0]==='evidence')[2].aborted,true);
 finish({...frozen,bundle_id:'stale'});await tick();assert.doesNotMatch(text(h.render()),/stale|原始冻结证据/);
});

test('subject pagination appends older rows and reports damaged rows',async()=>{
 let calls=0;
 const h=harness({history:async(_signal,subject,cursor)=>{assert.equal(subject.symbol,'600519');calls++;return calls===1?{records:[historyRow('new')],diagnostics:[{run_id:'bad',status:'CORRUPTED_OR_UNSUPPORTED'}],unassigned_corrupt_count:1,next_cursor:'older'}:{records:[historyRow('old')],diagnostics:[],unassigned_corrupt_count:1,next_cursor:null};}});
 await loadHistory(h);assert.match(text(h.render()),/1 条记录损坏/);assert.match(text(h.render()),/无法识别所属股票/);
 button(h.render(),'读取更早一批').props.onClick();await tick();assert.match(text(h.render()),/new/);assert.match(text(h.render()),/old/);assert.equal(button(h.render(),'读取更早一批'),undefined);
 assert.equal(h.calls.filter(c=>c[0]==='history')[1][3],'older');
});
test('late older history page cannot enter a different stock',async()=>{
 let finish,calls=0;
 const h=harness({history:async()=>{calls++;if(calls===1)return{records:[historyRow('new')],diagnostics:[],unassigned_corrupt_count:0,next_cursor:'older'};return new Promise(resolve=>{finish=resolve;});}});
 await loadHistory(h);button(h.render(),'读取更早一批').props.onClick();h.render({market:'US',symbol:'AAPL'});
 finish({records:[historyRow('late-old')],diagnostics:[],unassigned_corrupt_count:0,next_cursor:null});await tick();assert.doesNotMatch(text(h.render()),/late-old/);
});
test('history empty, failed and corrupt are distinct',async()=>{
 const empty=harness();await loadHistory(empty);assert.match(text(empty.render()),/暂无研究记录/);
 const corrupt=harness({history:async()=>({records:[],diagnostics:[{run_id:null,status:'CORRUPTED_OR_UNSUPPORTED'}],unassigned_corrupt_count:0,next_cursor:null})});await loadHistory(corrupt);assert.match(text(corrupt.render()),/记录损坏/);assert.doesNotMatch(text(corrupt.render()),/暂无研究记录/);
 const failed=harness({history:async()=>{throw Error('read failed');}});await loadHistory(failed);assert.match(text(failed.render()),/read failed/);assert.doesNotMatch(text(failed.render()),/暂无研究记录/);
});
test('unassignable damaged archives do not claim definitive empty subject history',async()=>{
 const h=harness({history:async()=>({records:[],diagnostics:[],unassigned_corrupt_count:1,next_cursor:null})});await loadHistory(h);assert.match(text(h.render()),/无法识别所属股票/);assert.doesNotMatch(text(h.render()),/暂无研究记录/);
});
