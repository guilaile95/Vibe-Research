import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import * as parser from '../src/lib/watchlistImport.ts';
function harness(onApply = async () => true) {
  const slots = []; let cursor = 0; const saves = [];
  const React = {
    useState(initial) { const i=cursor++; if(!(i in slots)) slots[i]=initial; return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}]; },
    useRef(initial) { const i=cursor++; return slots[i]??={current:initial}; }, useEffect() {},
  };
  const modules={react:React,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/watchlistImport':parser,'./WatchlistOcr':{WatchlistOcr:()=>null}};
  const exports={};
  const source=ts.transpileModule(readFileSync(new URL('../src/components/watchlist/WatchlistImport.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(source,{exports,require:n=>modules[n]});
  const props={codes:['000858'],etag:'v1',disabled:false,onApply:async codes=>{saves.push(codes);return onApply(codes);}};
  return {props,saves,render(){cursor=0;return exports.WatchlistImport(props);}};
}
function nodes(tree){if(tree==null||typeof tree!=='object')return [];return Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)];}
function text(tree){if(tree==null||typeof tree==='boolean')return '';if(typeof tree!=='object')return String(tree);return Array.isArray(tree)?tree.map(text).join(''):text(tree.props?.children);}
function button(tree,label){return nodes(tree).find(n=>n.type==='button'&&text(n).includes(label));}
function fill(h,value){nodes(h.render()).find(n=>n.type==='textarea').props.onChange({target:{value}});button(h.render(),'预览导入').props.onClick();return h.render();}
const tick=()=>new Promise(r=>setImmediate(r));
test('preview is read-only and explicit apply sends only deduplicated codes',async()=>{
 const h=harness();let tree=fill(h,'code,name,shares\n600519,private name,999999\n000858,private,100');
 assert.equal(h.saves.length,0);assert.match(text(tree),/新增 1/);assert.doesNotMatch(text(tree),/private name|999999/);
 button(tree,'确认添加').props.onClick();await tick();tree=h.render();
 assert.deepEqual(h.saves,[['000858','600519']]);assert.equal(nodes(tree).find(n=>n.type==='textarea').props.value,'');assert.match(text(tree),/已添加 1/);
});
test('invalid, changed authority and edited drafts block old preview',()=>{
 const h=harness();let tree=fill(h,'code\n600519\nBAD');assert.equal(button(tree,'确认添加').props.disabled,true);
 tree=fill(h,'600519');h.props.etag='v2';tree=h.render();assert.equal(button(tree,'确认添加').props.disabled,true);assert.match(text(tree),/版本已变化/);
 nodes(tree).find(n=>n.type==='textarea').props.onChange({target:{value:'300750'}});assert.equal(button(h.render(),'确认添加'),undefined);assert.equal(h.saves.length,0);
});
test('save failure keeps input, clears stale preview and never automatically retries',async()=>{
 const h=harness(async()=>false);button(fill(h,'600519'),'确认添加').props.onClick();await tick();const tree=h.render();
 assert.equal(nodes(tree).find(n=>n.type==='textarea').props.value,'600519');assert.equal(button(tree,'确认添加'),undefined);assert.equal(h.saves.length,1);assert.match(text(tree),/未确认保存成功/);
});
test('double click has one write and cancellation invalidates pending local file read',async()=>{
 let done;const h=harness(()=>new Promise(r=>{done=r;}));const apply=button(fill(h,'600519'),'确认添加');apply.props.onClick();apply.props.onClick();assert.equal(h.saves.length,1);done(true);await tick();
 let resolve;const file={name:'watch.csv',size:20,text:()=>new Promise(r=>{resolve=r;})};const input=nodes(h.render()).find(n=>n.type==='input');const read=input.props.onChange({target:{files:[file],value:'file'}});button(h.render(),'取消').props.onClick();resolve('600519');await read;
 assert.equal(nodes(h.render()).find(n=>n.type==='textarea').props.value,'');assert.equal(button(h.render(),'确认添加'),undefined);
});
test('image/oversize files are rejected locally before reading',async()=>{
 const h=harness();for(const file of [{name:'private.png',size:10},{name:'watch.csv',size:parser.MAX_IMPORT_BYTES+1}]){
  await nodes(h.render()).find(n=>n.type==='input').props.onChange({target:{files:[{...file,text:()=>assert.fail('must not read')}],value:'file'}});assert.match(text(h.render()),/64 KiB/);
 }assert.equal(h.saves.length,0);
});
