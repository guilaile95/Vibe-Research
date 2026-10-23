import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import { candidateWorkspaceHref } from '../src/lib/candidateCampaign.ts';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const source = readFileSync(new URL('../src/pages/Portfolio.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('Portfolio.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let row;
function visit(node) {
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(ast) === 'tr' && node.getText(ast).includes('{h.name}')) row = node.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
const code = ts.transpileModule(`const render = () => (${row});`, { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText;
function renderRow(h, canonicalHoldings = false) {
  const deps = { React, h, canonicalHoldings, Link: ({ to, children, ...props }) => React.createElement('a', { href: to, ...props }, children),
    fmtPx: String, fmt: String, fmtSigned: String, fmtPct: String, fmtExposurePct: String, exposurePct: () => 0,
    exposureBasis: {}, cn: (...args) => args.join(' '), pnlColor: () => '', openEdit: () => {}, Pencil: () => null, Trash2: () => null,
    candidateWorkspaceHref,
  };
  return renderToStaticMarkup(new Function(...Object.keys(deps), `${code}; return render();`)(...Object.values(deps)));
}
const holding = { code: '600519', name: 'Synthetic company', price: 10, shares: 100, cost: 8, market_value: 1000, pnl: 200, pnl_pct: 25 };

test('supported holding has separate direct data/research links without selecting a formal plan', () => {
  for (const canonical of [false, true]) {
    const html = renderRow(holding, canonical);
    assert.match(html, /href="\/stock-data\?code=600519&amp;return_to=%2Fportfolio%23portfolio-holding-600519"/);
    assert.match(html, /href="\/candidates\/600519\?return_to=%2Fportfolio%23portfolio-holding-600519"/);
    assert.match(html, />查看数据<\/a>/); assert.match(html, />候选研究<\/a>/);
    assert.doesNotMatch(html, /[?&](?:campaign|question|round|action|create)=/);
    assert.equal(html.includes('title="编辑"'), !canonical);
    assert.equal(html.includes('title="删除"'), !canonical);
  }
});

test('unsupported identities remain plain rows without guessing a market or changing editing', () => {
  for (const code of ['00700', 'AAPL', '005930.KS', '600519.SH', '60051', '', '600519?create=1', ' 600519']) {
    const html = renderRow({ ...holding, code });
    assert.doesNotMatch(html, /<a /, code);
    assert.match(html, /title="编辑"/);
  }
});
