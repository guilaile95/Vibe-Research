import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('./e2e/discovery-workspace.browser.mjs', import.meta.url), 'utf8');
const marker = 'await page.route("**/api/**", ';
const start = source.indexOf(marker) + marker.length;
const end = source.indexOf('\n  });\n\n  await page.goto', start);
assert.ok(start >= marker.length && end > start);
const handlerSource = source.slice(start, end) + '\n  }';
for (const [method, path, expected] of [
  ['GET', '/api/screener/condition-cards', 200],
  ['POST', '/api/screener/condition-cards', 404],
  ['GET', '/api/screener/condition-cards?unexpected=true', 404],
  ['GET', '/api/unregistered-source', 404],
]) test(`Discovery fixture preserves exact catalog boundary: ${method} ${path}`, async () => {
  const requests = [];
  const handler = vm.runInNewContext(`(${handlerSource})`, { URL, apiRequests: requests });
  let reply;
  await handler({ request: () => ({ url: () => `http://127.0.0.1:3000${path}`, method: () => method }), fulfill: async value => { reply = value; } });
  assert.equal(reply.status, expected);
  assert.equal(requests.length, 1);
  if (expected === 200) assert.deepEqual(JSON.parse(reply.body), { cards: [], runs: [] });
  else assert.match(JSON.parse(reply.body).detail, /^unmocked /);
});
