import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';
import {flush} from './helpers/askAiHarness.mjs';
const source=readFileSync(new URL('../src/pages/DailyReview.tsx',import.meta.url),'utf8');
// Execute the production refresh callback with synthetic React setters and promise boundaries.
const fn=source.slice(source.indexOf('  const refreshWatch ='),source.indexOf('\n  useEffect',source.indexOf('  const refreshWatch =')));
const quoteModule={exports:{}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/lib/quoteSnapshot.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,quoteModule);
const {validQuoteRows,quoteSnapshotStates,quoteSnapshotLabel}=quoteModule.exports;
function harness(){
 const state={quotes:{},loading:false,failures:[],error:null,completed:null};const requests=[];
 const setter=key=>value=>state[key]=typeof value==='function'?value(state[key]):value;
 const ctx={api:{quote:codes=>new Promise((resolve,reject)=>requests.push({codes,resolve,reject}))},setWatchQuotes:setter('quotes'),setWatchLoading:setter('loading'),setWatchQuoteFailures:setter('failures'),setWatchQuoteError:setter('error'),setWatchRequestCompletedAt:setter('completed'),watchRequest:{current:0},mountedRef:{current:true},validQuoteRows};
 vm.runInNewContext(ts.transpile(fn+'\nglobalThis.refresh=refreshWatch;', {target:ts.ScriptTarget.ES2022}),ctx);
 return {state,requests,refresh:ctx.refresh,unmount(){ctx.mountedRef.current=false;ctx.watchRequest.current++}};
}
const q=(time='2026-10-20T01:30:00Z')=>({price:100,change_pct:2,data_time:time});
test('DailyReview successful quote becomes explicit stale snapshot after failure, not fake new data time',async()=>{
 const h=harness();h.refresh(['A']);h.requests[0].resolve({A:q()});await flush();assert.equal(h.state.quotes.A.price,100);assert.equal(h.state.failures.length,0);assert.ok(h.state.completed);
 h.refresh(['A']);h.requests[1].reject(new Error('provider failed'));await flush();assert.equal(h.state.quotes.A.price,100);assert.equal(h.state.loading,false);assert.match(h.state.error,/刷新失败/);
 assert.match(quoteSnapshotLabel(quoteSnapshotStates(h.state.quotes,['A'],h.state.failures,Date.now()).A),/旧快照.*刷新失败/);
});
test('DailyReview partial/unknown/future data is marked and removed symbols cannot leak from older requests',async()=>{
 const h=harness();h.refresh(['A','B']);h.requests[0].resolve({A:q(null),B:q('2999-01-01T00:00:00Z')});await flush();let states=quoteSnapshotStates(h.state.quotes,['A','B'],[],Date.now());assert.equal(states.A.timeIssue,'unknown');assert.equal(states.B.timeIssue,'future');
 h.refresh(['A','B']);h.requests[1].resolve({A:q(),B:{price:NaN}});await flush();assert.equal(h.state.failures[0],'B');assert.equal(h.state.quotes.B.price,100);
 h.refresh(['A','B']);const old=h.requests.at(-1);h.refresh(['C']);const current=h.requests.at(-1);current.resolve({C:q(),A:q()});await flush();old.resolve({A:q(),B:q()});await flush();assert.deepEqual(Object.keys(h.state.quotes),['C']);assert.equal(h.state.loading,false);
 h.refresh(['C']);const pending=h.requests.at(-1);h.refresh([]);pending.reject(new Error('late'));await flush();assert.deepEqual(Object.keys(h.state.quotes),[]);assert.equal(h.state.error,null);assert.equal(h.state.completed,null);assert.equal(h.state.loading,false);
});
test('DailyReview first failure has no invented price and unmount rejects completion',async()=>{
 const h=harness();h.refresh(['A']);h.requests[0].reject(new Error('fail'));await flush();assert.equal(h.state.quotes.A,undefined);assert.equal(quoteSnapshotStates({},['A'],h.state.failures,Date.now()).A.available,false);
 h.refresh(['B']);h.unmount();h.requests.at(-1).resolve({B:q()});await flush();assert.equal(h.state.quotes.B,undefined);
});
test('both DailyReview quote surfaces render shared provider-time states and request completion is not quote time',()=>{
 assert.match(source,/quoteSnapshotLabel\(watchQuoteStates\[c\]\)/);assert.match(source,/quoteSnapshotLabel\(watchQuoteStates\[code\]\)/);assert.match(source,/非行情时间/);assert.doesNotMatch(fn,/setInterval|setTimeout/);
});
