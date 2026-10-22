import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { navigationEvidencePage } from './e2e/research-navigation.fixture.mjs';
import { loadCandidateEvidence, CandidateEvidenceLoadError } from '../src/lib/candidateEvidence.ts';

const record = { id: 'synthetic-evidence', subject_type: 'stock', subject_id: '600519', claim: 'Synthetic saved evidence', deleted: 0 };
function load(records, code = '600519') {
  return loadCandidateEvidence(async params => navigationEvidencePage(records, new URLSearchParams({
    subject_type: 'stock', subject_id: code, limit: String(params.limit), offset: String(params.offset),
  })), () => false);
}
test('browser evidence fixture is accepted before and after synthetic save by the real candidate loader', async () => {
  assert.deepEqual(await load([]), { records: [], total: 0 });
  assert.deepEqual(await load([record]), { records: [record], total: 1 });
  assert.deepEqual(await load([record], '600520'), { records: [], total: 0 });
  assert.deepEqual(await load([{ ...record, deleted: 1 }]), { records: [], total: 0 });
});
test('fixture honors pagination including the actual loader head consistency check', async () => {
  const records = Array.from({ length: 201 }, (_, n) => ({ ...record, id: `synthetic-${n}` }));
  assert.deepEqual(await load(records), { records, total: 201 });
});
test('missing offset from the original CI fixture remains rejected by production guard', async () => {
  await assert.rejects(() => loadCandidateEvidence(async () => ({ items: [record], total: 1 }), () => false), CandidateEvidenceLoadError);
});

test('browser cancellation targets the candidate-specific draft dialog, not the generic form dialog', () => {
  const component = readFileSync(new URL('../src/components/campaign/CandidateResearchNote.tsx', import.meta.url), 'utf8');
  const browser = readFileSync(new URL('./e2e/research-navigation.browser.mjs', import.meta.url), 'utf8');
  assert.match(component, /<h2[^>]*>研究内容尚未保存<\/h2>/);
  assert.match(component, /onClick=\{\(\) => \{ if \(blocker.state === "blocked"\) blocker.reset\(\); \}\}>留下继续编辑<\/button>/);
  assert.ok(browser.includes("dialog.getByRole('button', { name: '留下继续编辑', exact: true }).click()"));
  assert.ok(!browser.includes("name: '留在此页'"));
  assert.ok(browser.includes("await dialog.waitFor({ state: 'hidden' });"));
  assert.ok(browser.includes("await page.goBack(); await dialog.waitFor();\n      await page.waitForURL(url => url.pathname === '/candidates/600519');"));
  assert.ok(browser.includes("await page.waitForURL(url => url.pathname === '/stock-data' && url.searchParams.get('code') === '600519');"));
  assert.ok(browser.includes("dialog.getByRole('button', { name: '放弃未保存内容并离开', exact: true }).click()"));
});
