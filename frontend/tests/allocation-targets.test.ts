import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseTargets } from '../src/lib/allocationTargetInput.ts';
test('explicit inputs only; zero preserved; no implicit cash', () => {
  assert.deepEqual(parseTargets('600000 60\nCASH 0'), { '600000': 60, CASH: 0 });
  assert.deepEqual(parseTargets('600000 33.33'), { '600000': 33.33 });
});
test('invalid values and duplicates rejected', () => {
  for (const text of ['', 'CASH NaN', 'CASH -1', 'CASH 100.01', 'CASH 33.333', 'CASH 0\nCASH 1', 'AAPL 10', '600000']) assert.throws(() => parseTargets(text));
});
test('UI hides stale numbers on refresh/expiry and preserves optimistic version', () => {
  const source = readFileSync(new URL('../src/components/portfolio/PortfolioAllocationCard.tsx', import.meta.url), 'utf8');
  assert.match(source, /setBusy\(true\); setData\(null\)/);
  assert.match(source, /expected_version: editVersion/);
  assert.match(source, /generation.current === request/);
  assert.match(source, /Date.parse\(data.valid_until\) - Date.now\(\)/);
  assert.match(source, /expired \? null : row.actual_pct/);
  assert.match(source, /expired \|\| row.drift_pp === null/);
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
});
