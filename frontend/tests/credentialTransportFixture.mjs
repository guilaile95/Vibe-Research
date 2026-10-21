import assert from 'node:assert/strict';

// Synthetic stored authority for transport tests. Only the exact read-only
// credential preflight is handled here; original route/body mocks remain strict.
export function installCredentialFixture(t, config) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const value = JSON.stringify(config);
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => key === 'vr-llm' ? value : null,
  } });
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor);
    else delete globalThis.localStorage;
  });
}
export function withCredentialStatus(respond) {
  return async (url, init) => {
    if (String(url) === '/api/ai/credential-status') {
      assert.equal(init?.method, 'GET');
      assert.equal(init?.body, undefined);
      const stored = JSON.parse(globalThis.localStorage?.getItem('vr-llm') || 'null');
      assert.match(stored?.revision ?? '', /^(0|[1-9][0-9]{0,18})$/);
      return new Response(JSON.stringify({ configured: true, revision: stored.revision }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return respond(url, init);
  };
}
