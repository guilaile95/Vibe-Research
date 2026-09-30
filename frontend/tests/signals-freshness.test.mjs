import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/pages/Signals.tsx', import.meta.url), 'utf8');
test('GPU UI distinguishes sample age from failed retrieval and source collection', () => {
  assert.ok(source.includes('fetchError ? "本轮抓取失败" : "查询采样已过期"'));
  assert.ok(source.includes('查询采样）'));
  assert.ok(source.includes('响应生成于'));
  assert.ok(source.includes('上游采集时点、健康和完整性未验证'));
  assert.ok(source.includes('历史/未验证卡数：'));
  assert.ok(!source.includes('这是市场状态，不是数据故障。'));
});
