import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const source = ts.transpileModule(readFileSync(new URL('../src/components/campaign/CandidateCampaignPanel.tsx', import.meta.url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const tick = () => new Promise(resolve => setImmediate(resolve));
const nodes = value => !value || typeof value !== 'object' ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
function harness() {
  let props = { code: '600001', workspace: true }, cursor = 0, dirty = true, tree, writes = 0;
  const cells = [], effects = [], calls = [];
  const same = (a,b) => a && b && a.length === b.length && a.every((x,i) => Object.is(x,b[i]));
  const react = {
    useState(initial) { const i=cursor++; if (!(i in cells)) cells[i]=typeof initial==='function'?initial():initial; return [cells[i], next => { writes++; const value=typeof next==='function'?next(cells[i]):next; if(!Object.is(value,cells[i])) {cells[i]=value;dirty=true;} }]; },
    useRef(initial) { return cells[cursor++] ??= {current:initial}; },
    useMemo(fn,deps) { const i=cursor++; if(!cells[i]||!same(cells[i].deps,deps))cells[i]={deps,value:fn()}; return cells[i].value; },
    useCallback(fn,deps) { return react.useMemo(()=>fn,deps); },
    useLayoutEffect(fn,deps) { const i=cursor++; if(!cells[i]||!same(cells[i].deps,deps)){const old=cells[i];cells[i]={deps,effect:fn};effects.push(()=>{old?.cleanup?.();cells[i].cleanup=fn();});} },
  };
  const api = new Proxy({}, {get:(_,method)=>(...args)=>new Promise((resolve,reject)=>calls.push({method,args,resolve,reject}))});
  const modules = {react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/api':{api,ApiError:Error},'@/lib/decisionInbox':{CAMPAIGN_STRATEGIES:['SWING'],CAMPAIGN_STRATEGY_LABELS:{SWING:'swing'},errorMessage:e=>e.message},'@/lib/candidateCampaign':{selectCandidateCampaigns:(r,c)=>r.filter(x=>x.security_code===c)},'@/components/ui/GlassCard':{GlassCard:'section'},'lucide-react':{},'./CampaignLifecycleCard':{CampaignLifecycleCard:'lifecycle'},'./CampaignThesisActivationCard':{CampaignThesisActivationCard:'thesis'},'./ResearchContinuityCard':{ResearchContinuityCard:'continuity'}};
  const exports={};vm.runInNewContext(source,{exports,require:n=>{assert.ok(modules[n],n);return modules[n];}});
  return {calls, get tree(){return tree;}, get writes(){return writes;},
    update(code){props={...props,code};dirty=true;},
    unmount(){cells.forEach(cell=>cell?.cleanup?.());},
    replay(){cells.forEach(cell=>{if(cell?.effect){cell.cleanup?.();cell.cleanup=cell.effect();}});},
    select(){nodes(tree).find(n=>n.type==='input').props.onChange();},
    create(){nodes(tree).find(n=>n.props?.['data-testid']==='create-candidate-campaign').props.onClick();},
    async flush(){await tick();for(let n=0;n<20&&(dirty||effects.length);n++){if(dirty){dirty=false;cursor=0;tree=exports.CandidateCampaignPanel(props);}effects.splice(0).forEach(f=>f());await tick();}},
  };
}
const record = {status:'DRAFT',campaign_id:'A',security_code:'600001',strategy:'SWING'};
async function pendingCreate(){const h=harness();await h.flush();h.calls[0].resolve([]);await h.flush();h.select();await h.flush();h.create();await h.flush();assert.equal(h.calls[1].method,'createCampaign');return h;}
for(const failure of [false,true]) for(const returnToA of [false,true]) test(`late create ${failure?'error':'success'} cannot own ${returnToA?'A→B→A':'A→B'} context`,async()=>{
  const h=await pendingCreate();h.update('600002');await h.flush();h.calls[2].resolve([]);await h.flush();
  if(returnToA){h.update('600001');await h.flush();h.calls[3].resolve([]);await h.flush();}
  const count=h.calls.length,writes=h.writes;
  failure?h.calls[1].reject(new Error('STALE')):h.calls[1].resolve(record);await h.flush();
  assert.equal(h.calls.length,count,'old mutation cannot restart a loader');assert.equal(h.writes,writes,'old success/error/finalizer cannot mutate current state');
  assert.equal(nodes(h.tree).filter(n=>n.type==='lifecycle').length,0);h.unmount();
});
test('unmount and StrictMode effect replay invalidate pending mutation ownership',async()=>{
  for(const replay of [false,true]){const h=await pendingCreate();replay?h.replay():h.unmount();await h.flush();const count=h.calls.length,writes=h.writes;h.calls[1].resolve(record);await h.flush();assert.equal(h.calls.length,count);assert.equal(h.writes,writes);h.unmount();}
});
test('same-turn double click has one write; valid completion refreshes only its own security',async()=>{
  const h=harness();await h.flush();h.calls[0].resolve([]);await h.flush();h.select();await h.flush();h.create();h.create();await h.flush();assert.equal(h.calls.filter(c=>c.method==='createCampaign').length,1);
  h.calls[1].resolve(record);await h.flush();assert.equal(h.calls[2].args[0].security_code,'600001');h.calls[2].resolve([record]);await h.flush();h.calls[3].resolve({});await h.flush();assert.equal(nodes(h.tree).find(n=>n.type==='lifecycle').props.securityCode,'600001');
  const oldChanged=nodes(h.tree).find(n=>n.type==='lifecycle').props.onChanged;h.update('600002');await h.flush();const count=h.calls.length;oldChanged();await h.flush();assert.equal(h.calls.length,count);h.unmount();
});
test('mismatched create receipt is not installed as an actionable campaign',async()=>{
 const h=await pendingCreate();h.calls[1].resolve({...record,security_code:'600002'});await h.flush();assert.equal(h.calls.length,2);assert.equal(nodes(h.tree).filter(n=>n.type==='lifecycle').length,0);h.unmount();
});


test('visible strategy label owns the controlled radio and unlocks explicit creation',async()=>{
 const h=harness();await h.flush();h.calls[0].resolve([]);await h.flush();
 const labels=nodes(h.tree).filter(n=>n.type==='label'&&nodes(n.props.children).some(c=>c.type==='input'&&c.props.type==='radio'&&c.props.value==='SWING'));
 assert.equal(labels.length,1,'visible label target is unique');
 const radio=nodes(labels[0].props.children).find(n=>n.type==='input');
 assert.equal(radio.props.className,'sr-only');assert.equal(radio.props.checked,false);
 assert.equal(nodes(h.tree).find(n=>n.props?.['data-testid']==='create-candidate-campaign').props.disabled,true);
 radio.props.onChange();await h.flush();
 assert.equal(nodes(h.tree).find(n=>n.type==='input').props.checked,true);
 assert.equal(nodes(h.tree).find(n=>n.props?.['data-testid']==='create-candidate-campaign').props.disabled,false);
 h.create();await h.flush();assert.equal(h.calls.filter(c=>c.method==='createCampaign').length,1);h.unmount();
});
