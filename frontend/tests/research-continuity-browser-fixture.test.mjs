import test from 'node:test';
import assert from 'node:assert/strict';
import { continuity, readOnlyReply } from './e2e/research-continuity.fixture.mjs';
test('continuity DOM fixture retains actual backend overflow and conflict ordering', () => {
  const data = continuity('B');
  assert.equal(data.changes.items.length, 13);
  assert.equal(data.changes.items[11].change_type, 'CHANGED');
  assert.equal(data.changes.items[12].change_type, 'SOURCE_CONFLICT');
  assert.equal(data.decision_calendar.source, 'SYNTHETIC_B');
  assert.deepEqual(Object.values(data.writes), [0, 0, 0, 0]);
});
test('synthetic continuity transport only admits explicit read-only endpoints', () => {
  for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) assert.equal(readOnlyReply(method, '/api/campaigns/A/research-continuity'), null);
  assert.equal(readOnlyReply('GET', '/api/unknown'), null);
  assert.equal(readOnlyReply('GET', '/api/campaigns/A/research-continuity', 'A').json.data.campaign_id, 'A');
  assert.equal(readOnlyReply('GET', '/api/campaigns/B/research-continuity', 'B', true).status, 503);
});
