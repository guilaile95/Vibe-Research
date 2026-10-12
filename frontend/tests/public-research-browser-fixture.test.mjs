import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { parsePublicResearch } from '../src/lib/publicResearch.ts';
import { publicResearchPaths, publicResearchStaticAllowed, publicResearchSource, PUBLIC_RESEARCH_CLOCK, PUBLIC_RESEARCH_SOURCES } from './e2e/public-research.fixture.mjs';

test('relative CI output resolves once to the same absolute Vite and static root', () => {
  const frontend = path.resolve('synthetic/frontend');
  const paths = publicResearchPaths(frontend, 'public-research-evidence');
  assert.equal(paths.output, path.join(frontend, 'public-research-evidence'));
  assert.equal(paths.dist, path.join(frontend, 'public-research-evidence/page-dist'));
  assert.equal(path.resolve(frontend, 'tests/e2e/public-research-adapter', paths.dist), paths.dist);
});

test('exact source query and static navigation routes admit no method, date or query drift', () => {
  for (const source of PUBLIC_RESEARCH_SOURCES) {
    assert.equal(publicResearchSource('GET', '/api/public-research', `?source_id=${source}`), source);
    for (const query of ['', `?source_id=${source}&refresh=1`, `?source_id=${source}&source_id=${source}`, `?source_id=${source}&trade_date=2026-10-12`, `?source_id=${source.replace('_', '%5F')}`]) {
      assert.equal(publicResearchSource('GET', '/api/public-research', query), null);
    }
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']) assert.equal(publicResearchSource(method, '/api/public-research', `?source_id=${source}`), null);
  }
  assert.equal(publicResearchSource('GET', '/api/public-research/', '?source_id=public_kalshi'), null);
  assert.equal(publicResearchStaticAllowed('GET', '/', '?tab=events'), true);
  assert.equal(publicResearchStaticAllowed('GET', '/', '?tab=industry'), true);
  assert.equal(publicResearchStaticAllowed('GET', '/', '?tab=industry&refresh=1'), false);
  assert.equal(publicResearchStaticAllowed('POST', '/', ''), false);
  assert.equal(publicResearchStaticAllowed('GET', '/assets/index.js', '?x=1'), false);
  assert.equal(publicResearchStaticAllowed('GET', '/assets/index.js', ''), true);
});

test('every browser source golden passes the production guard at the actual browser clock', () => {
  const original = Date.now;
  try {
    Date.now = () => Date.parse(PUBLIC_RESEARCH_CLOCK);
    const golden = JSON.parse(readFileSync(new URL('./fixtures/public-research.golden.json', import.meta.url), 'utf8'));
    assert.deepEqual(Object.keys(golden).sort(), [...PUBLIC_RESEARCH_SOURCES].sort());
    for (const source of PUBLIC_RESEARCH_SOURCES) assert.equal(parsePublicResearch(golden[source], source).fixture, true);
  } finally { Date.now = original; }
});

test('both browser lanes preserve failure evidence and P5 opens its actual parent disclosure', () => {
  const p5 = readFileSync(new URL('./e2e/shortline-review.browser.mjs', import.meta.url), 'utf8');
  const publicSource = readFileSync(new URL('./e2e/public-research.browser.mjs', import.meta.url), 'utf8');
  const disclosure = "await page.locator('#market-detail-short-history > summary').click()";
  assert.ok(p5.indexOf(disclosure) > 0 && p5.indexOf(disclosure) < p5.indexOf('await card.waitFor()'));
  assert.match(p5, /captureBrowserFailure/); assert.match(p5, /baseViolations/);
  assert.match(publicSource, /captureBrowserFailure/); assert.match(publicSource, /phase, cases, audit/);
  assert.match(publicSource, /Vite output must exist at the exact static-server path/);
  for (const source of [p5, publicSource]) assert.doesNotMatch(source, /waitForTimeout|pauseAt/);
});
