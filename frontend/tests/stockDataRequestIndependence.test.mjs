import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/pages/StockData.tsx',import.meta.url),'utf8');
const start=source.indexOf('    // Financial enrichment must not hold');
const end=source.indexOf('  }, [commitPanelStates]);',start);
const body=source.slice(start,end);
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const execute=new AsyncFunction('api','c','rid','runIdRef','setFin','setFinError','setVal','setErr','setLoading','ApiError',body);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
test('actual StockData request block displays quote while financials remain held and rejects old owner', async()=>{
 const financial=deferred(),quote=deferred(),state={current:1},events=[];
 const task=execute({financials:()=>financial.promise,valuation:()=>quote.promise},'600000',1,state,...['fin','finError','quote','error','loading'].map(key=>value=>events.push([key,value])),Error);
 quote.resolve({price:10});await task;
 assert.deepEqual(events,[['quote',{price:10}],['loading',false]]);
 state.current=2;financial.resolve({revenue:1});await new Promise(r=>setImmediate(r));
 assert.equal(events.length,2);
});
test('actual request block retains financial state after quote failure without claiming standalone rendering',async()=>{
 const events=[];
 await execute({financials:async()=>({revenue:1}),valuation:async()=>{throw new Error('quote unavailable')}},'600000',1,{current:1},...['fin','finError','quote','error','loading'].map(key=>value=>events.push([key,value])),Error);
 assert.ok(events.some(([key,value])=>key==='fin'&&value.revenue===1));
 assert.ok(events.some(([key,value])=>key==='error'&&value==='quote unavailable'));
});
