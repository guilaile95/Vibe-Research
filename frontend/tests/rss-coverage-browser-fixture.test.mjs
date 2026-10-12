import assert from 'node:assert/strict';
import test from 'node:test';
import { rssCoverageFixture } from './e2e/rss-coverage.browser.mjs';

for (const mode of ['partial', 'unavailable', 'empty']) test(`RSS browser fixture preserves ${mode} coverage independently of article count`, () => {
  const f = rssCoverageFixture(mode);
  const radar = f.reply('GET', '/api/radar').json.data;
  assert.equal(radar.status, mode === 'empty' ? 'normal' : mode);
  assert.equal(radar.source_coverage.state, radar.status);
  assert.equal(radar.source_coverage.succeeded_sources, mode === 'unavailable' ? 0 : mode === 'partial' ? 1 : 2);
  assert.equal(radar.industries[0].items.length, mode === 'partial' ? 1 : 0);
  // backend/newsradar.py with_source_coverage derives attempted_sources from
  // sum(industry.total), where total is configured sources, not article count.
  assert.deepEqual(radar.industries.map(industry => industry.total), [2, 0]);
  assert.equal(radar.industries.reduce((sum, industry) => sum + industry.total, 0), radar.source_coverage.attempted_sources);
  assert.equal(radar.stats.total_sources, radar.source_coverage.expected_sources);
  assert.equal(radar.source_coverage.attempted_sources, radar.source_coverage.expected_sources);
  assert.equal(radar.source_coverage.succeeded_sources + radar.source_coverage.failed_sources, radar.source_coverage.attempted_sources);
  assert.equal(radar.stats.failed_sources, radar.source_coverage.failed_sources);
  for (const [path, query] of [['/api/native-intel/status', ''], ['/api/native-intel/items', '?limit=40&order_by=last_seen'], ['/api/native-intel/trending', '?window_hours=24&top_n=20']]) {
    assert.equal(f.reply('GET', path, query).status, 200);
  }
  assert.equal(f.reply('GET', '/api/intel-digests/latest', '?sector_key=ai').json.digest, null);
  assert.equal(f.reply('GET', '/api/intel-digests/latest', '?sector_key=saved').json.digest.summary_text, 'SYNTHETIC_SAVED_SUMMARY_STILL_READABLE');
  assert.deepEqual(f.unexpected, []);
});
test('RSS fixtures reject generation, saving, refresh and unrelated endpoints', () => {
  const f = rssCoverageFixture('unavailable');
  for (const [method, path, query] of [['POST', '/api/chat', ''], ['POST', '/api/intel-digests', ''], ['POST', '/api/radar/refresh', ''], ['GET', '/api/intel-digests/latest', '?sector_key=other'], ['GET', '/api/native-intel/items', '?limit=400']]) {
    assert.equal(f.reply(method, path, query).status, 503);
  }
  assert.equal(f.unexpected.length, 5);
});
