import test from 'node:test';
import assert from 'node:assert/strict';
import { observedBrowserAction } from './e2e/observed-browser-action.mjs';

test('observer rejection reaches normal failure capture while click remains blocked', async () => {
  const blockedClick = new Promise(() => {});
  await assert.rejects(observedBrowserAction(() => Promise.reject(Error('synthetic response timeout')), () => blockedClick), /synthetic response timeout/);
});
test('action rejection and later observer rejection both remain handled', async () => {
  let rejectObserver;
  const observation = new Promise((_, reject) => { rejectObserver = reject; });
  await assert.rejects(observedBrowserAction(() => observation, () => { throw Error('synthetic click failure'); }), /synthetic click failure/);
  rejectObserver(Error('later timeout'));
  await Promise.resolve();
});
test('observer is registered before action and its exact result is returned', async () => {
  const order = [], result = { status: 200 };
  assert.equal(await observedBrowserAction(() => { order.push('observe');return Promise.resolve(result); }, () => { order.push('click'); }), result);
  assert.deepEqual(order, ['observe', 'click']);
});
