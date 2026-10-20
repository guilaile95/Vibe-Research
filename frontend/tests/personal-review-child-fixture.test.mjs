import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { personalReviewChildRead } from './e2e/personal-review.fixture.mjs';
import { parsePredictionJournal } from '../src/lib/predictionJournal.ts';
const url = path => new URL(`http://127.0.0.1${path}`);
const asOf = '2026-07-28T00:00:00Z';

test('personal review child GET returns an accurate empty journal at the parent fixture time', () => {
  const response = personalReviewChildRead('GET', url('/api/prediction-journal'), asOf);
  const data = parsePredictionJournal(response.data);
  assert.equal(data.as_of, asOf);
  assert.deepEqual(data.records, []);
  assert.equal(data.summary.total, 0);
  assert.equal(data.summary.unresolved, 0);
  assert.equal(data.summary.resolved_binary, 0);
  assert.equal(data.summary.brier, null);
  assert.equal(data.summary.benchmark_brier, null);
  assert.equal(data.summary.bins.length, 10);
});
test('child fixture does not accept writes, historical queries, subroutes or unrelated APIs', () => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) assert.equal(personalReviewChildRead(method, url('/api/prediction-journal'), asOf), null);
  for (const path of ['/api/prediction-journal?as_of=2026-01-01', '/api/prediction-journal/id/resolutions', '/api/prediction-journal/', '/api/personal-review', '/api/ai/chat', '/api/trades', '/api/unknown']) {
    assert.equal(personalReviewChildRead('GET', url(path), asOf), null);
  }
});
test('browser route keeps origin restriction and unknown-request failure assertions', () => {
  const source = readFileSync(new URL('./e2e/personal-review.browser.mjs', import.meta.url), 'utf8');
  assert.match(source, /url\.origin !== origin/);
  assert.match(source, /personalReviewChildRead\(req\.method\(\), url, fixture\.as_of\)/);
  assert.match(source, /forbidden\.push\(`api \$\{req\.method\(\)\} \$\{url\.pathname\}`\); return route\.abort\("blockedbyclient"\)/);
  assert.match(source, /assert\.deepEqual\(forbidden,\[\]\); assert\.deepEqual\(errors,\[\]\)/);
});
