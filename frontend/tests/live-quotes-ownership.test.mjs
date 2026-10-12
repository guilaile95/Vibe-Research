import assert from 'node:assert/strict';
import test from 'node:test';
import { harness, flush } from './helpers/liveQuotesHarness.mjs';

async function ready() {
  const h = harness(); h.requests[0].resolve({}); await flush();
  h.render({ enabled: true }); return h;
}
const delays = h => [...h.timers.values()].map(timer => timer.ms);

test('visibility reentry during a slow tick has one owner and no extra request', async () => {
  const h = await ready();
  for (let i = 0; i < 8; i++) { h.visibility(true); h.visibility(false); }
  await flush();
  assert.equal(h.requests.length, 2); assert.equal(h.timers.size, 0);
  h.requests[1].resolve({}); await flush();
  assert.equal(h.requests.length, 2); assert.deepEqual(delays(h), [3000]);
  h.fire(); assert.equal(h.requests.length, 3);
  h.requests[2].resolve({}); await flush(); assert.deepEqual(delays(h), [3000]);
});
test('visibility kick replaces idle timer and resumes immediately without dropping restart', async () => {
  const h = await ready(); h.requests[1].resolve({}); await flush();
  h.visibility(true); h.fire(); assert.equal(h.state().polling, false); assert.deepEqual(delays(h), [10000]);
  h.visibility(false); assert.equal(h.requests.length, 3); assert.equal(h.timers.size, 0);
  assert.equal(h.state().polling, true);
  h.requests[2].resolve({}); await flush(); assert.deepEqual(delays(h), [3000]);
});
test('hidden while pending settles into one heartbeat and does not fetch until visible', async () => {
  const h = await ready(); h.visibility(true); h.requests[1].resolve({}); await flush();
  assert.deepEqual(delays(h), [3000]); h.fire(); assert.equal(h.requests.length, 2);
  assert.deepEqual(delays(h), [10000]); h.fire(); assert.equal(h.requests.length, 2);
  h.visibility(false); assert.equal(h.requests.length, 3);
});
test('rejected fetch maintains one backoff timer through repeated visibility changes', async () => {
  const h = await ready(); h.visibility(true); h.visibility(false);
  h.requests[1].reject(new Error('synthetic failure')); await flush();
  assert.deepEqual(delays(h), [6000]); assert.match(h.state().error, /行情获取失败/);
  h.fire(); h.requests[2].reject(new Error('synthetic failure')); await flush();
  assert.deepEqual(delays(h), [12000]); assert.match(h.state().error, /行情获取失败/);
  h.fire(); h.requests[3].resolve({}); await flush();
  assert.deepEqual(delays(h), [3000]); assert.match(h.state().error, /行情未完整获取/);
});
for (const reject of [false, true]) test(`cleanup during pending ${reject ? 'failure' : 'success'} cannot resurrect scheduler`, async () => {
  const h = await ready(); h.unmount(); assert.equal(h.listeners.size, 0);
  if (reject) h.requests[1].reject(new Error('synthetic failure')); else h.requests[1].resolve({});
  await flush(); assert.equal(h.timers.size, 0);
});
test('disable and re-enable during pending request leaves only new effect timer', async () => {
  const h = await ready(); h.render({ enabled: false }); assert.equal(h.state().polling, false);
  h.render({ enabled: true }); await flush();
  h.requests[1].resolve({}); await flush();
  // Existing request coalescing performs one catch-up request, not a second scheduler.
  assert.equal(h.requests.length, 3); h.requests[2].resolve({}); await flush();
  assert.deepEqual(delays(h), [3000]); h.fire(); assert.equal(h.requests.length, 4);
});
test('symbol change during pending request retains catch-up and one scheduler', async () => {
  const h = await ready(); h.render({ codes: ['000002'] });
  h.visibility(true); h.visibility(false);
  h.requests[1].resolve({}); await flush();
  assert.equal(h.requests.length, 3); assert.equal(h.requests[2].requested, '000002');
  h.requests[2].resolve({}); await flush(); assert.deepEqual(delays(h), [3000]);
  h.fire(); assert.equal(h.requests[3].requested, '000002');
});
test('empty symbols pause and restoring symbols preserves immediate fetch and eventual loop', async () => {
  const h = await ready(); h.requests[1].resolve({}); await flush();
  h.render({ codes: [] }); await flush(); h.fire();
  assert.deepEqual(delays(h), [10000]); assert.equal(h.state().polling, false);
  h.render({ codes: ['000003'] }); assert.equal(h.requests[2].requested, '000003');
  h.requests[2].resolve({}); await flush(); h.fire(); assert.equal(h.requests[3].requested, '000003');
});
test('outside trading hours only one heartbeat survives kicks and trading resumes', async () => {
  const h = await ready(); h.requests[1].resolve({}); await flush(); h.setTrading(false);
  for (let i = 0; i < 5; i++) h.visibility(false);
  assert.deepEqual(delays(h), [10000]); assert.equal(h.requests.length, 2);
  h.setTrading(true); h.fire(); assert.equal(h.requests.length, 3);
});
test('manual refresh remains available with polling disabled', async () => {
  const h = harness(); h.requests[0].resolve({}); await flush();
  h.state().refresh(); assert.equal(h.requests.length, 2);
  h.requests[1].resolve({}); await flush(); assert.equal(h.timers.size, 0);
});

test('initial enabled mount and StrictMode effect replay preserve one scheduler', async () => {
  const h = harness({ enabled: true }); h.replayEffects();
  for (let i = 0; i < 5; i++) { h.visibility(true); h.visibility(false); }
  await flush(); assert.deepEqual(delays(h), [3000]);
  h.requests[0].resolve({}); await flush(); assert.equal(h.requests.length, 2);
  h.requests[1].resolve({}); await flush(); assert.deepEqual(delays(h), [3000]);
  h.unmount(); assert.equal(h.timers.size, 0); assert.equal(h.listeners.size, 0);
});
test('failure backoff stays capped and success restores original fixed interval', async () => {
  const h = await ready();
  for (const [i, delay] of [6000, 12000, 24000, 30000, 30000].entries()) {
    h.requests[i + 1].reject(new Error('synthetic failure')); await flush();
    assert.deepEqual(delays(h), [delay]); h.fire();
  }
  h.requests[6].resolve({}); await flush(); assert.deepEqual(delays(h), [3000]);
});
