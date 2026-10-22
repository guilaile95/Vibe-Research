import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const reactSource = readFileSync(join(dirname(require.resolve('react-dom/package.json')), 'cjs/react-dom-client.development.js'), 'utf8');
const playwrightSource = require(join(dirname(require.resolve('playwright-core/package.json')), 'lib/generated/injectedScriptSource.js')).source;
function namedFunction(source, name) {
  const ast = ts.createSourceFile('dependency.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const matches = [];
  function visit(node) { if (ts.isFunctionDeclaration(node) && node.name?.text === name) matches.push(node.getText(ast)); ts.forEachChild(node, visit); }
  visit(ast); assert.equal(matches.length, 1, `one actual dependency function ${name}`); return matches[0];
}
// Minimal DOM model: HTMLTextAreaElement.defaultValue replaces its child text.
// The code under test is the installed React update and Playwright label engine,
// not a restatement of their behavior. No browser or application server is used.
function fixture() {
  const label = { nodeName: 'LABEL', nodeType: 1, shadowRoot: null };
  const text = { nodeType: 3, nodeValue: '我的暂定看法', nextSibling: null };
  const area = { nodeName: 'TEXTAREA', nodeType: 1, value: '', firstChild: null, nextSibling: null, shadowRoot: null, labels: [label], getAttribute: () => null };
  Object.defineProperty(area, 'defaultValue', {
    get: () => area.firstChild?.nodeValue ?? '',
    set: value => { area.firstChild = { nodeType: 3, nodeValue: value, nextSibling: null }; },
  });
  label.firstChild = text; text.nextSibling = area;
  return area;
}
const context = vm.createContext({
  Node: { TEXT_NODE: 3, COMMENT_NODE: 8, ELEMENT_NODE: 1 }, HTMLInputElement: class {},
  getToStringValue: value => value, shouldSkipForTextMatching: () => false,
  normalizeWhiteSpace: value => value.replace(/\s+/g, ' ').trim(), getAriaLabelledByElements: () => null,
});
vm.runInContext([
  namedFunction(reactSource, 'updateTextarea'), namedFunction(playwrightSource, 'elementText'), namedFunction(playwrightSource, 'getElementLabels'),
].join('\n'), context);

test('actual React update changes the exact Playwright wrapping-label text while retaining the draft', () => {
  const area = fixture();
  assert.equal(context.getElementLabels(new Map(), area)[0].normalized, '我的暂定看法');
  context.updateTextarea(area, '未保存的合成看法', undefined);
  assert.equal(area.value, '未保存的合成看法');
  assert.equal(context.getElementLabels(new Map(), area)[0].normalized, '我的暂定看法未保存的合成看法');
});
test('candidate browser readback uses a unique stable field identity, not a broad label or first match', () => {
  const component = readFileSync(new URL('../src/components/campaign/CandidateResearchNote.tsx', import.meta.url), 'utf8');
  const browser = readFileSync(new URL('./e2e/research-navigation.browser.mjs', import.meta.url), 'utf8');
  const placeholder = '先写目前的理解，不必形成正式结论';
  assert.equal(component.split(`"${placeholder}"`).length - 1, 1);
  assert.ok(browser.includes(`page.getByTestId('candidate-research-note').getByPlaceholder('${placeholder}', { exact: true })`));
  assert.ok(browser.includes('await tentativeView.waitFor();\n      assert.equal(await tentativeView.count(), 1)'));
  assert.equal(browser.split("assert.equal(await tentativeView.inputValue(), '未保存的合成看法')").length - 1, 2);
  assert.ok(browser.includes("page.getByLabel('我的暂定看法', { exact: true }).fill"));
  assert.ok(!browser.includes("getByLabel('我的暂定看法', { exact: true }).inputValue"));
  assert.ok(browser.includes('stack: error.stack, dom'));
});
