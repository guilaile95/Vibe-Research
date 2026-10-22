import assert from 'node:assert/strict';
import test from 'node:test';
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
