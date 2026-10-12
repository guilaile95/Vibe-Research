import assert from 'node:assert/strict';
import test from 'node:test';
import { AgentRuntime } from '../src/runtime.mjs';

const VERSION = { status: 0, stdout: 'codex-cli 0.149.0\n' };
const CHATGPT = { status: 0, stderr: 'Logged in using ChatGPT' };
// Never construct the runtime or create an SDK session. All process results are
// supplied by this stub; no CLI, account data, login or configuration is accessed.
function fixture(login = CHATGPT, version = VERSION) {
  const calls = [];
  const runtime = Object.create(AgentRuntime.prototype);
  Object.assign(runtime, {
    paths: { codexHome: '/synthetic/codex-home' }, sourceEnv: { OPENAI_API_KEY: 'PRIVATE_SENTINEL' },
    binary: 'synthetic-never-executed', loginState: null,
    sessions: new Map(), codexFactory: () => { throw Error('SDK forbidden'); },
    probeProcess(binary, args, options) {
      calls.push({ binary, args, options });
      const result = args[0] === '--version' ? version : login;
      if (result instanceof Error) throw result;
      return result;
    },
  });
  return { runtime, calls };
}
const cases = [
  ['ChatGPT stderr', CHATGPT, 'chatgpt', 'ready', null],
  ['ChatGPT stdout', { status: 0, stdout: 'Logged in using ChatGPT\r\n' }, 'chatgpt', 'ready', null],
  ['API key', { status: 0, stderr: 'Logged in using an API key - PRIVATE_SENTINEL' }, 'api_key', 'not_authenticated', null],
  ['logout', { status: 1, stderr: 'Not logged in' }, 'logged_out', 'not_authenticated', null],
  ['empty exit zero', { status: 0 }, 'unknown', 'probe_failed', 'malformed_output'],
  ['malformed prose', { status: 0, stdout: 'Error: Logged in using ChatGPT' }, 'unknown', 'probe_failed', 'malformed_output'],
  ['prefix collision', { status: 0, stdout: 'Logged in using ChatGPTish' }, 'unknown', 'probe_failed', 'malformed_output'],
  ['conflicting auth', { status: 0, stdout: CHATGPT.stderr, stderr: 'Logged in using an API key' }, 'unknown', 'probe_failed', 'malformed_output'],
  ['conflicting logout', { status: 1, stdout: CHATGPT.stderr, stderr: 'Not logged in' }, 'unknown', 'probe_failed', 'nonzero_exit'],
  ['logout wrong exit', { status: 0, stderr: 'Not logged in' }, 'unknown', 'probe_failed', 'malformed_output'],
  ['read failure', { status: 1, stderr: 'PRIVATE_SENTINEL' }, 'unknown', 'probe_failed', 'nonzero_exit'],
  ['nonzero', { status: 2, stderr: CHATGPT.stderr }, 'unknown', 'probe_failed', 'nonzero_exit'],
  ['timeout', { status: null, signal: 'SIGKILL', error: { code: 'ETIMEDOUT' }, stderr: 'Not logged in' }, 'unknown', 'probe_failed', 'timeout'],
  ['ENOENT', { error: { code: 'ENOENT' } }, 'unknown', 'runtime_unavailable', 'not_found'],
  ['signal', { status: 0, signal: 'SIGTERM', stderr: CHATGPT.stderr }, 'unknown', 'probe_failed', 'process_error'],
  ['output limit', { error: { code: 'ENOBUFS' } }, 'unknown', 'probe_failed', 'process_error'],
  ['thrown failure', new Error('PRIVATE_SENTINEL'), 'unknown', 'probe_failed', 'process_error'],
];
for (const [name, processResult, kind, state, error] of cases) test(`login classification: ${name}`, async () => {
  const { runtime, calls } = fixture(processResult);
  const status = runtime.status();
  assert.equal(status.auth_kind, kind);
  assert.equal(status.status, state);
  assert.equal(status.probe_error, error);
  assert.equal(status.available, kind === 'chatgpt');
  assert.equal(status.authenticated, kind === 'chatgpt');
  assert.doesNotMatch(JSON.stringify(status), /PRIVATE_SENTINEL/);
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call.options.timeout, 8000);
    assert.equal(call.options.killSignal, 'SIGKILL');
    assert.equal(call.options.maxBuffer, 64 * 1024);
    assert.equal(call.options.env.CODEX_HOME, '/synthetic/codex-home');
    assert.equal(call.options.env.OPENAI_API_KEY, undefined);
  }
  if (kind !== 'chatgpt') {
    await assert.rejects(runtime.chat({ session: 'synthetic', message: 'hello' }), e => {
      assert.equal(e.status, kind === 'unknown' ? 503 : 401);
      assert.doesNotMatch(e.message, /PRIVATE_SENTINEL/);
      return true;
    });
    assert.equal(runtime.sessions.size, 0);
  }
});
for (const [name, version, error] of [
  ['missing', { error: { code: 'ENOENT' } }, 'not_found'],
  ['timeout', { error: { code: 'ETIMEDOUT' } }, 'timeout'],
  ['empty', { status: 0 }, 'malformed_output'],
  ['raw output', { status: 0, stdout: 'PRIVATE_SENTINEL' }, 'malformed_output'],
  ['nonzero', { status: 1, stdout: VERSION.stdout }, 'nonzero_exit'],
]) test(`version probe: ${name}`, () => {
  const { runtime, calls } = fixture(CHATGPT, version);
  const result = runtime.status();
  assert.equal(result.probe_error, error);
  assert.equal(result.auth_kind, 'unknown');
  assert.equal(result.installed, error !== 'not_found');
  assert.equal(result.available, false);
  assert.equal(calls.length, 1);
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE_SENTINEL/);
});
for (const state of ['pending', 'failed']) test(`login lifecycle remains ${state} only for explicit logout`, () => {
  const { runtime } = fixture({ status: 1, stderr: 'Not logged in' });
  runtime.loginState = state;
  assert.equal(runtime.status().status, `login_${state}`);
  runtime.probeProcess = (_binary, args) => args[0] === '--version' ? VERSION : { error: { code: 'ETIMEDOUT' } };
  assert.equal(runtime.status().status, 'probe_failed');
  assert.equal(runtime.loginState, state);
});

for (const [kind, code] of [['api_key', 401], ['logged_out', 401], ['unknown', 503]]) test(`known auth kind cannot bypass chat preflight: ${kind}`, async () => {
  const { runtime } = fixture();
  runtime.status = () => ({ installed: true, authenticated: true, available: true, status: 'ready', auth_kind: kind });
  await assert.rejects(runtime.chat({ session: 'synthetic', message: 'hello' }), e => e.status === code);
  assert.equal(runtime.sessions.size, 0);
});
test('unavailable status cannot start an SDK session', async () => {
  const { runtime } = fixture();
  runtime.status = () => ({ installed: true, authenticated: true, available: false, status: 'ready' });
  await assert.rejects(runtime.chat({ session: 'synthetic', message: 'hello' }), e => e.status === 503);
  assert.equal(runtime.sessions.size, 0);
});
