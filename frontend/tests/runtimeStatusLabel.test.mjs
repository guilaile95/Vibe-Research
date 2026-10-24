import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Evaluate the exact JSX status-label expression. No Settings root/storage,
// credential fields, browser, network or model connection probe is executed.
const source = readFileSync(new URL('../src/pages/Settings.tsx', import.meta.url), 'utf8');
const expression = source.match(/Runtime：\{runtimeStatus\?\.runtime[^\n]+\n([\s\S]*?)\n\s*\}/)?.[1];
assert.ok(expression, 'Settings runtime label expression must remain testable');
const label = runtimeStatus => vm.runInNewContext(`(${expression})`, { runtimeStatus });
for (const [status, kind, expected] of [
  ['ready', 'chatgpt', '已登录 · 模型连通性未验证'],
  ['not_authenticated', 'api_key', '当前为 API key 登录，订阅接入需要 ChatGPT 登录'],
  ['not_authenticated', 'logged_out', '未连接'],
  ['probe_failed', 'unknown', '登录状态检测未完成，请重试（现有登录不会被清除）'],
  ['runtime_unavailable', 'unknown', 'Runtime 未启动'],
  ['login_pending', 'logged_out', '等待登录'],
  ['login_failed', 'logged_out', '登录未完成'],
]) test(`Settings runtime label: ${status}/${kind}`, () => {
  assert.equal(label({ status, auth_kind: kind }), expected);
});
test('legacy runtime payloads preserve display compatibility', () => {
  assert.equal(label({ status: 'ready' }), '已登录 · 模型连通性未验证');
  assert.equal(label({ status: 'not_authenticated' }), '未连接');
  assert.equal(label(null), 'Runtime 未启动');
});
