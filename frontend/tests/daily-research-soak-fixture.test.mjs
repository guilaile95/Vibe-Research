import test from 'node:test';
import assert from 'node:assert/strict';
import { isExpectedSoakUnavailable as allowed, isExpectedSoakConsoleError as expectedConsole } from './e2e/daily-research-soak.fixture.mjs';
const routes = [
  ['/api/position/derived', ''],
  ...['stock-relative-context', 'stock-valuation-context', 'valuation', 'blocks', 'hot-concepts'].map(path => [`/api/${path}`, '?code=600519']),
  ['/api/market/top-risk', '?days=120&code=600519'],
  ['/api/research-events', '?security_code=600519'],
];
test('only mounted and explicitly unavailable soak sources match', () => {
  for (const [path, query] of routes) {
    assert.equal(allowed('GET', path, query), true, path);
    assert.equal(allowed('POST', path, query), false);
    assert.equal(allowed('GET', path, query + (query ? '&' : '?') + 'unexpected=1'), false);
    if (query) assert.equal(allowed('GET', path, query.replace('600519', '000001')), false);
  }
  assert.equal(allowed('GET', '/api/new-required-source', ''), false);
  assert.equal(allowed('GET', '/api/valuation', '?code=600519&code=600519'), false);
  assert.equal(allowed('GET', '/api/valuation', ''), false);
});
test('503 console exception is scoped to exact same-origin optional source URL', () => {
  const base = 'http://127.0.0.1:1234';
  const text = 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)';
  assert.equal(expectedConsole({ text, url: `${base}/api/valuation?code=600519` }, base), true);
  for (const url of ['', `${base}/api/unknown`, `${base}/api/valuation?code=000001`, 'https://example.com/api/valuation?code=600519']) assert.equal(expectedConsole({ text, url }, base), false);
  assert.equal(expectedConsole({ text: 'Unexpected runtime failure', url: `${base}/api/valuation?code=600519` }, base), false);
});
