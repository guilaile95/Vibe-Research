import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isThemeResearchForDate, themeNumber } from '../src/lib/themeResearch.ts';
import { themeReply, dayA, dayB, validThemeQuery } from './e2e/theme-research.fixture.mjs';

test('actual API synthetic golden validates; null and zero remain distinct', () => {
  for (const day of [dayA, dayB]) for (const mode of ['normal', 'partial', 'unconnected']) assert.equal(isThemeResearchForDate(themeReply(day, mode), day), true);
  assert.equal(isThemeResearchForDate(themeReply(dayA), dayB), false);
  assert.equal(themeNumber(0), '0'); assert.equal(themeNumber(null), '未知');
  assert.equal(themeNumber(NaN), '未知'); assert.equal(themeNumber(2, true), '2.00%');
});
test('nested date, duplicate themes, unsafe authority and nonfinite metrics fail closed', () => {
  for (const mutate of [v => v.projection.canonical_authority = true, v => v.projection.sessions.pop(),
    v => v.projection.days[0].date = dayA, v => v.projection.rotation[0].cells[0].count = NaN,
    v => v.projection.rotation.push(v.projection.rotation[0]), v => v.projection.lineage[0].series[0].date = dayA,
    v => v.projection.tree[0].continuation_rate = 2]) {
    const v = themeReply(dayA); mutate(v); assert.equal(isThemeResearchForDate(v, dayA), false);
  }
});
test('read-only exact query boundary and mounted current/history component', () => {
  assert.equal(validThemeQuery('GET', '/api/market/theme-research', `?trade_date=${dayA}`), true);
  assert.equal(validThemeQuery('GET', '/api/market/theme-research', `?trade_date=${dayA}&refresh=1`), false);
  const page = readFileSync(new URL('../src/pages/DailyReview.tsx', import.meta.url), 'utf8');
  assert.match(page, /ThemeResearchCard tradeDate=\{dr\?\.trade_date \?\? null\}/);
  assert.match(page, /ThemeResearchCard tradeDate=\{snap\.trade_date \?\? null\}/);
  const component = readFileSync(new URL('../src/components/dailyReview/ThemeResearchCard.tsx', import.meta.url), 'utf8');
  assert.match(component, /state\?\.date === tradeDate/); assert.match(component, /token !== generation.current/);
  assert.match(component, /controller.abort/); assert.doesNotMatch(component, /Date.now|new Date|localStorage|setInterval/);
});

test('malformed directly rendered provenance operands fail closed', () => {
  for (const mode of ['bad-source-date', 'bad-seal', 'bad-basis', 'bad-name']) assert.equal(isThemeResearchForDate(themeReply(dayA, mode), dayA), false);
  const impossible = themeReply(dayA); impossible.projection.sessions[0] = '2026-02-30';
  assert.equal(isThemeResearchForDate(impossible, dayA), false);
  const duplicate = themeReply(dayA); duplicate.projection.lineage.push(duplicate.projection.lineage[0]);
  assert.equal(isThemeResearchForDate(duplicate, dayA), false);
});

test('full DailyReview fixtures allow only exact-date read-only theme routes', async () => {
  const { createFixture, DAY } = await import('./e2e/next-day-verification.fixture.mjs');
  const { ancillaryReply, ANCILLARY_TRADE_DATE } = await import('./e2e/final-families.fixture.mjs');
  const origin = 'http://127.0.0.1:18761', path = '/api/market/theme-research';
  const f = createFixture(origin, { withSealQuality: true });
  const accepted = f.handle(`${origin}${path}?trade_date=${DAY}`);
  assert.equal(accepted.kind, 'json'); assert.equal(isThemeResearchForDate(accepted.body.data, DAY), true);
  assert.equal(accepted.body.data.projection, null); assert.equal(accepted.body.data.reason_codes[0], 'ARCHIVE_NOT_CONNECTED');
  assert.equal(isThemeResearchForDate(ancillaryReply('GET', path, `?trade_date=${ANCILLARY_TRADE_DATE}`).data, ANCILLARY_TRADE_DATE), true);
  assert.equal(createFixture(origin).handle(`${origin}${path}?trade_date=${DAY}`).kind, 'deny');
  for (const method of ['POST', 'PUT', 'DELETE']) {
    assert.equal(createFixture(origin, { withSealQuality: true }).handle(`${origin}${path}?trade_date=${DAY}`, method).kind, 'deny');
    assert.equal(ancillaryReply(method, path, `?trade_date=${ANCILLARY_TRADE_DATE}`), null);
  }
  for (const suffix of ['', '?trade_date=2026-07-30', `?trade_date=${DAY}&refresh=1`, `?trade_date=${DAY}&root=/tmp`, `?trade_date=${DAY}&trade_date=${DAY}`])
    assert.equal(createFixture(origin, { withSealQuality: true }).handle(origin+path+suffix).kind, 'deny');
  for (const suffix of ['', '?trade_date=2026-10-07', `?trade_date=${ANCILLARY_TRADE_DATE}&refresh=1`, `?trade_date=${ANCILLARY_TRADE_DATE}&root=/tmp`, `?trade_date=${ANCILLARY_TRADE_DATE}&trade_date=${ANCILLARY_TRADE_DATE}`])
    assert.equal(ancillaryReply('GET', path, suffix), null);
});

test('P2 sibling full-page fixture is also exact-date and read-only', async () => {
  const { createFixture, DAY } = await import('./e2e/next-day-verification.fixture.mjs');
  const { ancillaryReply, ANCILLARY_TRADE_DATE } = await import('./e2e/final-families.fixture.mjs');
  const origin = 'http://127.0.0.1:18761', path = '/api/market/shortline-research';
  const f = createFixture(origin, { withSealQuality: true });
  const result = f.handle(`${origin}${path}?trade_date=${DAY}`);
  assert.equal(result.kind, 'json'); assert.equal(result.body.data.schema_version, 'shortline-research.v1');
  assert.equal(result.body.data.trade_date, DAY); assert.equal(result.body.data.projection, null);
  assert.equal(ancillaryReply('GET', path, `?trade_date=${ANCILLARY_TRADE_DATE}`).data.trade_date, ANCILLARY_TRADE_DATE);
  for (const method of ['POST', 'PUT', 'DELETE']) {
    assert.equal(createFixture(origin, { withSealQuality: true }).handle(`${origin}${path}?trade_date=${DAY}`, method).kind, 'deny');
    assert.equal(ancillaryReply(method, path, `?trade_date=${ANCILLARY_TRADE_DATE}`), null);
  }
  for (const suffix of ['', '?trade_date=2026-07-30', `?trade_date=${DAY}&as_of=x`, `?trade_date=${DAY}&root=/tmp`, `?trade_date=${DAY}&trade_date=${DAY}`])
    assert.equal(createFixture(origin, { withSealQuality: true }).handle(origin+path+suffix).kind, 'deny');
  for (const suffix of ['', '?trade_date=2026-10-07', `?trade_date=${ANCILLARY_TRADE_DATE}&as_of=x`, `?trade_date=${ANCILLARY_TRADE_DATE}&root=/tmp`, `?trade_date=${ANCILLARY_TRADE_DATE}&trade_date=${ANCILLARY_TRADE_DATE}`])
    assert.equal(ancillaryReply('GET', path, suffix), null);
});
