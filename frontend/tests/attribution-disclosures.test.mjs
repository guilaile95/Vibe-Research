import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
async function component(path, name) {
 const bundle=await build({entryPoints:[fileURLToPath(new URL('../src/'+path,import.meta.url))],bundle:true,write:false,format:'esm',platform:'node',tsconfig:fileURLToPath(new URL('../tsconfig.json',import.meta.url))});
 return (await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`))[name];
}
const AttributionScopeNote=await component('components/review/AttributionScopeNote.tsx','AttributionScopeNote');
const AccountCoverageNote=await component('components/portfolio/AccountCoverageNote.tsx','AccountCoverageNote');
const result={as_of_date:'2026-10-01',date_from:'2026-09-01',date_to:null,selected_trade_count:0,positions:[{code:'600001',data_limitations:['无持仓成本基准，未计入']}]};
test('scope uses result dates, preserves zero count and explains actual fees and missing cost',()=>{
 const before=JSON.stringify(result);const html=renderToStaticMarkup(createElement(AttributionScopeNote,{result,historical:false}));
 for(const text of ['2026-09-01 至 不设结束','0 笔','不是报价日期','币种未提供','不折算成手','手续费和其他成本','不是再扣一次','600001：无持仓成本基准','不自动补入','部分合计不代表全部持仓'])assert.ok(html.includes(text),text);
 assert.equal(JSON.stringify(result),before);assert.doesNotMatch(html,/<(?:button|input|select)\b/);
});
test('old frozen results do not invent a date range, input count, currency or quote timestamp',()=>{
 const html=renderToStaticMarkup(createElement(AttributionScopeNote,{result:{positions:[]},historical:true}));
 for(const text of ['未记录 至 未记录','未记录（旧结果不推算）','原结果计算日期','历史快照原结果','币种未提供'])assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/人民币|CNY|0 笔/);
});
test('complete, partial and absent count coverage never assert temporal compatibility',()=>{
 for(const coverage of [{valid_holdings:2,total_holdings:2,complete:true},{valid_holdings:1,total_holdings:2,complete:false},undefined]){
  const html=renderToStaticMarkup(createElement(AccountCoverageNote,{coverage}));
  assert.ok(html.includes('无法确认时间兼容性'));assert.ok(html.includes('账户更新时间不是报价时间'));
  assert.ok(html.includes(coverage ? `${coverage.valid_holdings} / ${coverage.total_holdings}`:'未提供'));
  assert.ok(html.includes(coverage?.complete?'条目齐全':'不可用') || !coverage);
 }
});
