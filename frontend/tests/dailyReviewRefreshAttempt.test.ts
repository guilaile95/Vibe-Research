import assert from 'node:assert/strict';
import test from 'node:test';
import { parseRefreshAttempt, refreshAttemptLines } from '../src/lib/dailyReviewRefreshAttempt.ts';
const failed = { state: 'failed', started_at: '2026-10-31 14:00:00', finished_at: '2026-10-31 14:03:30', reason_code: 'SOURCE_TIMEOUT', failed_sources: ['emotion'], pending_sources: ['breadth'] };
test('latest attempt exposes safe reason, component and timing separately from success', () => {
  const lines = refreshAttemptLines(failed).join('\n');
  assert.match(lines, /最近刷新尝试：失败/);
  assert.match(lines, /开始：2026-10-31 14:00:00.*结束：2026-10-31 14:03:30/);
  assert.match(lines, /SOURCE_TIMEOUT/);
  assert.match(lines, /失败组件：短线情绪/);
  assert.match(lines, /未完成组件：市场广度/);
  assert.doesNotMatch(lines, /最近成功/);
});
test('legacy absent attempts stay absent; unknown raw provider details never render', () => {
  assert.deepEqual(refreshAttemptLines(undefined), []);
  assert.equal(parseRefreshAttempt({ ...failed, started_at: 'https://secret' }), null);
  const text = refreshAttemptLines({ ...failed, reason_code: 'https://secret', failed_sources: ['https://secret', 'indices', 'indices'], pending_sources: ['Bearer secret'] }).join('\n');
  assert.doesNotMatch(text, /secret|Bearer|https/);
  assert.match(text, /失败组件：大盘指数/);
});
test('running and success are distinct; empty component lists do not invent failure', () => {
  for (const [state, label] of [['running', '进行中'], ['succeeded', '成功']]) {
    const lines = refreshAttemptLines({ ...failed, state, reason_code: null, failed_sources: [], pending_sources: [], finished_at: null });
    assert.equal(lines.length, 1);
    assert.match(lines[0], new RegExp(`最近刷新尝试：${label}`));
  }
});

test('known stages render safely while absent or unrecognized stages remain compatible', () => {
  assert.match(refreshAttemptLines({...failed, stage:'quality'}).join('\n'), /阶段：质量校验/);
  assert.doesNotMatch(refreshAttemptLines({...failed, stage:'https:\/\/secret'}).join('\n'), /secret|阶段/);
});

test('safe Push2 cause labels distinguish cooldown and exhausted budget without encouraging retries', () => {
  const text = refreshAttemptLines({ ...failed, stage: 'collection', reason_code: 'SOURCE_COOLDOWN', failed_sources: ['breadth', 'emotion'], pending_sources: [], source_errors: { breadth: 'SOURCE_COOLDOWN', emotion: 'SOURCE_BUDGET_EXHAUSTED' } }).join('\n');
  assert.match(text, /原因：数据源冷却保护中；不要重复刷新（SOURCE_COOLDOWN）/);
  assert.match(text, /市场广度：数据源冷却保护中；不要重复刷新/);
  assert.match(text, /短线情绪：数据源请求预算已用尽；不要重复刷新/);
});
test('all approved source errors are allowed but unknown sources, raw errors and nonfailed components are dropped', () => {
  for (const code of ['SOURCE_COOLDOWN', 'SOURCE_BUDGET_EXHAUSTED', 'SOURCE_READ_ONLY', 'SOURCE_SAFETY_UNAVAILABLE', 'SOURCE_REFUSED', 'SOURCE_BLOCKED']) {
    assert.equal(parseRefreshAttempt({ ...failed, reason_code: code, source_errors: { emotion: code } })?.source_errors?.emotion, code);
  }
  const malicious = {...failed, source_errors:{ emotion:'https://secret?token=key', breadth:'SOURCE_COOLDOWN', 'Bearer secret':'SOURCE_BLOCKED' }};
  assert.equal(parseRefreshAttempt(malicious)?.source_errors, undefined);
  assert.doesNotMatch(refreshAttemptLines(malicious).join('\n'), /secret|Bearer|https|冷却/);
  assert.equal(parseRefreshAttempt(failed)?.source_errors, undefined);
});
