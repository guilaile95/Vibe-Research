import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { candidateEntryContext } from '../src/lib/candidateEntryContext.ts';
import { researchNavigationRisk } from '../src/lib/researchResume.ts';
import { candidateRaceLocators, selectCandidateRaceStrategy, assertEmptyCandidateRace } from './e2e/candidate-race-controls.fixture.mjs';
import { CAMPAIGN_STRATEGIES, CAMPAIGN_STRATEGY_LABELS } from '../src/lib/decisionInbox.ts';
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
  const modules = {react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/api':{api,ApiError:Error},'@/lib/decisionInbox':{CAMPAIGN_STRATEGIES,CAMPAIGN_STRATEGY_LABELS,errorMessage:e=>e.message},'@/lib/candidateCampaign':{selectCandidateCampaigns:(r,c)=>r.filter(x=>x.security_code===c)},'@/components/ui/GlassCard':{GlassCard:'section'},'lucide-react':{},'./CampaignLifecycleCard':{CampaignLifecycleCard:'lifecycle'},'./CampaignThesisActivationCard':{CampaignThesisActivationCard:'thesis'},'./ResearchContinuityCard':{ResearchContinuityCard:'continuity'}};
  const exports={};vm.runInNewContext(source,{exports,require:n=>{assert.ok(modules[n],n);return modules[n];}});
  return {calls, get tree(){return tree;}, get writes(){return writes;},
    update(code){props={...props,code};dirty=true;},
    unmount(){cells.forEach(cell=>cell?.cleanup?.());},
    replay(){cells.forEach(cell=>{if(cell?.effect){cell.cleanup?.();cell.cleanup=cell.effect();}});},
    select(){nodes(tree).find(n=>n.type==='input'&&n.props.value==='SWING').props.onChange();},
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
 assert.equal(nodes(h.tree).find(n=>n.type==='input'&&n.props.value==='SWING').props.checked,true);
 assert.equal(nodes(h.tree).find(n=>n.props?.['data-testid']==='create-candidate-campaign').props.disabled,false);
 h.create();await h.flush();assert.equal(h.calls.filter(c=>c.method==='createCampaign').length,1);h.unmount();
});


// A bounded locator adapter over the actual JSX tree, not a parallel fake UI.
// Parent traversal and label activation use the production node relationship;
// every locator is resolved fresh after the actual hook lifecycle advances.
function panelLocator(h) {
 const text=node=>typeof node==='string'||typeof node==='number'?String(node):Array.isArray(node)?node.map(text).join(''):node&&typeof node==='object'?text(node.props?.children):'';
 const all=()=>nodes(h.tree), parent=node=>all().find(p=>Array.isArray(p.props?.children)?p.props.children.includes(node):p.props?.children===node);
 const one=find=>{const matches=find();assert.equal(matches.length,1,'locator must resolve exactly one production node');return matches[0];};
 const locator=find=>({
  getByTestId:id=>locator(()=>find().flatMap(nodes).filter(n=>n.props?.['data-testid']===id)),
  getByText:(value,{exact})=>locator(()=>find().flatMap(nodes).filter(n=>text(n)===value&&!nodes(n.props?.children).some(child=>text(child)===value))),
  getByRole:(role,{name,exact})=>locator(()=>find().flatMap(nodes).filter(n=>n.type==='input'&&n.props.type===role&&text(parent(n))===name)),
  locator:selector=>{assert.equal(selector,'..');return locator(()=>[parent(one(find))]);},
  evaluate:async fn=>fn({tagName:one(find).type.toUpperCase()}),
  click:async()=>{const label=one(find);assert.equal(label.type,'label');const input=nodes(label).find(n=>n.type==='input');input.props.onChange();await h.flush();},
  isDisabled:async()=>Boolean(one(find).props.disabled), isChecked:async()=>Boolean(one(find).props.checked),
  waitFor:async()=>{one(find);},count:async()=>find().length,
  innerText:async()=>text(one(find)),getAttribute:async name=>one(find).props[name],
 });
 return locator(()=>[h.tree]);
}
for(const outcome of ['success','failure','return-to-A']) test(`shared browser controls and full production mutation flow: ${outcome}`,async()=>{
 const h=harness();await h.flush();h.calls[0].resolve([]);await h.flush();
 const panel=panelLocator(h);await selectCandidateRaceStrategy(panel);h.create();await h.flush();
 assert.equal(h.calls[1].method,'createCampaign');assert.deepEqual(Array.from(h.calls[1].args),['600001','SWING']);
 h.update('600002');await h.flush();h.calls[2].resolve([]);await h.flush();
 await assertEmptyCandidateRace(panel,'600002');
 if(outcome==='return-to-A'){h.update('600001');await h.flush();h.calls[3].resolve([]);await h.flush();await assertEmptyCandidateRace(panel,'600001');}
 const count=h.calls.length,writes=h.writes;
 outcome==='failure'?h.calls[1].reject(new Error('Late synthetic create failure')):h.calls[1].resolve(record);await h.flush();
 assert.equal(h.calls.length,count,'late create receipt cannot refresh its old context');
 assert.equal(h.writes,writes,'late success/error/finalizer must not mutate the committed owner');
 await assertEmptyCandidateRace(panel,outcome==='return-to-A'?'600001':'600002');h.unmount();
});

