import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Execute actual component handlers and JSX with offline dependencies.
function harness(file, name, overrides) {
  const slots = [], effects = []; let cursor = 0, pending = [], tree;
  const same = (a,b) => a && b && a.length === b.length && a.every((v,i)=>Object.is(v,b[i]));
  const hooks = {
    useState(value) { const i=cursor++; if (!(i in slots)) slots[i]=typeof value==='function'?value():value; return [slots[i], v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}]; },
    useRef(value) { const i=cursor++; return slots[i] ??= {current:value}; },
    useCallback(fn,deps) { const i=cursor++; if(!same(slots[i]?.deps,deps)) slots[i]={fn,deps}; return slots[i].fn; },
    useEffect(fn,deps) { const i=cursor++; if(!same(effects[i]?.deps,deps)) pending.push(()=>{effects[i]?.cleanup?.();effects[i]={deps,cleanup:fn()};}); },
  };
  const modules = {react:hooks, 'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}, ...overrides};
  const stub = new Proxy({}, {get:(_,key)=>key==='__esModule'?true:key==='default'?'presentation':()=>null});
  const exports={};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'), {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,
    {exports,require:name=>modules[name]??stub,AbortController,DOMException,Error});
  return {render(){cursor=0;tree=exports[name]({});const queue=pending;pending=[];queue.forEach(fn=>fn());return tree;},nodes:()=>nodes(tree)};
}
const nodes = n => !n || typeof n!=='object'?[]:Array.isArray(n)?n.flatMap(nodes):[n,...nodes(n.props?.children)];
const text = n => n==null || typeof n==='boolean'?'':typeof n!=='object'?String(n):Array.isArray(n)?n.map(text).join(''):text(n.props?.children);
const click = (h,label) => { const b=h.nodes().find(n=>n.type==='button' && text(n).trim()===label); assert.ok(b,`missing button ${label}`); assert.ok(!b.props.disabled); return b.props.onClick(); };
const tick = () => new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
async function intelHarness(latest=null) {
  const requests=[];
  const api={nativeIntelStatus:async()=>({status:'normal'}),nativeIntelItems:async()=>({items:[],status:'normal'}),nativeIntelTrending:async()=>({entities:[],status:'normal'}),radar:async()=>({generated_at:'synthetic',stats:{},industries:[{key:'ai',name:'AI',items:[]}]}),getIntelDigestLatest:async()=>({digest:latest})};
  const h=harness('../src/components/market/MarketIntelPanel.tsx','default',{
    '@/lib/api':{api,ApiError:Error},'@/lib/llm':{hasLlm:()=>true},
    '@/components/ui/SaveNoteButton':{SaveNoteButton:'SaveNoteButton'},
    '@/lib/intelDigestOrchestrator':{runIntelDigestGeneration:params=>{const d=deferred();requests.push({...d,params});return d.promise;}},
    '@/lib/marketIntelStatus':{deriveMarketIntelStatus:()=> 'normal',knownCountText:()=>'',knownHistoryItemCount:()=>0,sourceHealthText:()=>'',trendEmptyReason:()=>'',TREND_EMPTY_LABELS:{},radarCoverageNotice:()=>null},
  });
  h.render();await tick();h.render();await tick();h.render();return {...h,requests};
}
const saves=h=>h.nodes().filter(n=>n.type==='SaveNoteButton');
test('cancelled partial digest stays visible without ordinary note-save action, including late completion',async()=>{
  const h=await intelHarness();click(h,'让 AI 提炼今日要点');const r=h.requests[0];r.params.onDelta('SYNTHETIC_PARTIAL');h.render();click(h,'取消生成');h.render();
  assert.match(text(h.render()),/SYNTHETIC_PARTIAL/);assert.equal(saves(h).length,0);
  r.resolve({status:'cancelled',summaryText:'SYNTHETIC_PARTIAL'});await tick();h.render();assert.equal(saves(h).length,0);
  click(h,'重新提炼');h.requests[1].resolve({status:'saved',summaryText:'SYNTHETIC_RETRY_COMPLETE'});await tick();h.render();
  assert.equal(saves(h).length,1);assert.equal(saves(h)[0].props.content,'SYNTHETIC_RETRY_COMPLETE');assert.doesNotMatch(text(h.render()),/SYNTHETIC_PARTIAL/);
});
test('complete saved and complete save-failed digests retain ordinary note-save recovery',async()=>{
  for(const status of ['saved','save_failed']){
    const h=await intelHarness();click(h,'让 AI 提炼今日要点');h.requests[0].resolve({status,summaryText:'SYNTHETIC_COMPLETE',error:status==='save_failed'?'quota':undefined});await tick();h.render();
    assert.equal(saves(h).length,1);assert.equal(saves(h)[0].props.content,'SYNTHETIC_COMPLETE');
  }
  const h=await intelHarness({summary_text:'SYNTHETIC_HISTORY',digest_date:'2026-10-31'});assert.equal(saves(h).length,1);
});
test('debate saved note retains current data gaps and truncation without model repetition; retry resets them',async()=>{
  const requests=[],saved=[];
  const h=harness('../src/pages/Debate.tsx','Debate',{
    'react-router-dom':{useLocation:()=>({search:'?code=600519'})},'@/lib/debateHandoff':{debateCodeFromSearch:()=> '600519'},
    '@/lib/agents':{debateStream:(code,rounds,callbacks)=>{const d=deferred();requests.push({...d,callbacks});return d.promise;}},
    '@/lib/notes':{addNote:async(...args)=>{saved.push(args);}},'@/lib/api':{ApiError:Error},
  });
  h.render();h.render();
  async function complete(gaps){const p=click(h,'开始辩论');const r=requests.at(-1); if(gaps){r.callbacks.onDossierProgress('报价',false,1,4,'partial',false);r.callbacks.onDossierProgress('公告',true,2,4,'success',true);r.callbacks.onDossierProgress('研报',true,3,4,'empty',false);r.callbacks.onDossierProgress('财务',false,4,4,'error',false);r.callbacks.onDossierReady([],['财务'],['报价']);} else r.callbacks.onDossierReady([],[],[]);
    r.callbacks.onStageStart('bull','多方');r.callbacks.onStageDone('bull','多方','SYNTHETIC_MODEL_TEXT');r.resolve();await p;h.render();await click(h,'存入沉淀');h.render();}
  await complete(true);const body=saved[0][2];assert.match(body,/数据.*限制/);for(const marker of ['报价','公告','已截断','研报','未取到','财务','获取失败'])assert.ok(body.includes(marker),marker);assert.match(body,/SYNTHETIC_MODEL_TEXT/);
  await complete(false);assert.doesNotMatch(saved[1][2],/报价|公告|研报|财务|已截断/);
});
