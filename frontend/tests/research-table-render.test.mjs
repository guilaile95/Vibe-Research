import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFileSync} from 'node:fs';import ts from 'typescript';import * as analytics from '../src/lib/researchAnalytics.ts';
const exports={};const jsx=(type,props)=>typeof type==='function'?type(props):({type,props});
const mods={'react':{},'react/jsx-runtime':{jsx,jsxs:jsx,Fragment:'fragment'},'@/lib/researchAnalytics':analytics,'@/lib/api':{},'@/lib/notes':{},'@/lib/researchAnalyticsNote':{}};
const source=readFileSync(process.env.RESEARCH_TABLE_SOURCE || new URL('../src/pages/ResearchAnalytics.tsx',import.meta.url),'utf8')+'\nexport {RecordTable};';
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText,{exports,require:name=>mods[name]});
const label=x=>x==null?'':typeof x==='object'?Array.isArray(x)?x.map(label).join(' '):label(x.props?.children):String(x);
const nodes=x=>!x||typeof x!=='object'?[]:Array.isArray(x)?x.flatMap(nodes):[x,...nodes(x.props?.children)];
test('actual table renders metric value, status and missing reason without raw JSON',()=>{
 const rows=[{total_return:{status:'SUPPORTED',value:0.0669999,reason:null},trade_count:{status:'SUPPORTED',value:0,reason:null},sharpe:{status:'UNDEFINED',value:null,reason:'NO_CLOSED_TRADES'}}];const before=JSON.stringify(rows);
 const tree=exports.RecordTable({title:'comparison',rows}),text=label(tree);
 assert.match(text,/6\.70%/);assert.match(text,/已计算/);assert.match(text,/未定义/);assert.match(text,/原因：\s*NO_CLOSED_TRADES/);assert.doesNotMatch(text,/"status"|"value"|"reason"/);assert.equal(JSON.stringify(rows),before);
 assert.equal(nodes(tree).filter(n=>n.props?.['data-testid']==='research-table-metric').length,3);
 const region=nodes(tree).find(n=>n.props?.role==='region');assert.equal(region.props.tabIndex,0);assert.match(region.props.className,/overflow-auto/);assert.match(nodes(tree).find(n=>n.type==='table').props.className,/w-max min-w-full/);
});
