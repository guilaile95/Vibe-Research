import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ExperimentGeneration, experimentEndpoint } from '../src/lib/experimentLedger.ts';

const source = readFileSync(new URL('../src/components/signals/RollingSignalValidationPanel.tsx', import.meta.url), 'utf8');
test('rolling entry exposes predeclared complete preset and bounded unit labels', () => {
  assert.match(source, /sma-fast-neighbors-v1/);
  for (const parameter of ['15\/60', '20\/60', '25\/60']) assert.match(source, new RegExp(parameter));
  assert.match(source, /已存储观测，不是交易日/);
  assert.match(source, /calendar_gaps_omitted/);
  assert.match(source, /events_purged_label_end/);
  assert.match(source, /NOT_EVALUATED/);
  assert.match(source, /report\.trials\.map/);
  assert.match(source, /kind="rolling-signal" input={input}/);
  assert.equal(experimentEndpoint('rolling-signal'), '/signals/validation/rolling');
});
test('input changes, cancellation and unmount reject older results', () => {
  const state = new ExperimentGeneration();
  const pending = state.next();
  state.next();
  assert.equal(state.current(pending), false);
  assert.match(source, /controller\.current\?\.abort\(\)/);
  assert.match(source, /generation\.current\.current\(token\)/);
  assert.match(source, /\}, \[input\]\)/);
  assert.match(source, /setReport\(null\)/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|setInterval/);
});
