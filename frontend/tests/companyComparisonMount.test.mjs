import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/pages/StockData.tsx', import.meta.url), 'utf8');
const file = ts.createSourceFile('StockData.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function all(root, predicate) {
  const found = [];
  const visit = node => { if (predicate(node)) found.push(node); ts.forEachChild(node, visit); };
  visit(root); return found;
}
const mount = name => {
  const nodes = all(file, n => ts.isJsxSelfClosingElement(n) && n.tagName.getText(file) === name);
  assert.equal(nodes.length, 1, 'one actual mount of ' + name); return nodes[0];
};
function expression(node, name) {
  const attr = node.attributes.properties.find(p => ts.isJsxAttribute(p) && p.name.getText(file) === name);
  assert.ok(attr && attr.initializer && ts.isJsxExpression(attr.initializer) && attr.initializer.expression, name + ' expression required');
  return attr.initializer.expression;
}
const canonical = node => ts.createPrinter({ removeComments: true }).printNode(ts.EmitHint.Unspecified, node, file).replace(/\s+/g, ' ').trim();
function evaluate(node, inputs) {
  const code = ts.transpileModule('(' + node.getText(file) + ')', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return vm.runInNewContext(code, inputs);
}
function namedImport(name, from) {
  return file.statements.some(n => ts.isImportDeclaration(n) && n.moduleSpecifier.text === from &&
    n.importClause?.namedBindings && ts.isNamedImports(n.importClause.namedBindings) &&
    n.importClause.namedBindings.elements.some(e => e.name.text === name));
}

test('research and comparison are direct siblings with identical returned subject and distinct keys', () => {
  const research = mount('CompanyResearchPanel'), comparison = mount('CompanyComparisonCard');
  assert.equal(research.parent, comparison.parent);
  assert.ok(ts.isJsxFragment(research.parent), 'shared conditional fragment retains both panels');
  const rSubject = expression(research, 'subject'), cSubject = expression(comparison, 'subject');
  assert.equal(canonical(rSubject), canonical(cSubject));
  const rKey = expression(research, 'key'), cKey = expression(comparison, 'key');
  for (const [inputs, identity] of [
    [{ gstock: null, val: { code: '600000' } }, { market: 'A', symbol: '600000' }],
    [{ gstock: { market: 'US', code: 'AAPL' }, val: null }, { market: 'US', symbol: 'AAPL' }],
    [{ gstock: { market: 'HK', code: '00700' }, val: null }, { market: 'HK', symbol: '00700' }],
  ]) {
    assert.equal(JSON.stringify(evaluate(rSubject, inputs)), JSON.stringify(identity));
    assert.equal(JSON.stringify(evaluate(cSubject, inputs)), JSON.stringify(identity));
    assert.equal(evaluate(rKey, inputs), 'research:' + identity.market + ':' + identity.symbol);
    assert.equal(evaluate(cKey, inputs), 'comparison:' + identity.market + ':' + identity.symbol);
    assert.notEqual(evaluate(rKey, inputs), evaluate(cKey, inputs));
  }
});

test('StockData mount only supplies identity and key, without automatic action expressions', () => {
  for (const name of ['CompanyResearchPanel', 'CompanyComparisonCard']) {
    const node = mount(name);
    assert.deepEqual(node.attributes.properties.map(p => {
      assert.ok(ts.isJsxAttribute(p), 'no opaque prop spread'); return p.name.getText(file);
    }).sort(), ['key', 'subject']);
    assert.equal(all(node.attributes, n => ts.isCallExpression(n) || ts.isNewExpression(n)).length, 0);
  }
  // Actual component manual-start/effect behavior is tested separately in
  // companyComparisonUi.test.mjs; this test covers only shared mount wiring.
});

test('comparison mount retains qualified financial context and selected-result Debate imports', () => {
  assert.ok(namedImport('CompanyComparisonCard', '@/components/research/CompanyComparisonCard'));
  assert.ok(namedImport('CompanyResearchPanel', '@/components/research/CompanyResearchPanel'));
  assert.ok(namedImport('financialEvidenceContext', '@/lib/stockDataEvidence'));
  assert.ok(namedImport('stockDebateHrefForResult', '@/lib/debateHandoff'));
  const calls = all(file, ts.isCallExpression);
  const financial = calls.filter(n => n.expression.getText(file) === 'financialEvidenceContext');
  assert.equal(financial.length, 1);
  assert.deepEqual(financial[0].arguments.map(n => n.getText(file)), ['fin']);
  const handoff = calls.filter(n => n.expression.getText(file) === 'stockDebateHrefForResult');
  assert.equal(handoff.length, 1);
  assert.deepEqual(handoff[0].arguments.map(n => n.getText(file)), ['activeCode', 'val', 'gstock']);
  assert.doesNotMatch(source, /fin\?\.revenue\s*\?/);
});
