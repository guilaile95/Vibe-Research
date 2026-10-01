import test from 'node:test';
import assert from 'node:assert/strict';
import { electronMainPID } from './process-identity.mjs';
test('Windows shell wrapper PID is never substituted for Electron main PID', async () => {
  const application = { process: () => ({ pid: 11 }), evaluate: async () => 42 };
  assert.equal(await electronMainPID(application), 42);
});
test('invalid Electron PID fails closed without a shell-PID fallback', async () => {
  for (const pid of [undefined, null, 0, -1, '42']) {
    await assert.rejects(electronMainPID({ process: () => ({ pid: 11 }), evaluate: async () => pid }), /valid main-process PID/);
  }
});
