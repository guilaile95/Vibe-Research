import assert from 'node:assert/strict';
import test from 'node:test';
import { checkCredentialGeneration, modelRequestWireBody } from '../src/lib/api.ts';
import { installCredentialFixture } from './credentialTransportFixture.mjs';
import { credentialStatus, storedCredential, routeCredentialStatus } from './e2e/credential-generation.fixture.mjs';
import { ancillaryReply, syntheticLlm, syntheticStoredLlm } from './e2e/final-families.fixture.mjs';
import { createExtendedPageFixture, syntheticLlm as researchLlm } from './e2e/extended-page.fixture.mjs';
import { createComparisonFixture, comparisonLlm } from './e2e/company-comparison.fixture.mjs';

test('saved browser fixture obeys actual generation guard and preserves strict wire model', async t => {
  const stored = storedCredential(syntheticLlm);
  installCredentialFixture(t, stored);
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/ai/credential-status'); assert.equal(init?.method, 'GET');
    return new Response(JSON.stringify(credentialStatus(syntheticLlm)));
  };
  await checkCredentialGeneration('/debate', { llm: stored });
  await assert.rejects(checkCredentialGeneration('/debate', { llm: syntheticLlm }), /AI 配置已变化/);
  await assert.rejects(checkCredentialGeneration('/debate', { llm: { ...stored, revision: '2' } }), /AI 配置已变化/);
  assert.deepEqual(modelRequestWireBody({ llm: stored }), { llm: stored });
  assert.deepEqual(syntheticStoredLlm, stored);
  assert.equal('apiKey' in credentialStatus(researchLlm), false);
});

test('standalone browser status route accepts only exact read-only preflight', async () => {
  let handle;
  await routeCredentialStatus({ route: async (pattern, callback) => {
    assert.equal(pattern, '**/api/ai/credential-status'); handle = callback;
  } }, syntheticLlm);
  for (const [method, search, body] of [['GET', '', null], ['POST', '', null], ['GET', '?x=1', null], ['GET', '', '{}']]) {
    const route = { request: () => ({ method: () => method, url: () => 'http://fixture/api/ai/credential-status' + search, postData: () => body }), fulfill: async response => response };
    if (method === 'GET' && !search && body === null) assert.deepEqual((await handle(route)).json, credentialStatus(syntheticLlm));
    else assert.throws(() => handle(route), /Unexpected credential preflight/);
  }
});

test('strict full-page fixtures expose matching generation without widening their write contracts', () => {
  assert.deepEqual(ancillaryReply('GET', '/api/ai/credential-status'), credentialStatus(syntheticLlm));
  assert.equal(ancillaryReply('POST', '/api/ai/credential-status'), null);
  assert.equal(ancillaryReply('GET', '/api/ai/credential-status', '?x=1'), null);
  for (const [create, model] of [[createExtendedPageFixture, researchLlm], [createComparisonFixture, comparisonLlm]]) {
    const fixture = create('http://fixture');
    assert.deepEqual(fixture.handle('http://fixture/api/ai/credential-status').body, credentialStatus(model));
    for (const [url, method, body] of [['http://fixture/api/ai/credential-status', 'POST', undefined], ['http://fixture/api/ai/credential-status?x=1', 'GET', undefined], ['http://elsewhere/api/ai/credential-status', 'GET', undefined], ['http://fixture/api/ai/credential-status', 'GET', {}]]) {
      assert.equal(fixture.handle(url, method, body).kind, 'deny');
    }
  }
});
