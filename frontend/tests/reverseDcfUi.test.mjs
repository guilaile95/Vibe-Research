import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
function harness(calculate) {
 const slots=[];let cursor=0,pending=[];const calls=[];
 const react={useState(init){const i=cursor++;if(!(i in slots))slots[i]=typeof init==='function'?init():init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useRef(init){const i=cursor++;return slots[i]??={current:init};},useEffect(effect,deps){const i=cursor++,old=slots[i];if(!old||deps.some((d,j)=>d!==old.deps[j]))pending.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:effect()};});}};
 const modules={react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/reverseDcf':{requiredNumber:value=>{if(!value.trim()||!Number.isFinite(Number(value)))throw new Error('missing');return Number(value);},formatImpliedGrowth:v=>v===null?'不可计算':`${(v*100).toFixed(2)}%`,calculateReverseDcf:async(...args)=>{calls.push(args);return calculate?calculate(...args):{status:'SOLVED',implied_growth:.123456789,sensitivity:[],reason_codes:[],evaluated_on:'2026-10-19'};}}};
 const exports={};const code=ts.transpileModule(readFileSync(new URL('../src/components/research/ReverseDcfCard.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(code,{exports,require:n=>modules[n],AbortController,Error});
 let subject={market:'US',symbol:'TEST'};
 return {calls,render(next){subject=next??subject;cursor=0;pending=[];let tree=exports.ReverseDcfCard({subject});if(pending.length){pending.forEach(f=>f());cursor=0;pending=[];tree=exports.ReverseDcfCard({subject});}return tree;},unmount(){slots.forEach(s=>s?.cleanup?.());}};
}
function nodes(t){return t==null||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];}
function text(t){return t==null||typeof t==='boolean'?'':typeof t!=='object'?String(t):Array.isArray(t)?t.map(text).join(''):text(t.props?.children);}
function fill(h){
 const values=['Synthetic industry','20','Synthetic quote','2026-10-19','100','Synthetic FCFF','2026-09-30','200','Synthetic debt','2026-09-30','100','Synthetic shares','2026-09-30','10','2','5','-90','100','8,10,12','Manual synthetic assumptions'];
 nodes(h.render()).filter(n=>n.type==='input').forEach((n,i)=>n.props.onChange({target:{value:values[i]}}));
 for(const n of nodes(h.render()).filter(n=>n.type==='select')) {const options=nodes(n).filter(x=>x.type==='option');if(options.some(x=>x.props.value==='non_financial'))n.props.onChange({target:{value:'non_financial'}});else if(options.some(x=>x.props.value==='annual_unlevered_fcff'))n.props.onChange({target:{value:'annual_unlevered_fcff'}});else if(options.some(x=>x.props.children==='USD'))n.props.onChange({target:{value:'USD'}});}
}
const submit=h=>nodes(h.render()).find(n=>n.type==='form').props.onSubmit({preventDefault(){}});
const tick=()=>new Promise(r=>setImmediate(r));
test('manual calculator defaults unknown and blank, independent of model generation',()=>{const h=harness();const tree=h.render();assert.equal(h.calls.length,0);assert.equal(nodes(tree).filter(n=>n.type==='input').every(n=>n.props.value===''),true);assert.match(text(tree),/不是预测或买卖建议/);assert.match(text(tree),/未核验/);assert.match(text(tree),/不调用 AI/);});
test('form sends explicit observations and percent assumptions; double submit only once',async()=>{const h=harness();fill(h);submit(h);submit(h);await tick();assert.equal(h.calls.length,1);const p=h.calls[0][0];assert.equal(p.price.value,20);assert.equal(p.fcff.source,'Synthetic FCFF');assert.equal(p.assumptions.wacc,.1);assert.deepEqual([...p.assumptions.sensitivity_wacc],[.08,.1,.12]);assert.equal(p.industry,'non_financial');assert.match(text(h.render()),/12.35%/);});
test('edit aborts pending result and ignores late response',async()=>{let finish;const h=harness(()=>new Promise(r=>finish=r));fill(h);submit(h);const input=nodes(h.render()).find(n=>n.type==='input');input.props.onChange({target:{value:'Changed source'}});assert.equal(h.calls[0][1].aborted,true);finish({status:'SOLVED',implied_growth:9,reason_codes:[],sensitivity:[]});await tick();assert.doesNotMatch(text(h.render()),/900.00%/);});
test('subject change resets observations and aborts old request; unmount aborts',async()=>{let finish;const h=harness(()=>new Promise(r=>finish=r));fill(h);submit(h);h.render({market:'HK',symbol:'00700'});assert.equal(h.calls[0][1].aborted,true);assert.equal(nodes(h.render()).find(n=>n.type==='input').props.value,'');finish({status:'SOLVED',implied_growth:9,reason_codes:[],sensitivity:[]});await tick();assert.doesNotMatch(text(h.render()),/900.00%/);fill(h);submit(h);h.unmount();assert.equal(h.calls[1][1].aborted,true);});
test('cancel aborts and discards a late result',async()=>{let finish;const h=harness(()=>new Promise(r=>finish=r));fill(h);submit(h);nodes(h.render()).find(n=>n.type==='button'&&text(n)==='取消').props.onClick();assert.equal(h.calls[0][1].aborted,true);finish({status:'SOLVED',implied_growth:9,reason_codes:[],sensitivity:[]});await tick();assert.doesNotMatch(text(h.render()),/900.00%/);});

test('calculation error permits retry and editing clears completed result',async()=>{let count=0;const h=harness(async()=>{if(count++===0)throw new Error('Synthetic failure');return {status:'SOLVED',implied_growth:.1,reason_codes:[],sensitivity:[]};});fill(h);submit(h);await tick();assert.match(text(h.render()),/Synthetic failure/);submit(h);await tick();assert.equal(h.calls.length,2);assert.match(text(h.render()),/10.00%/);nodes(h.render()).find(n=>n.type==='input').props.onChange({target:{value:'Updated industry source'}});assert.doesNotMatch(text(h.render()),/10.00%/);});
