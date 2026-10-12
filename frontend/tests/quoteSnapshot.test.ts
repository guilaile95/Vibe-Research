import assert from 'node:assert/strict';
import test from 'node:test';
import { providerQuoteTime, quoteSnapshotStates, quoteSnapshotTime, quoteSnapshotLabel, validQuoteRows } from '../src/lib/quoteSnapshot.ts';
import type { Quote } from '../src/lib/api/types.ts';
const quote = (price: number, data_time: string | null = null) => ({ price, data_time } as Quote);

test('provider time requires real full date and explicit zone, preserving offset equivalence', () => {
  assert.equal(providerQuoteTime('2026-10-12T10:00:00+08:00'), Date.parse('2026-10-12T02:00:00Z'));
  assert.notEqual(providerQuoteTime('2024-02-29T00:00:00Z'), null);
  for (const value of [null, undefined, '', 'invalid', '2026-10-12', '2026-10-12T10:00:00', '2026-02-30T00:00:00Z', '2025-02-29T00:00:00Z', '2026-00-01T00:00:00Z', '2026-01-00T00:00:00Z', '2026-01-01T24:00:00Z', '2026-01-01T23:60:00Z', '2026-01-01T23:00:60Z', '2026-01-01T00:00:00+14:01', '2026-01-01T00:00:00+25:00']) assert.equal(providerQuoteTime(value), null, String(value));
});
test('price contract rejects nonpositive/nonfinite while preserving genuine zero/negative metrics', () => {
  const data = { a: { ...quote(1), change_pct: -1, amount_wan: 0 }, b: quote(0), c: quote(-1), d: quote(NaN), e: quote(Infinity) };
  assert.deepEqual(Object.keys(validQuoteRows(data, Object.keys(data))), ['a']);
  assert.equal(validQuoteRows(data, ['a']).a.amount_wan, 0);
  assert.equal(validQuoteRows(data, ['a']).a.change_pct, -1);
});
test('summary is earliest source instant, unknown/future invalidates it; missing is separate coverage', () => {
  const now = Date.parse('2026-10-12T02:00:00Z');
  const rows = { a: quote(10,'2026-10-12T09:59:59+08:00'), b: quote(20,'2026-10-09T15:00:00+08:00') };
  let states = quoteSnapshotStates(rows, ['a','b','missing'], ['b'], now);
  assert.equal(quoteSnapshotTime(states), Date.parse(rows.b.data_time!));
  assert.equal(states.missing.available, false);
  assert.match(quoteSnapshotLabel(states.b), /旧快照.*刷新失败.*2026.*北京时间/);
  states = quoteSnapshotStates({...rows, b: quote(20)}, ['a','b'], [], now);
  assert.equal(quoteSnapshotTime(states), null); assert.match(quoteSnapshotLabel(states.b), /行情时间未知/);
  states = quoteSnapshotStates({a: quote(10,'2026-10-13T00:00:00Z')}, ['a'], [], now);
  assert.equal(quoteSnapshotTime(states), null); assert.match(quoteSnapshotLabel(states.a), /晚于本机时钟/);
  assert.equal(quoteSnapshotTime({}), null);
});
