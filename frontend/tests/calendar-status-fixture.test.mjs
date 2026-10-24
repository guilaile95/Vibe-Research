import test from 'node:test';
import assert from 'node:assert/strict';
import { readCalendarStatusReply } from './e2e/calendar-status.fixture.mjs';
import { readReply, readPaths } from './e2e/ai-settings-storage.fixture.mjs';

test('calendar startup fixture models bounded supported and expiring public metadata', () => {
  assert.ok(readPaths.includes('/api/calendar-status'));
  assert.deepEqual(readReply('GET', '/api/calendar-status'), readCalendarStatusReply('GET', '/api/calendar-status'));
  for (const status of ['SUPPORTED', 'EXPIRING']) {
    const { data } = readCalendarStatusReply('GET', '/api/calendar-status', '', status);
    assert.equal(data.status, status);
    assert.equal(data.future_dates_inferred, false);
    assert.equal(data.calendar_id, 'CN_A_SHARE');
    assert.equal(data.source_policy, 'SSE_SZSE_OFFICIAL_CONSENSUS');
    assert.equal(data.days_until_coverage_end, (Date.parse(data.supported_end) - Date.parse(data.as_of_date)) / 86400000);
    assert.equal(data.maintenance_required, status === 'EXPIRING');
    assert.equal(data.next_action, status === 'EXPIRING' ? 'VERIFY_SSE_SZSE_OFFICIAL_CALENDAR' : 'NONE');
    assert.equal(data.days_until_coverage_end <= 90, status === 'EXPIRING');
    data.future_dates_inferred = true;
    assert.equal(readCalendarStatusReply('GET', '/api/calendar-status', '', status).data.future_dates_inferred, false);
  }
});

test('calendar fixture rejects writes, query parameters, aliases and unrelated API requests', () => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']) {
    assert.equal(readCalendarStatusReply(method, '/api/calendar-status'), null);
    assert.equal(readReply(method, '/api/calendar-status'), null);
  }
  for (const path of ['/api/calendar-status/', '/api/calendar-status/refresh', '/api/trade-calendar', '/api/agent-runtime/status'])
    assert.equal(readCalendarStatusReply('GET', path), null);
  for (const search of ['?refresh=true', '?date=2027-01-01']) {
    assert.equal(readCalendarStatusReply('GET', '/api/calendar-status', search), null);
    assert.equal(readReply('GET', '/api/calendar-status', search), null);
  }
  assert.throws(() => readCalendarStatusReply('GET', '/api/calendar-status', '', 'GUESS'), /Unsupported synthetic/);
});
