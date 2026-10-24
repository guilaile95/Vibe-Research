import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { build } from 'esbuild';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { fileURLToPath } from 'node:url';
import { stockFinancialsFixture } from './e2e/stock-financials.fixture.mjs';
import { ReadRequestContext } from '../src/lib/readRequestContext.ts';
const source=readFileSync(new URL('../src/pages/StockData.tsx',import.meta.url),'utf8');
const start=source.indexOf('  const run = useCallback(async');
const end=source.indexOf('  // Each tab loads',start);
const runBody=source.slice(start,end);
const effectBody=source.slice(source.indexOf('  useEffect(() => {',end),source.indexOf('  useEffect(() => {\n    if (urlCode',end));
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
const tick=()=>new Promise(r=>setImmediate(r));
function harness() {
 const calls=[],events=[];let effect;
 const scope={
  useCallback:f=>f,useEffect:f=>{effect=f;},ReadRequestContext,loadAccessKey:()=>'',runIdRef:{current:0},
  readContextRef:{current:null},loadedTabsRef:{current:new Set()},activeCodeRef:{current:''},
  commitPanelStates:()=>{},resetPanelStates:()=>({}),ApiError:Error,activeCode:'',tab:'overview',tiQueryVersion:0,
  api:new Proxy({}, {get:(_,method)=>(...args)=>{
   const held=deferred();calls.push({method,args,...held});return held.promise;
  }}),
  loadEvidenceSource:(f,empty,message,set,current)=>{set({status:'loading',data:empty});return f().then(data=>{if(current())set({status:'success',data});},()=>{if(current())set({status:'error',data:empty});});},
  resolveEvidenceList:p=>p.catch(()=>({status:'error',data:[]})),
  resolveReportEvidence:p=>p.catch(()=>({status:'error',data:[]})),
 };
 for(const name of new Set((runBody+effectBody).match(/\bset[A-Z]\w+/g))) scope[name]=v=>{events.push([name,v]);};
 vm.runInNewContext(ts.transpileModule(runBody+';globalThis.run=run;\n'+effectBody,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,scope);
 return {scope,calls,events,run:scope.run,tab:tab=>{scope.activeCode=scope.activeCodeRef.current;scope.tab=tab;effect();},stop:()=>{scope.runIdRef.current++;scope.readContextRef.current.cancel();}};
}
test('actual query starts only primary valuation, completes before enrichment, lazy tabs retain source groups',async(t)=>{
 const h=harness();t.after(()=>h.stop());const task=h.run('600001');
 assert.deepEqual(h.calls.map(c=>c.method),['valuation']);
 h.tab('overview');
 assert.deepEqual(h.calls.map(c=>c.method),['valuation','topRisk','stockRelativeContext','stockValuationContext']);
 h.calls[0].resolve({price:10});await task;await tick();
 assert.ok(h.events.some(([key,v])=>key==='setVal'&&v?.price===10));
 assert.ok(h.events.some(([key,v])=>key==='setLoading'&&v===false));
 assert.equal(h.calls.some(c=>['financials','news','margin','reportsWithCoverage'].includes(c.method)),false);
 h.tab('overview'); assert.equal(h.calls.filter(c=>c.method==='topRisk').length,1);
 // Drain current tab to prove finite FIFO and then select a different group.
 for(let i=1;i<h.calls.length;i++){h.calls[i].resolve({});await tick();}
 h.tab('financials');
 assert.deepEqual(h.calls.slice(-2).map(c=>c.method),['financials','percentile']);
 h.stop();await tick();
});
test('actual rapid A→B→A query aborts old active transport and queued reads; late A cannot fill B',async(t)=>{
 const h=harness();t.after(()=>h.stop());const a=h.run('600001');h.tab('overview');
 const old=h.calls.slice();const b=h.run('600002');
 assert.ok(old.every(c=>c.args.at(-1).aborted));
 old.forEach(c=>c.resolve({code:'600001'}));await a;await tick();
 assert.equal(h.calls.filter(c=>c.args[0]==='600001').length,4,'old queued blocks/hotConcepts never start');
 assert.equal(h.events.filter(([key])=>key==='setVal').length,2,'only two reset writes, no stale fill');
 const last=h.calls.at(-1);last.resolve({code:'600002'});await b;
 assert.equal(h.events.filter(([key,v])=>key==='setVal'&&v?.code==='600002').length,1);
 const again=h.run('600001');assert.equal(h.calls.at(-1).method,'valuation');
 h.stop();await again;
});
test('actual primary failure is retryable and query cancellation clears current spinner without stale fill',async(t)=>{
 const h=harness();t.after(()=>h.stop());const task=h.run('600001');h.calls[0].reject(Error('quote unavailable'));await task;
 assert.ok(h.events.some(([key,v])=>key==='setErr'&&v==='quote unavailable'));
 const retry=h.run('600001');assert.equal(h.calls.length,2);
 h.calls[1].resolve({code:'600001'});await retry;
 assert.ok(h.events.some(([key,v])=>key==='setLoading'&&v===false));h.stop();
});


test('lazy financial source completion renders the actual snapshot and a unique readiness heading', async(t) => {
 const root=fileURLToPath(new URL('../',import.meta.url));
 const bundle=await build({entryPoints:[`${root}src/components/ui/EarningsSnapshot.tsx`],bundle:true,write:false,format:'esm',platform:'node',tsconfig:`${root}tsconfig.json`});
 const {EarningsSnapshot}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
 const h=harness();t.after(()=>h.stop());
 const render=()=>renderToStaticMarkup(createElement(EarningsSnapshot,{fin:h.events.filter(([key])=>key==='setFin').at(-1)?.[1]??null,error:null}));
 const task=h.run('000001');h.calls[0].resolve({code:'000001',price:11.5});await task;
 assert.equal(h.calls.some(c=>c.method==='financials'),false,'inactive financials cannot be fetched eagerly');
 assert.doesNotMatch(render(),/Growth · 增长/);
 h.tab('financials');
 assert.equal(h.calls.filter(c=>c.method==='financials').length,1);
 assert.doesNotMatch(render(),/Growth · 增长/,'mounted card does not mean financial response completed');
 h.calls.find(c=>c.method==='financials').resolve(stockFinancialsFixture());await tick();
 const html=render();
 assert.equal((html.match(/>Growth · 增长<\/h4>/g)||[]).length,1,'readiness heading uniquely identifies loaded facts');
 assert.equal((html.match(/>260.00 亿元<\//g)||[]).length,3,'latest and two history rows intentionally repeat the amount: strict amount locator is invalid');
 for(const text of ['Profitability · 盈利能力','Cash Flow Quality · 现金流质量','披露日期：未知（数据源未提供）','现金转化率','150.0%','自由现金流']) assert.ok(html.includes(text),text);
 h.tab('overview');h.tab('financials');
 assert.equal(h.calls.filter(c=>c.method==='financials').length,1,'return to the same tab reuses its source');
});