test('race selection parent resolves, while the rejected nested-panel has scope cannot match',async()=>{
 const h=harness();await h.flush();h.calls[0].resolve([]);await h.flush();
 const labels=nodes(h.tree).filter(n=>n.type==='label');
 assert.equal(labels.length,CAMPAIGN_STRATEGIES.length);
 assert.equal(labels.filter(label=>nodes(label).some(n=>n.props?.['data-testid']==='candidate-campaign-panel')).length,0,
  'a has-filter evaluated inside a label cannot find the outer panel');
 const swing=nodes(h.tree).find(n=>n.type==='input'&&n.props.value==='SWING');
 assert.equal(labels.filter(label=>nodes(label).includes(swing)).length,1);
 await selectCandidateRaceStrategy(panelLocator(h));h.unmount();
});


test('actual Candidate return-link JSX supplies the clean A→B SPA destination and exact name',()=>{
 const src=readFileSync(new URL('../src/pages/CandidateWorkspace.tsx',import.meta.url),'utf8');
 const ast=ts.createSourceFile('CandidateWorkspace.tsx',src,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 let link;
 const visit=node=>{if(ts.isJsxElement(node)&&node.openingElement.tagName.getText(ast)==='Link'&&node.openingElement.attributes.properties.some(p=>ts.isJsxAttribute(p)&&p.name.getText(ast)==='data-testid'&&p.initializer?.text==='candidate-stock-data-entry'))link=node.getText(ast);ts.forEachChild(node,visit);};visit(ast);assert.ok(link);
 const from=new URL('/candidates/600519?return_to='+encodeURIComponent('/candidates/600520'),'http://fixture.local');
 const {returnTo:sourceReturnTo,discoveryStrategy}=candidateEntryContext(from.searchParams);
 const exports={};vm.runInNewContext(ts.transpileModule(`exports.node=(${link});`,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText,
  {exports,React:{createElement:(type,props,...children)=>({type,props:{...props,children}})},Link:'a',ArrowLeft:'icon',sourceReturnTo,discoveryStrategy,code:'600519',encodeURIComponent});
 assert.equal(exports.node.props.to,'/candidates/600520');
 assert.equal(exports.node.props.children.filter(v=>typeof v==='string').join('').trim(),'返回来源');
 assert.equal(researchNavigationRisk(from,new URL(exports.node.props.to,from)),'page');
 assert.equal(new URL(exports.node.props.to,from).pathname,'/candidates/600520');
 // Returning to A restores the original locator, not a guessed campaign URL.
 assert.equal(from.pathname,'/candidates/600519');assert.equal(from.searchParams.get('return_to'),'/candidates/600520');
});


test('pinned Playwright composes shared controls as parent traversal, not a nested has-panel search',()=>{
 // Construct only the pinned client Locator and parser. No browser, server,
 // transport, executable launch or computer access is involved.
 const require=createRequire(import.meta.url);
 const root=dirname(require.resolve('playwright-core/package.json'));
 const {Locator}=require(join(root,'lib/client/locator.js'));
 const {parseSelector}=require(join(root,'lib/utils/isomorphic/selectorParser.js'));
 const frame={_platform:{}};
 const panel=new Locator(frame,'[data-testid="candidate-campaign-panel"]');
 const {strategy,label,create}=candidateRaceLocators(panel);
 const parts=parseSelector(label._selector).parts;
 assert.equal(parts.length,3);
 assert.equal(parts[0].name,'css');assert.equal(parts[1].name,'internal:role');
 assert.equal(parts[1].body,'radio[name="SWING · 波段"s]');
 assert.equal(parts[2].name,'xpath');assert.equal(parts[2].body,'..');
 assert.equal(parseSelector(create._selector).parts.at(-1).name,'internal:testid');
 const old=panel.locator('label').filter({has:strategy});
 const nested=parseSelector(old._selector).parts.at(-1);
 assert.equal(nested.name,'internal:has');
 assert.equal(nested.body.parsed.parts[0].source,'[data-testid="candidate-campaign-panel"]',
  'CI3 failure reproduced: has begins by searching for outer panel inside label');
});
