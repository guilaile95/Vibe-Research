import test from 'node:test';
import assert from 'node:assert/strict';
import { createAgentServer } from '../src/server.mjs';

test('desktop sidecar requires ephemeral bearer for all routes and denies browser Origins', async t => {
  let calls = 0;
  const server = createAgentServer({ status: () => { calls++; return { available: true }; } }, 'fixture-secret');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  const url = `http://127.0.0.1:${server.address().port}`;
  for (const route of ['/health', '/status', '/login', '/chat', '/cancel']) {
    assert.equal((await fetch(url + route)).status, 401);
    assert.equal((await fetch(url + route, { headers: { Authorization: 'Bearer wrong' } })).status, 401);
  }
  assert.equal((await fetch(url + '/status', { headers: { Authorization: 'Bearer fixture-secret', Origin: 'http://evil.example' } })).status, 403);
  assert.equal(calls, 0);
  assert.equal((await fetch(url + '/status', { headers: { Authorization: 'Bearer fixture-secret' } })).status, 200);
  assert.equal(calls, 1);
});

test('desktop display session variables pass to login without exposing application secrets', async () => {
  const { engineEnv } = await import('../src/security.mjs');
  const env = engineEnv('/tmp/fixture-codex-home', { DISPLAY: ':1', WAYLAND_DISPLAY: 'wayland-0',
    XAUTHORITY: '/tmp/xauth-fixture', XDG_RUNTIME_DIR: '/tmp/runtime-fixture',
    DBUS_SESSION_BUS_ADDRESS: 'unix:path=/tmp/bus-fixture', VR_API_KEY: 'secret', VR_AGENT_RUNTIME_TOKEN: 'secret' });
  assert.equal(env.DISPLAY, ':1');
  assert.equal(env.WAYLAND_DISPLAY, 'wayland-0');
  assert.equal(env.XAUTHORITY, '/tmp/xauth-fixture');
  assert.equal(env.XDG_RUNTIME_DIR, '/tmp/runtime-fixture');
  assert.equal(env.DBUS_SESSION_BUS_ADDRESS, 'unix:path=/tmp/bus-fixture');
  assert.equal(env.VR_API_KEY, undefined);
  assert.equal(env.VR_AGENT_RUNTIME_TOKEN, undefined);
});
