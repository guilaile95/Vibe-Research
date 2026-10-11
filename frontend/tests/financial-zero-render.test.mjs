import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
const bundle = await build({ entryPoints: [fileURLToPath(new URL('../src/components/ui/EarningsSnapshot.tsx', import.meta.url))], bundle: true, write: false, format: 'esm', platform: 'node', tsconfig: fileURLToPath(new URL('../tsconfig.json', import.meta.url)) });
const { EarningsSnapshot } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);

test('zero-valued summary facts render as zero, not missing or empty', () => {
  const fin = { revenue: 0, net_profit: 0, eps: 0, roe: 0, period_end: '2025-12-31', history: [], data_quality: { status: 'normal', missing_fields: [] } };
  const html = renderToStaticMarkup(createElement(EarningsSnapshot, { fin, error: null }));
  for (const label of ['营业总收入', '净利润', '基本每股收益', 'ROE']) {
    assert.match(html, new RegExp(`${label}</p><p[^>]*>0</p>`));
  }
  assert.doesNotMatch(html, /当前数据源未返回财务记录/);
  assert.match(html, /历史 PIT：不支持/);
});

const render = (fin, error = null) => renderToStaticMarkup(createElement(EarningsSnapshot, { fin, error }));
const summary = { revenue: 0, net_profit: 0, period_end: '2025-12-31', data_quality: { status: 'normal', missing_fields: [] } };

test('normal means checked fields available, with explicit unverified comparability and formatting assumptions', () => {
  const html = render(summary);
  assert.match(html, /字段状态：已检查字段齐备（不代表口径已核验）/);
  assert.match(html, /币种、单位、合并范围及修订版本尚未核验；同报告期末不代表口径已一致/);
  assert.match(html, /金额展示：标为“亿元”的金额暂按人民币元换算，源币种及单位未独立核验/);
  assert.match(html, /利润与现金流按报告期累计，资产负债为期末值；不推算单季变化/);
  assert.doesNotMatch(html, /本期字段完整|口径：报告期累计值/);
  // Normal does not guarantee all derived observations exist.
  assert.match(html, /自由现金流<\/p><p[^>]*>未知<\/p>/);
});

test('partial state retains missing count and discloses the same semantic limits', () => {
  const html = render({ ...summary, data_quality: { status: 'partial', missing_fields: ['operating_cash_flow'] } });
  assert.match(html, /字段状态：部分缺失（1）/);
  assert.match(html, /源币种及单位未独立核验/);
  assert.doesNotMatch(html, /已检查字段齐备/);
});

test('snapshot and history retain zero, negative, finite and unknown observations', () => {
  const row = { period_end: '2025-12-31', net_profit_amount: 0, operating_cash_flow: 200_000_000, free_cash_flow: -100_000_000, cash_conversion_ratio: 0 };
  const html = render({ ...summary, ...row, capital_expenditure: 0, free_cash_flow_margin: -0.05, total_debt: Infinity,
    history: [row, { period_end: '2025-09-30', net_profit_amount: null, operating_cash_flow: NaN, free_cash_flow: undefined, cash_conversion_ratio: null }] });
  for (const [label, value] of [['经营现金流', '2.00 亿元'], ['资本开支', '0.00 亿元'], ['自由现金流', '-1.00 亿元'], ['现金转化率', '0.0%'], ['自由现金流率', '-5.0%'], ['总负债', '未知']]) {
    assert.ok(html.includes(`${label}</p><p class="mt-0.5 font-mono text-base font-bold">${value}</p>`), label);
  }
  assert.match(html, /<summary[^>]*>查看最近 2 个报告期现金利润匹配<\/summary>/);
  assert.match(html, /按相同报告期末对齐；未知值不补零/);
  assert.match(html, /币种、单位、合并范围及修订版本未核验，累计期长度不同不直接作趋势比较/);
  const tbody = html.match(/<tbody>(.*?)<\/tbody>/)[1];
  const cells = [...tbody.matchAll(/<td[^>]*>(.*?)<\/td>/g)].map(match => match[1]);
  assert.deepEqual(cells, ['2025-12-31', '0.00 亿元', '2.00 亿元', '0.0%', '-1.00 亿元', '2025-09-30', '未知', '未知', '未知', '未知']);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test('empty and error states remain unavailable without implying a checked snapshot', () => {
  assert.match(render(null), /当前数据源未返回财务记录/);
  assert.match(render(summary, 'failed'), /财务数据暂不可用/);
  for (const html of [render(null), render(summary, 'failed')]) {
    assert.doesNotMatch(html, /已检查字段齐备|Data Quality|<table/);
  }
});
