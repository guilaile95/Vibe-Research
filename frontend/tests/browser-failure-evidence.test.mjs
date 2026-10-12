import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { captureBrowserFailure } from './e2e/browser-failure-evidence.mjs';

test('failure evidence keeps request audit and scoped DOM when target is hidden and screenshot fails', async () => {
  const output = mkdtempSync(path.join(tmpdir(), 'vr-failure-unit-'));
  const card = { first() { return this; }, count: async () => 1, evaluate: async () => '<div data-testid="target">hidden synthetic card</div>', isVisible: async () => false };
  const page = { isClosed: () => false, locator: () => card, content: async () => '<details><div data-testid="target">hidden synthetic card</div></details>', screenshot: async () => { throw Error('synthetic screenshot failure'); } };
  const audit = { requests: [{ method: 'GET', path: '/api/known', search: '?date=2026-07-31' }] };
  const result = await captureBrowserFailure({ page, output, prefix: '390', selector: '[data-testid=target]', error: Error('timed out'), audit });
  assert.match(readFileSync(path.join(output, '390-failure.html'), 'utf8'), /<details>/);
  assert.match(readFileSync(path.join(output, '390-failure-fragment.html'), 'utf8'), /hidden synthetic card/);
  assert.equal(result.capture_errors.length, 2);
  assert.deepEqual(JSON.parse(readFileSync(path.join(output, '390-failure.json'), 'utf8')).audit, audit);
});

test('failure manifest survives a browser startup failure without a page', async () => {
  const output = mkdtempSync(path.join(tmpdir(), 'vr-failure-unit-'));
  await captureBrowserFailure({ output, prefix: 'startup', selector: 'main', error: Error('launch failed'), audit: { reads: [] } });
  assert.ok(existsSync(path.join(output, 'startup-failure.json')));
});
