import assert from "node:assert/strict";
import test from "node:test";

const requests: Array<{ url: string; method: string; body: string | null }> = [];
let responseBody: unknown = { data: [] };

Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined,
  },
});

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  requests.push({
    url,
    method: (init?.method || "GET").toUpperCase(),
    body: typeof init?.body === "string" ? init.body : null,
  });
  return new Response(JSON.stringify(responseBody), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}) as typeof fetch;

const { api } = await import("../src/lib/api.ts");

test("Review Due Worklist uses a server-owned read-only endpoint", async () => {
  requests.length = 0;
  responseBody = { data: { evaluation_as_of: "2026-09-01T00:00:00.000000Z" } };
  await api.getFormalDecisionReviewWorklist();
  const request = requests.at(-1);
  assert.ok(request);
  assert.equal(request.url, "/api/formal-decision-review-worklist");
  assert.equal(request.method, "GET");
  assert.equal(request.body, null);
});

test("Formal Outcome list is separate and carries only evaluation boundary query", async () => {
  requests.length = 0;
  responseBody = { data: [] };
  await api.listFormalDecisionOutcomes({
    evaluation_as_of: "2026-09-01T00:00:00.000000Z",
    limit: 50,
    offset: 0,
  });
  const request = requests.at(-1);
  assert.ok(request);
  const url = new URL(request.url, "http://localhost");
  assert.equal(url.pathname, "/api/formal-decision-outcomes");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    evaluation_as_of: "2026-09-01T00:00:00.000000Z",
    limit: "50",
    offset: "0",
  });
  assert.equal(request.method, "GET");
  assert.equal(request.body, null);
});

test("Formal Outcome detail scopes identity to decision_id path", async () => {
  requests.length = 0;
  responseBody = { data: { decision_id: "decision_abc" } };
  await api.getFormalDecisionOutcome(
    "decision/abc",
    "2026-09-01T00:00:00.000000Z",
  );
  const request = requests.at(-1);
  assert.ok(request);
  assert.equal(
    request.url,
    "/api/formal-decisions/decision%2Fabc/outcome?evaluation_as_of=2026-09-01T00%3A00%3A00.000000Z",
  );
  assert.equal(request.body, null);
});
