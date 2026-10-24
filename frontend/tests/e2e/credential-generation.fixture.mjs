// Browser fixtures model a saved synthetic credential generation, not a bypass
// of the production preflight. Preserve revision as a server-side dispatch precondition.
export const syntheticRevision = '1';
export const storedCredential = model => ({ ...model, revision: syntheticRevision });
export function credentialStatus(model) {
  return { revision: syntheticRevision, configured: true, provider: model.provider,
    model: model.model, baseURL: model.baseURL || '', updated_at: '2026-10-20T00:00:00Z',
    scheduled_available: true, scheduled_credential_available: true, error: null };
}
export async function routeCredentialStatus(page, model) {
  await page.route('**/api/ai/credential-status', route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() !== 'GET' || url.search || request.postData() !== null) {
      throw new Error('Unexpected credential preflight method/query/body');
    }
    return route.fulfill({ json: credentialStatus(model) });
  });
}
