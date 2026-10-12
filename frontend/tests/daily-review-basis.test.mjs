import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import * as helpers from '../src/lib/dailyReviewBasis.ts';
import {getDailyReviewAiRestoreTradeDate} from '../src/stores/dailyReviewAiResultMetadata.ts';

const source=readFileSync(new URL('../src/components/dailyReview/DailyReviewAiBasis.tsx',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const exports={};vm.runInNewContext(compiled,{exports,require:n=>{if(n==='react/jsx-runtime')return jsx;if(n==='@/lib/dailyReviewBasis')return helpers;throw Error('unexpected dependency '+n)}});
const Component=exports.DailyReviewAiBasis;
const result=()=>({result_type:'daily_review_ai',trade_date:'2026-07-23',schema_version:'daily_review_ai.v2',generated_at:'2026-07-23 16:00:00',model_provider:'fixture',model_name:'fixture',stale:false,payload:{markdown:'fixture',source_review_generated_at:'2026-07-23 15:30:00',source_data_cutoff:'2026-07-23 15:00:00',input_basis:{schema_version:'daily-review-input-basis.v1',context_schema_version:'daily-review-ai-context-v0.1',review_schema_version:'daily-review-v0.1',trade_date:'2026-07-23',source_review_generated_at:'2026-07-23 15:30:00',source_data_cutoff:'2026-07-23 15:00:00',review_status:'partial',component_statuses:Object.fromEntries(Object.keys(helpers.basisComponents).map(k=>[k,k==='breadth'?'partial':'unknown'])),omitted_component_count:1,warning_count:2,unknown_count:30,context_sha256:'a'.repeat(64)}}});
const render=r=>renderToStaticMarkup(createElement(Component,{result:r,currentTradeDate:'2026-07-24',currentCutoff:null}));
test('production JSX displays actual input gaps without asserting provider evidence',()=>{
 const r=result(),before=JSON.stringify(r),markup=render(r);
 assert.match(markup,/生成输入依据与缺口/);assert.match(markup,/部分缺失/);assert.match(markup,/输入警告 2 条/);assert.match(markup,/未知项 30 条/);
 assert.match(markup,/当前页面数据不能为旧结果补证/);assert.match(markup,/未记录逐供应商来源/);assert.match(markup,/不覆盖完整提示词和用户请求/);
 assert.equal(JSON.stringify(r),before);
});
test('historical v1 remains readable with explicitly absent capture',()=>{
 const r=result();r.schema_version='daily_review_ai.v1';delete r.payload.input_basis;
 assert.match(render(r),/此历史版本未记录/);assert.equal(getDailyReviewAiRestoreTradeDate(r),'2026-07-23');
 assert.equal(getDailyReviewAiRestoreTradeDate(result()),'2026-07-23');
});
test('malformed v2 cannot silently render as old v1 or validated basis',()=>{
 for(const mutate of [r=>delete r.payload.input_basis,r=>r.payload.input_basis.warning_count=true,r=>r.payload.input_basis.trade_date='2026-07-24',r=>r.payload.input_basis.component_statuses.private='normal',r=>r.payload.input_basis.component_statuses.breadth='toString',r=>r.payload.input_basis.extra='secret',r=>r.payload.input_basis.review_status=['normal'],r=>r.payload.input_basis.component_statuses.breadth=['normal'],r=>r.schema_version='daily_review_ai.v3']){
  const r=result();mutate(r);assert.equal(helpers.validatedReviewBasis(r),null);assert.match(render(r),/生成输入依据不可核对/);
 }
});
test('actual page wires disclosure without fetching or triggering AI',()=>{
 const page=readFileSync(new URL('../src/pages/DailyReview.tsx',import.meta.url),'utf8');
 assert.match(page,/<DailyReviewAiBasis result=\{taskResultMeta\}/);
 assert.doesNotMatch(source,/fetch\(|useEffect|setInterval|localStorage/);
});

test('basis rejects matching but impossible dates and normalized timestamps',()=>{
 for(const day of ['2026-02-30','0000-01-01','2025-02-29','2026-13-01']){
  const r=result();r.trade_date=day;r.payload.input_basis.trade_date=day;
  assert.equal(helpers.validatedReviewBasis(r),null);
 }
 for(const stamp of ['2026-02-30 12:00:00','2026-07-23 24:00:00','2026-07-23 12:60:00','2026-07-23T12:00:00+24:00','2026-07-23']){
  const r=result();r.payload.source_review_generated_at=stamp;r.payload.input_basis.source_review_generated_at=stamp;
  assert.equal(helpers.validatedReviewBasis(r),null);
 }
 const bad=result();bad.result_type='portfolio_advice';assert.equal(helpers.validatedReviewBasis(bad),null);
 for(const stamp of ['2026-07-23 15:30:00','2026-07-23T15:30:00+08:00','2026-07-23T07:30:00.123456Z']){
  const r=result();r.payload.source_review_generated_at=stamp;r.payload.input_basis.source_review_generated_at=stamp;
  assert.ok(helpers.validatedReviewBasis(r));
 }
});
