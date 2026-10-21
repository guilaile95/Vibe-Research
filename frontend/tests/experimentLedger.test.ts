import test from 'node:test';
import assert from 'node:assert/strict';
import { ExperimentGeneration, experimentEndpoint } from '../src/lib/experimentLedger.ts';
import { readFileSync } from 'node:fs';

test('only existing bounded evaluator routes are available', () => {
  assert.equal(experimentEndpoint('rolling-signal'), '/signals/validation/rolling');
  assert.equal(experimentEndpoint('factor'), '/signals/factor-validation/evaluate');
  assert.equal(experimentEndpoint('signal'), '/signals/validation/evaluate');
  assert.throws(() => experimentEndpoint('../../trade'));
});
test('stale responses cannot replace a newer input, selection, or unmounted display', () => {
  const generation = new ExperimentGeneration();
  const previous = generation.next();
  const current = generation.next();
  assert.equal(generation.current(previous), false);
  assert.equal(generation.current(current), true);
  generation.next();
  assert.equal(generation.current(current), false);
});
test('UI captures only through an explicit button and does not persist private reports locally', () => {
  const source = readFileSync(new URL('../src/components/research/ExperimentLedger.tsx', import.meta.url), 'utf8');
  assert.match(source, /onClick={record}/);
  assert.match(source, /run\.current\.current\(token\)/);
  assert.match(source, /compare\.current\.current\(token\)/);
  assert.doesNotMatch(source, /localStorage|addNote|JSON\.stringify\(report/);
});
