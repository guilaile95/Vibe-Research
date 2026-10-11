import assert from "node:assert/strict";

export async function mutateThesis(page, thesisId, method, pathname, button, revision) {
  const [response] = await Promise.all([
    page.waitForResponse(response => response.request().method() === method
      && new URL(response.url()).pathname === pathname, { timeout: 15000 }),
    button.click(),
  ]);
  assert.equal(response.status(), 200, `${method} ${pathname} must succeed`);
  const payload = await response.json();
  assert.equal(payload.data?.thesis?.id, thesisId);
  assert.equal(payload.data?.thesis?.current_revision, revision);
  await page.locator("p").filter({ hasText: new RegExp(`^v${revision}$`) })
    .waitFor({ state: "visible", timeout: 15000 });
  return payload.data;
}
