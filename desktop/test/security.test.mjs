import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { spawnOwned, stopOwned } from '../src/processes.mjs';

test('production shell keeps Chromium sandbox and has no privileged renderer API', () => {
  const main = fs.readFileSync(new URL('../src/main.mjs', import.meta.url), 'utf8');
  assert.match(main, /app.enableSandbox\(\)/);
  for (const setting of ['contextIsolation: true', 'nodeIntegration: false', 'sandbox: true', 'webSecurity: true', 'webviewTag: false']) assert.ok(main.includes(setting));
  assert.doesNotMatch(main, /no-sandbox|disable-web-security|nodeIntegration: true|ipcMain|preload:/);
  assert.match(main, /requestSingleInstanceLock/);
  assert.match(main, /supervisor.stdin.end\(\)/);
});
test('POSIX owned group cleanup reaps an active descendant, without touching other services', { skip: process.platform === 'win32' }, async t => {
  const child = spawnOwned(process.execPath, ['-e', `const {spawn}=require('child_process'); const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'}); console.log(c.pid); setInterval(()=>{},1000);`]);
  t.after(() => stopOwned(child));
  const descendant = await new Promise(resolve => child.stdout.once('data', data => resolve(Number(data.toString().trim()))));
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)']);
  t.after(() => unrelated.kill());
  await stopOwned(child);
  // Zombie entries can remain until the container init reaps them; they cannot run.
  const state = pid => { try { return fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(' ')[2]; } catch { return null; } };
  assert.ok([null, 'Z'].includes(state(descendant)));
  assert.ok(![null, 'Z'].includes(state(unrelated.pid)));
});
