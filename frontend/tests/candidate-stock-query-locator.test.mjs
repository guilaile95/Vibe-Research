import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

test('candidate code-switch locator owns the production query input despite preceding archive date inputs', () => {
 const source = readFileSync(new URL('../src/pages/StockData.tsx', import.meta.url), 'utf8');
 const ast = ts.createSourceFile('StockData.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
 const inputs = [];
 const visit = node => {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === 'input') inputs.push(node);
  ts.forEachChild(node, visit);
 };
 visit(ast);
 const placeholder = 'A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）';
 const matching = inputs.filter(node => node.attributes.properties.some(attr => ts.isJsxAttribute(attr) && attr.name.getText(ast) === 'placeholder' && attr.initializer?.text === placeholder));
 assert.equal(matching.length, 1);
 assert.match(matching[0].getText(ast), /setCode/);
 const browser = readFileSync(new URL('./e2e/candidate-campaign.browser.mjs', import.meta.url), 'utf8');
 assert.ok(browser.includes(`getByPlaceholder("${placeholder}", { exact: true }).fill("600520")`));
 assert.doesNotMatch(browser, /locator\(['"]input['"]\)\.first\(\)/);
 assert.ok(browser.includes('manual StockData code switch must bind the forwarded route to activeCode'));
});
