import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(page, start, end) {
  const source=readFileSync(new URL(`../src/pages/${page}.tsx`,import.meta.url),'utf8');
  const body=source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
  const state={};const calls=[];
  const api=new Proxy({}, {get:()=>params=>new Promise((resolve,reject)=>calls.push({params,resolve,reject}))});
  const scope={api,HISTORY_LIMIT:20,histOffset:0,histFilterDate:'',historyRequestRef:{current:0},requestRef:{current:0},mountedRef:{current:true},ApiError:Error};
  for(const key of ['HistLoading','HistErr','HistItems','HistCount','HistOffset','HistDone','Loading','ErrorMsg','RunRecord','SignalEntries','DecisionOutcomes'])scope[`set${key}`]=value=>{state[key]=value;};
  const code=ts.transpileModule(body+`;globalThis.run=${page==='DailyReview'?'loadHistory':'fetchData'};`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(code,scope);
  return {...scope,state,calls};
}
for(const kind of ['DailyReview','SignalLedger']) {
  for(const staleError of [false,true]) test(`${kind} ignores stale ${staleError?'error':'success'} and finalizer`,async()=>{
    const h=kind==='DailyReview'?harness(kind,'  const loadHistory =','  const pending ='):harness(kind,'  const fetchData =','  useEffect(');
    const first=kind==='DailyReview'?{trade_date:'2026-10-01'}:{stage:'schema'};
    const second=kind==='DailyReview'?{trade_date:'2026-10-02'}:{stage:'execution'};
    h.run(first);h.run(second);
    h.calls[1].resolve({items:[{id:'NEW'}],count:1,offset:0});await tick();
    if(staleError)h.calls[0].reject(new Error('STALE ERROR'));else h.calls[0].resolve({items:[{id:'OLD'}],count:7,offset:20});
    await tick();
    const rows=h.state[kind==='DailyReview'?'HistItems':'SignalEntries'];
    assert.equal(rows[0].id,'NEW');
    assert.equal(h.state[kind==='DailyReview'?'HistErr':'ErrorMsg'],null);
    if(kind==='DailyReview')assert.equal(h.state.HistOffset,0);
  });
  test(`${kind} stale request cannot stop current loading`,async()=>{
    const h=kind==='DailyReview'?harness(kind,'  const loadHistory =','  const pending ='):harness(kind,'  const fetchData =','  useEffect(');
    h.run({});h.run({});h.calls[0].resolve({items:[]});await tick();
    assert.equal(h.state[kind==='DailyReview'?'HistLoading':'Loading'],true);
    h.calls[1].resolve({items:[]});await tick();
    assert.equal(h.state[kind==='DailyReview'?'HistLoading':'Loading'],false);
  });
}

test('SignalLedger old run detail cannot overwrite newer general query',async()=>{
  const h=harness('SignalLedger','  const fetchData =','  useEffect(');
  h.run({decision_run_id:'old'});h.run({stage:'execution'});
  h.calls[1].resolve({items:[{id:'NEW'}]});await tick();
  h.calls[0].resolve({run:{id:'OLD'},signal_entries:[{id:'OLD'}],decision_outcomes:[{id:'OLD'}]});await tick();
  assert.equal(h.state.RunRecord,null);assert.equal(h.state.SignalEntries[0].id,'NEW');
  assert.equal(h.state.DecisionOutcomes.length,0);
});
for(const kind of ['DailyReview','SignalLedger'])test(`${kind} invalidated unmounted request cannot mutate state`,async()=>{
  const h=kind==='DailyReview'?harness(kind,'  const loadHistory =','  const pending ='):harness(kind,'  const fetchData =','  useEffect(');
  h.run({});const before={...h.state};
  h.historyRequestRef.current++;h.requestRef.current++;h.mountedRef.current=false;
  h.calls[0].resolve({items:[{id:'LATE'}]});await tick();
  assert.deepEqual(h.state,before);
});
