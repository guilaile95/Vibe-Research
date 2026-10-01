import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { APP_ORIGIN, CSP, isAppURL, createProtocolHandler } from '../src/protocol.mjs';

test('only exact trusted custom origin is navigable', () => {
  for (const value of ['app://research/', 'app://research/portfolio?q=1']) assert.equal(isAppURL(value), true);
  for (const value of ['http://research/', 'app://research.evil/', 'app://user@research/', 'app://research:99/', 'javascript:alert(1)', 'file:///etc/passwd']) assert.equal(isAppURL(value), false);
});
test('protocol serves SPA and assets with strict CSP, rejects traversal/missing assets/mutations', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'vibe-protocol-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await fs.writeFile(path.join(root, 'index.html'), '<div>fixture</div>');
  await fs.writeFile(path.join(root, 'main.js'), 'export const fixture=true');
  const handler = createProtocolHandler({ frontend: root, backendPort: 123, token: 'secret' });
  for (const route of ['/', '/portfolio', '/settings']) {
    const response = await handler(new Request(`${APP_ORIGIN}${route}`));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('content-security-policy'), CSP);
    assert.match(await response.text(), /fixture/);
  }
  assert.equal((await handler(new Request(`${APP_ORIGIN}/main.js`))).headers.get('content-type'), 'text/javascript; charset=utf-8');
  assert.equal((await handler(new Request(`${APP_ORIGIN}/missing.js`))).status, 404);
  assert.equal((await handler(new Request(`${APP_ORIGIN}/x%2f..%2foutside.txt`))).status, 403);
  assert.equal((await handler(new Request(`${APP_ORIGIN}/x%5cy`))).status, 403);
  assert.equal((await handler(new Request(`${APP_ORIGIN}/`, { method: 'POST' }))).status, 405);
  assert.equal((await handler(new Request('app://evil/'))).status, 403);
});
test('API bridge fixes target, injects secret outside renderer, streams and strips headers', async () => {
  let outgoing;
  const handler = createProtocolHandler({ frontend: '/unused', backendPort: 3456, token: 'session-secret',
    fetchImpl: async (url, options) => {
      outgoing = { url, options };
      return new Response('data: fixture\n\n', { headers: { 'Content-Type': 'text/event-stream', 'Set-Cookie': 'secret=x', Location: 'https://evil/' } });
    } });
  const response = await handler(new Request(`${APP_ORIGIN}/api/chat?stream=1`, { method: 'POST', body: '{}', headers: {
    authorization: 'malicious', origin: 'https://evil/', cookie: 'x=y', 'content-type': 'application/json', 'x-forwarded-host': 'evil',
  } }));
  assert.equal(outgoing.url, 'http://127.0.0.1:3456/api/chat?stream=1');
  assert.equal(outgoing.options.headers.get('authorization'), 'Bearer session-secret');
  assert.equal(outgoing.options.headers.get('origin'), null);
  assert.equal(outgoing.options.headers.get('cookie'), null);
  assert.equal(outgoing.options.headers.get('x-forwarded-host'), null);
  assert.equal(outgoing.options.redirect, 'error');
  assert.equal(outgoing.options.duplex, 'half');
  assert.equal(response.headers.get('set-cookie'), null);
  assert.equal(response.headers.get('location'), null);
  assert.equal(await response.text(), 'data: fixture\n\n');
});
test('backend failure is sanitized', async () => {
  const handler = createProtocolHandler({ frontend: '/unused', backendPort: 1, token: 'secret', fetchImpl: async () => { throw new Error('private path and token'); } });
  const response = await handler(new Request(`${APP_ORIGIN}/api/runtime-info`));
  assert.equal(response.status, 502);
  assert.equal(await response.text(), 'Desktop request unavailable');
});

test('API stream is incremental and downstream cancellation reaches upstream', async () => {
  let cancelled = false;
  let upstreamController;
  let outgoingSignal;
  const controller = new AbortController();
  const handler = createProtocolHandler({ frontend: '/unused', backendPort: 1, token: 'secret',
    fetchImpl: async (_url, options) => {
      outgoingSignal = options.signal;
      return new Response(new ReadableStream({
        start(c) { upstreamController = c; c.enqueue(new TextEncoder().encode('first\n')); },
        cancel() { cancelled = true; },
      }));
    } });
  const response = await handler(new Request(`${APP_ORIGIN}/api/chat`, { signal: controller.signal }));
  const reader = response.body.getReader();
  assert.equal(new TextDecoder().decode((await reader.read()).value), 'first\n');
  upstreamController.enqueue(new TextEncoder().encode('second\n'));
  assert.equal(new TextDecoder().decode((await reader.read()).value), 'second\n');
  controller.abort();
  assert.equal(outgoingSignal.aborted, true);
  await reader.cancel();
  assert.equal(cancelled, true);
});
