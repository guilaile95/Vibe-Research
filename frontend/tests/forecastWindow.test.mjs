import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
import ts from 'typescript';

// Execute production declarations and JSX, not a separately reimplemented view.
// Only unrelated evidence formatters are stubbed; no global clock is replaced.
const filename = fileURLToPath(new URL('../src/pages/StockData.tsx', import.meta.url));
const source = ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declarations = new Map();
const expressions = [];
function visit(node) {
  if (ts.isVariableDeclaration(node) && ['fmt', 'forecastMetrics', 'aiContext'].includes(node.name.getText(source))) declarations.set(node.name.getText(source), node.getText(source));
  if (ts.isJsxExpression(node) && (node.expression?.getText(source).startsWith('val.forecast_note &&') || node.expression?.getText(source).startsWith('forecastMetrics.map('))) expressions.push(node.getText(source));
  ts.forEachChild(node, visit);
}
visit(source);
assert.equal(declarations.size, 3);
assert.equal(expressions.length, 2);
const bundle = await build({stdin: {
  contents: `const ${declarations.get('fmt')};
    export function view(val) {
      const pctl = null, pctlResult = {}, fin = {}, announcementResult = {}, reportResult = {};
      const evidenceStatusText = () => '', financialEvidenceContext = () => '', quoteEvidenceContext = () => '', announcementEvidenceContext = () => '', reportEvidenceContext = () => '';
      const ${declarations.get('forecastMetrics')};
      const ${declarations.get('aiContext')};
      return {aiContext, forecastMetrics};
    }
    export function Forecast({val}) { const {forecastMetrics} = view(val); return <>${expressions.join('')}</>; }`,
  resolveDir: fileURLToPath(new URL('../', import.meta.url)), loader: 'tsx',
}, bundle: true, write: false, format: 'esm', platform: 'node', tsconfig: fileURLToPath(new URL('../tsconfig.json', import.meta.url))});
const {view, Forecast} = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const current = {name: 'Synthetic', code: '000001', price: 10, pe_ttm: 18, pb: 2, mcap_yi: 10, eps_26e: 1, eps_27e: 1.5, pe_26e: 10, peg: .2, digest_years: 0, analyst_count: 4};
const note = '2026→2027 一致预期窗口已过期；仅保留明确年度的 EPS 原始预测，不作为当前前向估值或评分依据';
test('expired production forecast JSX and AI context retain warning and explicit years', () => {
  const val = {...current, forecast_status: 'EXPIRED', forecast_note: note, pe_26e: null, peg: null, digest_years: null};
  const html = renderToStaticMarkup(createElement(Forecast, {val}));
  assert.ok(html.includes(note));
  assert.match(html, /26E PE/);
  assert.match(html, /26E EPS/);
  assert.equal(view(val).forecastMetrics.find(m => m.testId === 'stock-forecast-pe-26e').v, '—');
  const context = view(val).aiContext;
  assert.ok(context.includes(note));
  assert.match(context, /26E EPS 1 · 26E PE — · PEG —/);
  assert.match(context, /PE\(TTM\) 18.*PB 2/);
  assert.doesNotMatch(context, /前向PE/);
});
test('current 2026 fixture retains metrics including real zero', () => {
  const html = renderToStaticMarkup(createElement(Forecast, {val: current}));
  assert.ok(!html.includes('已过期'));
  assert.match(view(current).aiContext, /26E PE 10.*PEG 0.2.*消化 0年/);
});
