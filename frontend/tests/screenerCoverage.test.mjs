import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';
import ts from 'typescript';

const root=fileURLToPath(new URL('../',import.meta.url));
const path=`${root}src/pages/Screener.tsx`;
const source=ts.createSourceFile(path,readFileSync(path,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let card, group, fullSummary;
function visit(node){
 if(ts.isFunctionDeclaration(node)&&node.name?.text==='ResultGroup') group=node.getText(source);
 if(ts.isJsxElement(node)&&node.openingElement.attributes.properties.some(p=>ts.isJsxAttribute(p)&&p.name.text==='data-testid'&&p.initializer?.text==='screener-research-source'))card=node.getText(source);
 if(ts.isJsxElement(node)&&node.openingElement.attributes.properties.some(p=>ts.isJsxAttribute(p)&&p.name.text==='data-testid'&&p.initializer?.text==='full-market-summary'))fullSummary=node.getText(source);
 ts.forEachChild(node,visit);
}
visit(source);assert.ok(card);assert.ok(group);assert.ok(fullSummary);
const bundle=await build({stdin:{contents:`import {GlassCard} from './src/components/ui/GlassCard';
 import {candidateWorkspaceHref} from './src/lib/candidateCampaign';
 const Link=({children})=><a>{children}</a>;
 export function Source({result}){return ${card};}
 export function FullSummary({fullMarketResult}){return ${fullSummary};}
 export ${group}`,resolveDir:root,loader:'tsx'},bundle:true,write:false,format:'esm',platform:'node',tsconfig:`${root}tsconfig.json`});
const {Source,ResultGroup,FullSummary}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const base={research_data:{status:'partial',dataset_id:'synthetic',provider_id:'local',adjustment:'UNADJUSTED',as_of:'2026-05-30',coverage:{start:'2026-01-01',end:'2026-05-30',row_count:300,code_count:2},provenance:{artifact_sha256:'abc'},limitations:[]},batch_coverage:{requested_count:2,with_data_count:1,empty_count:1,failed_count:0,fully_evaluable_count:1,missing_condition_count:0,unavailable_count:1}};
const render=result=>renderToStaticMarkup(createElement(Source,{result})).replaceAll(/<!--.*?-->/g,'');
test('production source card separates partial request coverage from whole artifact',()=>{
 const before=JSON.stringify(base);const html=render(base);
 assert.match(html,/部分请求读到样本/);assert.match(html,/本次请求 2 股 · 读到样本 1 股 · 空样本 1 股 · 读取失败 0 股/);
 assert.match(html,/整份数据集覆盖（非本次请求）/);assert.match(html,/300 行 · 2 个代码/);
 assert.match(html,/全部条件可评估 1 股/);assert.equal(JSON.stringify(base),before);
});
test('empty request data does not claim available even when artifact exists',()=>{
 const html=render({...base,research_data:{...base.research_data,status:'unavailable'},batch_coverage:{...base.batch_coverage,with_data_count:0,empty_count:2,fully_evaluable_count:0,unavailable_count:2}});
 assert.match(html,/请求样本不可用/);assert.doesNotMatch(html,/全部请求已读到样本|部分请求读到样本/);
});
test('legacy response does not fabricate requested coverage',()=>{
 const html=render({...base,batch_coverage:undefined});assert.match(html,/本次请求覆盖未提供/);
 assert.doesNotMatch(html,/本次请求 2 股/);
});
for(const [status,rows,expected]of [['available',30,'30 行'],['empty',0,'0 行'],['unavailable',null,'未知 行']]){
 test(`production row keeps observed ${status} coverage and tri-state`,()=>{
 const item={code:'000001',trade_date:'2026-01-30',technical_status:'partial',limitations:[],data_coverage:{status,returned_rows:rows,start:status==='available'?'2026-01-01':null,end:status==='available'?'2026-01-30':null,cutoff:'2026-05-30',snapshot_id:'snapshot'},condition_results:[{id:'known_false',evaluable:true,passed:false,evidence:{}},{id:'missing',evaluable:false,passed:null,evidence:{}}]};
 const html=renderToStaticMarkup(createElement(ResultGroup,{title:'未命中',items:[item]}));
 assert.match(html,new RegExp(expected));assert.match(html,/不通过/);assert.match(html,/不可评估/);
 assert.match(html,/查询截止：2026-05-30/);
 if(status==='available')assert.match(html,/至 2026-01-30/);
 });
}


// Run the exact E2E assertion against production JSX, not a duplicate expected string.
const browserPath = `${root}tests/e2e/full-market-source-to-sink.browser.mjs`;
const browserSource = ts.createSourceFile(browserPath, readFileSync(browserPath, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
const summaryChecks = [];
function findSummaryCheck(node) {
 if (ts.isForOfStatement(node) && node.statement.getText(browserSource).includes('normal summary missing')) summaryChecks.push(node.getText(browserSource));
 ts.forEachChild(node, findSummaryCheck);
}
findSummaryCheck(browserSource);
assert.equal(summaryChecks.length, 1, 'Exactly one real browser summary assertion');
const checkBrowserSummary = new Function('summaryText', 'fixture', summaryChecks[0]);
const fullFixture = {
 status:'normal', as_of:'2026-03-07',
 coverage:{start:'2026-01-02',end:'2026-03-07',row_count:131,code_count:3,universe_count:3,current_count:3,stale_count:0},
 breadth:{ma20:{breadth:1,evaluable_count:2,insufficient_count:1,stale_count:0},ma60:{breadth:1,evaluable_count:2,insufficient_count:1,stale_count:0}},
 provenance:{artifact_sha256:'synthetic-hash',source_name:'full-market.csv'},limitations:[],
};
const summaryText = value => renderToStaticMarkup(createElement(FullSummary,{fullMarketResult:value}))
 .replaceAll(/<!--.*?-->/g,'').replaceAll(/<[^>]*>/g,' ').replaceAll(/\s+/g,' ').trim();
test('browser normal summary assertion agrees with actual production coverage wording',()=>{
 checkBrowserSummary(summaryText(fullFixture),{manifest:{artifact_sha256:'synthetic-hash'}});
});
for (const [name, patch] of [['wrong universe',{universe_count:2}], ['wrong current',{current_count:2}], ['stale promoted as current',{stale_count:1}], ['wrong row count',{row_count:130}]]) {
 test(`browser summary still rejects ${name}`,()=>{
  assert.throws(()=>checkBrowserSummary(summaryText({...fullFixture,coverage:{...fullFixture.coverage,...patch}}),{manifest:{artifact_sha256:'synthetic-hash'}}),/normal summary missing/);
 });
}
