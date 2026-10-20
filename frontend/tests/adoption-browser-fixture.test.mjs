import test from 'node:test';
import assert from 'node:assert/strict';
import { syntheticApi } from './e2e/fixtures/adoption-api.mjs';
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
