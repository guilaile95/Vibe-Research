import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(page, start, end, entry) {
  const source=readFileSync(new URL(`../src/pages/${page}.tsx`,import.meta.url),'utf8');
  const body=source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
  const state={};const calls=[];
  const api=new Proxy({}, {get:()=>params=>new Promise((resolve,reject)=>calls.push({params,resolve,reject}))});
  const scope={api,HISTORY_LIMIT:20,histOffset:0,histFilterDate:'',historyRequestRef:{current:0},requestRef:{current:0},mountedRef:{current:true},detailRequestRef:{current:0},comparisonRequestRef:{current:0},baseSnapshot:{id:1},targetSnapshot:{id:2},comparisonLoading:false,COMPARE_BOARD_LIMIT:10,COMPARE_STOCK_LIMIT:10,ApiError:Error};
  for(const key of ['HistLoading','HistErr','HistItems','HistCount','HistOffset','HistDone','Loading','ErrorMsg','RunRecord','SignalEntries','DecisionOutcomes','SelectedSnapshotId','SelectedSnapshot','DetailError','DetailLoading','BaseSnapshot','TargetSnapshot','Comparison','ComparisonError','ComparisonLoading'])scope[`set${key}`]=value=>{state[key]=value;};
  const code=ts.transpileModule(body+`;globalThis.run=${entry || (page==='DailyReview'?'loadHistory':'fetchData')};`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
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

test('DailyReview newer snapshot selection rejects an older detail result',async()=>{
  const h=harness('DailyReview','  const openHistoryDetail =','  const onHistDateChange =','openHistoryDetail');
  h.run(1);h.run(2);
  h.calls[1].resolve({id:2,trade_date:'2026-10-02'});await tick();
  h.calls[0].resolve({id:1,trade_date:'2026-10-01'});await tick();
  assert.equal(h.state.SelectedSnapshotId,2);
  assert.equal(h.state.SelectedSnapshot.id,2);
});

for(const action of ['clearCompareSelection','selectBaseSnapshot','selectTargetSnapshot'])test(`DailyReview ${action} invalidates old comparison`,async()=>{
  const h=harness('DailyReview','  const invalidateComparison =','  /** rank_delta','({runCompare,clearCompareSelection,selectBaseSnapshot,selectTargetSnapshot})');
  h.run.runCompare();h.run[action]({id:3});
  h.calls[0].resolve({base_id:1,target_id:2,marker:'OLD'});await tick();
  assert.equal(h.state.Comparison,null);
});

test('DailyReview close detail invalidates pending response',async()=>{
  const h=harness('DailyReview','  const openHistoryDetail =','  const onHistDateChange =','({openHistoryDetail,closeHistoryDetail})');
  h.run.openHistoryDetail(1);h.run.closeHistoryDetail();
  h.calls[0].resolve({id:1});await tick();
  assert.equal(h.state.SelectedSnapshotId,null);assert.equal(h.state.SelectedSnapshot,null);
  assert.equal(h.state.DetailLoading,false);
});
