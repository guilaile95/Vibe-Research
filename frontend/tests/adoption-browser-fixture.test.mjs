import test from 'node:test';
import assert from 'node:assert/strict';
import { syntheticApi, auditMutationReadbacks } from './e2e/fixtures/adoption-api.mjs';
import { parsePredictionJournal, verifyPredictionWrite } from '../src/lib/predictionJournal.ts';
const url = path => new URL(`http://127.0.0.1/api${path}`);
test('synthetic journal receipts satisfy production parser and exact readback contracts', () => {
  const { dispatch } = syntheticApi();
  assert.equal(parsePredictionJournal(dispatch('GET', url('/prediction-journal'))).summary.brier, null);
  const forecast = { id: 'fixture', subject: 'Synthetic', question: 'Binary?', probability: .7, deadline: '2030-01-01T00:00:00Z', evidence_context: 'Synthetic', evidence_kind: 'USER_ASSERTION', outcome_not_known: true, benchmark_probability: null, benchmark_context: null };
  dispatch('POST', url('/prediction-journal'), forecast);
  verifyPredictionWrite(parsePredictionJournal(dispatch('GET', url('/prediction-journal'))), 'fixture', forecast, true);
  const resolution = { expected_revision: 0, outcome: 'TRUE', available_at: '2030-01-02T00:00:00Z', evidence: 'Synthetic evidence', evidence_kind: 'USER_ASSERTION', correction_reason: 'Synthetic reason' };
  dispatch('POST', url('/prediction-journal/fixture/resolutions'), resolution);
  const data = parsePredictionJournal(dispatch('GET', url('/prediction-journal')));
  verifyPredictionWrite(data, 'fixture', resolution, false);
  assert.ok(Math.abs(data.summary.brier - .09) < 1e-12);
});
test('unknown and consequential routes are rejected rather than silently mocked', () => {
  for (const route of ['/ai/chat', '/trades', '/evidence/anchor', '/provider/refresh']) {
    assert.throws(() => syntheticApi().dispatch('POST', url(route), {}), /Unexpected synthetic route/);
  }
});
test('annotation stale failure does not mutate synthetic archive', () => {
  const { state, dispatch } = syntheticApi();
  state.failAnnotation = true;
  assert.equal(dispatch('POST', url('/research-annotations'), {}).errorStatus, 409);
  assert.deepEqual(state.notes, []);
});

test('browser selectors distinguish explicit aria labels from nested select label text', async () => {
  const { readFile } = await import('node:fs/promises');
  const runner = await readFile(new URL('./e2e/adoption-workflows.browser.mjs', import.meta.url), 'utf8');
  // These production labels wrap select options; exact getByLabel(label) would
  // include option text and fail even when the real control is visible.
  for (const name of ['币种', 'FCF 口径', '结果', '同一个股的另一条证据', '关系']) {
    assert.ok(runner.includes(`getByRole('combobox', { name: /^${name}/ })`), name);
    assert.ok(!runner.includes(`getByLabel('${name}', { exact: true })`), name);
  }
  assert.ok(runner.includes("dcf.getByRole('group', { name: label, exact: true })"));
  // Filing selectors have explicit aria-labels and retain exact matching.
  for (const name of ['更正旧版本', '旧文档', '新文档']) {
    assert.ok(runner.includes(`getByLabel('${name}', { exact: true })`), name);
  }
});

test('readback audit never borrows another viewport or workflow evidence', () => {
  assert.equal(auditMutationReadbacks([]).length, 10);
  const calls = [
    { case: 'annotation-1280', method: 'POST', path: '/research-annotations' },
    { case: 'annotation-1280', method: 'GET', path: '/research-annotations' },
    { case: 'annotation-375', method: 'GET', path: '/research-annotations' },
    { case: 'annotation-375', method: 'POST', path: '/research-annotations' },
    { case: 'groups-375', method: 'GET', path: '/research-annotations' },
  ];
  let missing = auditMutationReadbacks(calls);
  assert.equal(missing.length, 9);
  assert.ok(missing.some(row => row.case === 'annotation-375'));
  assert.ok(!missing.some(row => row.case === 'annotation-1280'));
  calls.push({ case: 'annotation-375', method: 'GET', path: '/research-annotations' });
  missing = auditMutationReadbacks(calls);
  assert.equal(missing.length, 8);
  assert.ok(!missing.some(row => row.case === 'annotation-375'));
});

test('subject reset waits for value and historical read-only check opens remounted details', async () => {
  const { readFile } = await import('node:fs/promises');
  const runner = await readFile(new URL('./e2e/adoption-workflows.browser.mjs', import.meta.url), 'utf8');
  const subjectSwitch = runner.slice(runner.indexOf("await nav('Switch subject');"));
  const wait = subjectSwitch.indexOf('await page.waitForFunction(');
  const emptyAssertion = subjectSwitch.indexOf("assert.equal(await dcf.getByLabel('参考股价数值', { exact: true }).inputValue(), '');");
  assert.ok(wait >= 0 && emptyAssertion > wait, 'wait for reset value before asserting empty');
  assert.ok(subjectSwitch.includes("input[aria-label=\"参考股价数值\"]')?.value === ''"));
  const history = runner.slice(runner.indexOf(".fill('2031-01-01T00:00');"));
  const open = history.indexOf("await record.getByText('追加人工结果 / 修正（不重写原预测）', { exact: true }).click();");
  const visible = history.indexOf("await shown(record.getByRole('button', { name: '追加结果修订' }));");
  const disabled = history.indexOf("assert.equal(await record.getByRole('button', { name: '追加结果修订' }).isDisabled(), true);");
  assert.ok(open >= 0 && visible > open && disabled > visible, 'open reloaded details and assert visible button remains disabled');
});

test('DCF fixture preserves production subject-key remount and blank-submit boundary', async () => {
  const { readFile } = await import('node:fs/promises');
  const production = await readFile(new URL('../src/components/research/CompanyResearchPanel.tsx', import.meta.url), 'utf8');
  const fixture = await readFile(new URL('./e2e/fixtures/adoption-workflows.tsx', import.meta.url), 'utf8');
  const boundary = '<ReverseDcfCard key={`${subject.market}:${subject.symbol}`} subject={subject} />';
  assert.ok(production.includes(boundary), 'production isolates every subject with a React key');
  assert.ok(fixture.includes(boundary), 'fixture must use the same identity boundary');
  const runner = await readFile(new URL('./e2e/adoption-workflows.browser.mjs', import.meta.url), 'utf8');
  assert.ok(runner.includes("for (const input of await dcf.locator('input').all()) assert.equal(await input.inputValue(), ''"));
  assert.ok(runner.includes("assert.equal(state.calls.length, callsBeforeSubjectSwitch, 'old-company inputs must not submit for a new subject')"));
});
