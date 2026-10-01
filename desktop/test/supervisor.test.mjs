import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../src/supervisor.mjs', import.meta.url));
async function fixture(t, failBackend) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'vibe-supervisor-'));
  for (const dir of ['node', 'backend', 'agent-runtime/src', 'data']) await fs.mkdir(path.join(root, dir), { recursive: true });
  await fs.symlink(process.execPath, path.join(root, 'node/node'));
  const service = type => `import fs from 'node:fs'; fs.appendFileSync(process.env.FIXTURE_PIDS, process.pid+'\\n'); console.log(JSON.stringify({type:'listening',service:'${type}',port:12345})); setInterval(()=>{},1000);`;
  await fs.writeFile(path.join(root, 'agent-runtime/package.json'), '{"type":"module"}');
  await fs.writeFile(path.join(root, 'agent-runtime/src/server.mjs'), service('agent'));
  await fs.writeFile(path.join(root, 'backend/vibe-backend'), `#!${process.execPath}\n${failBackend ? 'process.exit(7)' : service('backend')}`, { mode: 0o755 });
  // Extensionless Node entry is ESM under this fixture package.
  await fs.writeFile(path.join(root, 'package.json'), '{"type":"module"}');
  const child = spawn(process.execPath, [script, root, path.join(root, 'data')], {
    env: { ...process.env, FIXTURE_PIDS: path.join(root, 'pids') }, stdio: ['pipe', 'pipe', 'pipe'],
  });
  t.after(async () => { child.stdin.end(); await fs.rm(root, { recursive: true, force: true }); });
  return { child, root };
}
async function exited(child) {
  return await Promise.race([
    new Promise(resolve => child.once('exit', resolve)),
    new Promise((_, reject) => setTimeout(() => reject(new Error('Supervisor failed to stop')), 10_000)),
  ]);
}
async function assertChildrenStopped(root) {
  const pids = (await fs.readFile(path.join(root, 'pids'), 'utf8')).trim().split('\n').map(Number);
  assert.ok(pids.length > 0);
  for (const pid of pids) assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
}

test('ownership pipe EOF stops both services', { skip: process.platform !== 'linux' }, async t => {
  const { child, root } = await fixture(t, false);
  await new Promise(resolve => child.stdout.on('data', chunk => { if (chunk.toString().includes('"ready"')) resolve(); }));
  const done = exited(child);
  child.stdin.end();
  assert.equal(await done, 0);
  await assertChildrenStopped(root);
});
test('partial startup failure cleans already-started agent', { skip: process.platform !== 'linux' }, async t => {
  const { child, root } = await fixture(t, true);
  assert.equal(await exited(child), 1);
  await assertChildrenStopped(root);
});
