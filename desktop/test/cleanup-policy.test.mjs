import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanupInOrder, uncertainProcessFailure } from './cleanup-policy.mjs';
test('only completed watchdog exits establish cleanup certainty', () => {
  for (const error of [{ status: 125 }, { status: null, signal: 'SIGKILL' }, { code: 'ENOBUFS', status: 1 }, { code: 'ENOENT' }]) assert.equal(uncertainProcessFailure(error), true);
  for (const status of [1, 2, 124, 130]) assert.equal(uncertainProcessFailure({ status }), false);
});
for (const uncertainAt of [0, 1]) test(`uncertainty during cleanup step ${uncertainAt} prevents every later mutation`, async () => {
  let uncertain = false;
  const calls = [];
  const result = await cleanupInOrder([0, 1, 2, 3].map(i => async () => {
    calls.push(i);
    if (i === uncertainAt) { uncertain = true; throw new Error('watchdog uncertain'); }
  }), () => uncertain);
  assert.deepEqual(calls, uncertainAt === 0 ? [0] : [0, 1]);
  assert.equal(result.uncertain, true);
  assert.equal(result.errors.length, 1);
});
test('preexisting uncertainty runs no cleanup', async () => {
  const result = await cleanupInOrder([() => assert.fail('must not mutate')], () => true);
  assert.equal(result.uncertain, true);
});
