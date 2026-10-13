import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isEvidenceReadinessForDate } from '../src/lib/evidenceReadiness.ts';
const golden = JSON.parse(readFileSync(new URL('./fixtures/evidence-readiness-golden.json', import.meta.url), 'utf8'));
const day = '2026-07-31';
const clone = () => structuredClone(golden[day]);
test('accepts actual temporary-store API service goldens for exact dates', () => {
  for (const [date, value] of Object.entries(golden)) assert.equal(isEvidenceReadinessForDate(value, date), true, date);
  assert.equal(isEvidenceReadinessForDate(golden[day], '2026-07-30'), false);
});
for (const [name, mutate] of Object.entries({
  schema: x => x.schema_version = 'new', readOnly: x => x.read_only = false, ingestion: x => x.ingestion_enabled = true,
  extra: x => x.root = '/private', missingFeature: x => x.features.pop(), duplicateFeature: x => x.features[1] = x.features[0],
  unknownStatus: x => x.features[0].status = 'success', reasons: x => x.features[0].reason_codes = ['/private/key'],
  contradictoryReady: x => x.features[0].reason_codes = ['ARCHIVE_MISSING'], wrongDate: x => x.features[0].required_dates = ['2026-07-30'],
  duplicateDates: x => x.features[1].required_dates = [day, day], invalidDate: x => x.features[1].required_dates[0] = '2026-02-30',
  missingRequirement: x => x.features[0].requirements = '', metricType: x => x.journal.prior_metric_available.limit_up_count = 1,
  falseReady: x => x.journal.prior_metric_available = {limit_up_count: false, failed_board_rate: false},
  falseVerified: x => x.journal.verification_claim = 'VERIFIED', malformedStamp: x => x.generated_at = '2026-02-30T00:00:00Z',
  wrongSeal: x => x.journal.seals_at = '2026-08-03T07:00:00Z',
  fractionalSeal: x => x.journal.seals_at = '2026-08-03T01:15:00.000001Z', unknownWindow: x => x.journal.state = 'CAN_TRADE',
  calendarContradiction: x => x.journal.state = 'CALENDAR_UNKNOWN', unknownMetric: x => x.journal.prior_metric_available.foo = true,
  emptyLimitations: x => x.limitations = [],
  normalizedMidnight: x => x.generated_at = '2026-07-31T24:00:00Z',
  invalidMinute: x => x.generated_at = '2026-07-31T10:60:00Z',
  invalidSecond: x => x.generated_at = '2026-07-31T10:00:60Z',
  staleOpen: x => x.generated_at = '2026-08-03T01:15:00Z',
  prematureOpen: x => x.generated_at = '2026-07-31T06:59:59Z',
  falseSealed: x => x.journal.state = 'SEALED',
})) test(`rejects ${name}`, () => { const value = clone(); mutate(value); assert.equal(isEvidenceReadinessForDate(value, day), false); });
test('null, arrays and incomplete payloads fail closed', () => {
  for (const value of [null, [], {}, 1, 'ready', {trade_date:day}]) assert.equal(isEvidenceReadinessForDate(value,day),false);
});
