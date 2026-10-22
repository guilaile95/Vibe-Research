import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { ApiError } from '../src/lib/api.ts';
import * as panels from '../src/components/ui/optionalDataPanelState.ts';
import * as evidence from '../src/lib/stockDataEvidence.ts';
import * as candidate from '../src/lib/candidateCampaign.ts';
import * as internalReturn from '../src/lib/internalReturnTo.ts';

// Actual component with synthetic hooks and API boundaries; no browser/providers.
function harness(globalStock, initialQuery = "AAP", valuation = async () => { throw new ApiError("SYNTHETIC_QUOTE_FAILURE", 503); }) {
  const slots=[], effects=[];
  let cursor=0, pending=[], query=initialQuery;
  const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
  const React={
    useState(initial) { const i=cursor++; if (!(i in slots)) slots[i]=typeof initial==='function'?initial():initial; return [slots[i],next=>{slots[i]=typeof next==='function'?next(slots[i]):next;}]; },
    useRef(initial) { const i=cursor++; return slots[i]??={current:initial}; },
    useCallback(fn,deps) { const i=cursor++; if (!slots[i]||!same(slots[i].deps,deps)) slots[i]={deps,value:fn}; return slots[i].value; },
    useEffect(fn,deps) { const i=cursor++; if (!effects[i]||!same(effects[i].deps,deps)) pending.push(()=>{effects[i]?.cleanup?.();effects[i]={deps,cleanup:fn()};}); },
  };
  const stub=new Proxy({}, {get:(_,key)=>key==='__esModule'?true:()=>null});
  const modules={
    react:React,
    'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},
    'react-router-dom':{Link:()=>null,useLocation:()=>({pathname:'/stock',search:`?code=${query}`,hash:''}),useNavigate:()=>()=>{},useSearchParams:()=>[new URLSearchParams({code:query})]},
    '@/components/ui/optionalDataPanelState':panels,
    '@/lib/stockDataEvidence':evidence,
    '@/lib/candidateCampaign':candidate,
    '@/lib/internalReturnTo':internalReturn,
    '@/lib/utils':{cn:(...items)=>items.join(' ')},
    '@/lib/api':{ApiError,api:new Proxy({globalStock,valuation,hkCashflow:async()=>{throw new ApiError('not HK',404);}}, {get:(target,key)=>key in target?target[key]:()=>Promise.reject(new Error(`Synthetic unavailable API ${String(key)}`))})},
  };
  const exports={};
  const source=ts.transpileModule(readFileSync(new URL('../src/pages/StockData.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(source,{exports,require:name=>modules[name]??stub,URLSearchParams});
  return {render(){cursor=0;const tree=exports.StockData();const queue=pending;pending=[];queue.forEach(fn=>fn());return tree;},query(value){query=value;}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function text(tree){if(tree==null||typeof tree==='boolean')return '';if(typeof tree!=='object')return String(tree);return Array.isArray(tree)?tree.map(text).join(''):text(tree.props?.children);}

for(const [status,message] of [[400,'证券标识存在歧义'],[404,'未找到美股/港股代码'],[503,'证券搜索接口暂时不可用']]){
  test(`actual StockData renders ${status} resolver failure without a success card`,async()=>{
    const calls=[];
    const h=harness(async symbol=>{calls.push(symbol);throw new ApiError(message,status);});
    h.render();await tick();const tree=h.render();
    assert.match(text(tree),new RegExp(message));
    assert.doesNotMatch(text(tree),/Synthetic wrong security/);
    assert.deepEqual(calls,['AAP']);
  });
}

test('actual StockData ignores a late old-symbol rejection after another lookup',async()=>{
  let oldReject;
  const h=harness(symbol=>symbol==='AAP'?new Promise((_,reject)=>{oldReject=reject;}):Promise.reject(new ApiError('CURRENT_ERROR',400)));
  h.render();h.query('ABC');h.render();await tick();
  assert.match(text(h.render()),/CURRENT_ERROR/);
  oldReject(new ApiError('OLD_ERROR',503));await tick();
  assert.match(text(h.render()),/CURRENT_ERROR/);
  assert.doesNotMatch(text(h.render()),/OLD_ERROR/);
});

function nodes(tree) { if (tree == null || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.actions)]; }
function candidateLink(tree) { return nodes(tree).find(node => node.props?.['data-testid'] === 'stock-data-candidate-entry'); }
for (const code of ['', '00700', 'AAPL', 'BAD', '60051']) {
  test(`production candidate entry rejects non A-share or unsubmitted code ${code}`, async () => {
    const h = harness(async () => { throw new Error('unavailable'); }, code);
    h.render(); await tick(); assert.equal(candidateLink(h.render()), undefined);
  });
}
test('production candidate entry survives failed quote and ignores unsubmitted text', async () => {
  const h = harness(async () => null, '600519');
  h.render(); await tick(); let tree = h.render();
  const input = nodes(tree).find(node => node.props?.placeholder?.startsWith('A 股 6 位代码'));
  input.props.onChange({ target: { value: '600520' } }); tree = h.render();
  const target = new URL(candidateLink(tree).props.to, 'http://localhost');
  assert.equal(target.pathname, '/candidates/600519');
  assert.equal(new URL(target.searchParams.get('return_to'), 'http://localhost').searchParams.get('code'), '600519');
  assert.match(text(tree), /行情与估值暂不可用/);
});
test('production candidate entry remains bound to latest query after late quote success', async () => {
  let finish;
  const h = harness(async () => null, '600519', code => code === '600519' ? new Promise(resolve => { finish = resolve; }) : Promise.reject(new Error('new unavailable')));
  h.render(); h.render(); h.query('600520'); h.render(); await tick();
  finish({ code: '600519', name: 'LATE_OLD', price: 1 }); await tick();
  const tree = h.render();
  assert.equal(new URL(candidateLink(tree).props.to, 'http://localhost').pathname, '/candidates/600520');
  assert.doesNotMatch(text(tree), /LATE_OLD/);
});
