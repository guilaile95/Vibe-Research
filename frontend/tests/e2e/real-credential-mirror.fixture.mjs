import assert from "node:assert/strict";

// Use only against an isolated harness with VR_DATA_DIR set to its temporary directory.
// Exercise the production router/store CAS contract rather than inventing a revision.
export async function saveHarnessCredential(backendUrl, model) {
  const beforeResponse = await fetch(`${backendUrl}/api/ai/credential-status`);
  assert.equal(beforeResponse.status, 200);
  const before = await beforeResponse.json();
  assert.match(before.revision, /^(0|[1-9][0-9]{0,18})$/);
  const response = await fetch(`${backendUrl}/api/ai/credential`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...model, expectedRevision: before.revision }),
  });
  assert.equal(response.status, 200, "synthetic credential must save through the real router");
  const saved = await response.json();
  assert.equal(saved.configured, true);
  assert.notEqual(saved.revision, before.revision);
  const statusResponse = await fetch(`${backendUrl}/api/ai/credential-status`);
  assert.equal(statusResponse.status, 200);
  const status = await statusResponse.json();
  assert.equal(status.revision, saved.revision);
  assert.equal(status.configured, true);
  assert.equal("apiKey" in status, false);
  return { ...model, revision: saved.revision };
}
