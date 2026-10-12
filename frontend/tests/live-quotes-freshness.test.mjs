import assert from 'node:assert/strict';
import test from 'node:test';
import { harness, flush } from './helpers/liveQuotesHarness.mjs';
const q = (price, data_time = null) => ({ name: 'Synthetic', price, data_time, change_pct: -1, amount_wan: 0 });
const now = 1791770400000;
const recent = '2026-10-12T09:59:57+08:00';
const old = '2026-10-09T15:00:00+08:00';

test('actual hook exposes mixed provider ages and partial/empty coverage without fabricated timestamps', async () => {
  const h = harness({codes:['a','b']});
  h.requests[0].resolve({a:q(10,recent), b:q(20,old)}); await flush();
  assert.equal(h.state().updatedAt, Date.parse(old)); assert.equal(h.state().requestCompletedAt, now);
  assert.equal(h.state().snapshots.a.quoteTime, Date.parse(recent));
  h.state().refresh(); h.setNow(now+1000); h.requests[1].resolve({a:q(11,recent)}); await flush();
  assert.equal(h.state().quotes.b, undefined); assert.equal(h.state().snapshots.b.available, false);
  assert.match(h.state().error, /1\/2/); assert.equal(h.state().updatedAt, Date.parse(recent));
  assert.equal(h.state().requestCompletedAt, now+1000);
  h.state().refresh(); h.requests[2].resolve({}); await flush();
  assert.equal(h.state().updatedAt, null); assert.match(h.state().error, /0\/2/);
});
test('first manual failure marks retained snapshots stale immediately and recovery is per returned row', async () => {
  const h = harness({codes:['a','b']});
  h.requests[0].resolve({a:q(10,recent),b:q(20,old)}); await flush();
  h.state().refresh(); h.requests[1].reject(Error('fixture')); await flush();
  assert.equal(h.state().quotes.a.price,10); assert.equal(h.state().snapshots.a.stale,true);
  assert.equal(h.state().snapshots.b.stale,true); assert.match(h.state().error,/可点刷新重试/);
  assert.doesNotMatch(h.state().error,/正在重试/); assert.equal(h.timers.size,0);
  h.state().refresh(); h.requests[2].resolve({a:q(11,null)}); await flush();
  assert.equal(h.state().snapshots.a.stale,false); assert.equal(h.state().snapshots.a.timeIssue,'unknown');
  assert.equal(h.state().snapshots.b.available,false); assert.equal(h.state().updatedAt,null);
});
test('automatic first failure is visible and paused state does not promise retries', async () => {
  const h = harness({codes:['a']}); h.requests[0].resolve({a:q(10,recent)}); await flush();
  h.render({enabled:true}); h.render({enabled:false});
  h.requests[1].reject(Error('fixture')); await flush();
  assert.equal(h.state().polling,false); assert.equal(h.state().snapshots.a.stale,true);
  assert.match(h.state().error,/自动行情获取失败/); assert.doesNotMatch(h.state().error,/正在重试/);
  assert.equal(h.timers.size,0);
});
test('nontrading manual refresh still uses provider time and initial failure stays unavailable', async () => {
  const h = harness({codes:['a'],trading:false,enabled:true});
  h.requests[0].reject(Error('fixture')); await flush();
  assert.equal(h.state().snapshots.a.available,false); assert.equal(h.state().updatedAt,null);
  assert.match(h.state().error,/可点刷新重试/); assert.equal(h.state().polling,false);
  h.state().refresh(); h.requests[1].resolve({a:q(10,old)}); await flush();
  assert.equal(h.state().updatedAt,Date.parse(old)); assert.equal(h.state().snapshots.a.stale,false);
});
for (const reject of [false,true]) test(`pending old-list ${reject?'failure':'success'} cannot leak into new symbol`, async () => {
  const h = harness({codes:['a','b']}); h.requests[0].resolve({a:q(1,recent),b:q(2,old)}); await flush();
  h.state().refresh(); h.render({codes:['b','c']});
  if (reject) h.requests[1].reject(Error('fixture')); else h.requests[1].resolve({a:q(3,recent),b:q(4,recent)});
  await flush();
  assert.equal(h.state().quotes.a,undefined); assert.equal(h.state().snapshots.c.available,false);
  assert.equal(h.state().snapshots.c.stale,false); assert.equal(h.requests[2].requested,'b,c');
  h.requests[2].resolve({c:q(5,recent)}); await flush();
  assert.equal(h.state().snapshots.b.available,false); assert.equal(h.state().quotes.c.price,5);
});
test('empty list clears timestamp, coverage, error even after in-flight failure', async () => {
  const h = harness({codes:['a']}); h.render({codes:[]}); h.requests[0].reject(Error('fixture')); await flush();
  assert.deepEqual(Object.keys(h.state().quotes),[]); assert.equal(h.state().requestCompletedAt,null);
  assert.equal(h.state().updatedAt,null); assert.equal(h.state().error,null);
});
