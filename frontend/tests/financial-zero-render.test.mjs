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
