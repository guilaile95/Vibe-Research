import assert from "node:assert/strict";
import test from "node:test";

type RecordedRequest = {
  url: string;
  method: string;
  body: string | null;
};

type MockResponse = {
  status: number;
  body: unknown;
  contentType?: string;
};

const requests: RecordedRequest[] = [];
let nextResponse: MockResponse = { status: 200, body: { data: [] } };

const store: Record<string, string> = {};
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
  },
});

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  requests.push({
    url,
    method: (init?.method || "GET").toUpperCase(),
    body: typeof init?.body === "string" ? init.body : null,
  });
  const body =
    nextResponse.contentType === "text/html"
      ? String(nextResponse.body)
      : JSON.stringify(nextResponse.body);
  return new Response(body, {
    status: nextResponse.status,
    headers: { "Content-Type": nextResponse.contentType || "application/json" },
  });
}) as typeof fetch;

const { api, ApiError } = await import("../src/lib/api.ts");

function reset(response: MockResponse = { status: 200, body: { data: [] } }) {
  requests.length = 0;
  nextResponse = response;
}

function lastRequest(): RecordedRequest {
  const request = requests.at(-1);
  assert.ok(request, "expected a recorded request");
  return request;
}

test("listDecisionEvidence sends query params correctly", async () => {
  reset({ status: 200, body: { data: { items: [], total: 0 } } });
  await api.listDecisionEvidence({
    code: "600519",
    trade_date: "2026-07-29",
    quality_status: "valid",
    trace_status: "complete",
    page: 2,
    limit: 10,
  });

  const request = lastRequest();
  assert.equal(request.method, "GET");
  const url = new URL(request.url, "http://localhost");
  assert.equal(url.pathname, "/api/decision-evidence");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    code: "600519",
    trade_date: "2026-07-29",
    quality_status: "valid",
    trace_status: "complete",
    limit: "10",
    offset: "10",
  });
});

test("getDecisionEvidence calls endpoint with encoded runId", async () => {
  reset({
    status: 200,
    body: {
      data: {
        decision_run: { id: "dr_test_123", trade_date: "2026-07-29" },
        evidence_items: [],
        explanation_items: [],
      },
    },
  });

  const res = await api.getDecisionEvidence("dr_test_123");
  assert.equal(lastRequest().url, "/api/decision-evidence/dr_test_123");
  assert.equal(res.run?.id || res.decision_run?.id, "dr_test_123");
});

test("getDecisionEvidenceByAdvice constructs query parameters correctly", async () => {
  reset({
    status: 200,
    body: {
      data: {
        decision_run: { id: "dr_advice_1", trade_date: "2026-07-29" },
        evidence_items: [],
        explanation_items: [],
      },
    },
  });

  await api.getDecisionEvidenceByAdvice({
    trade_date: "2026-07-29",
    generated_at: "2026-07-29T10:00:00Z",
    code: "600519",
  });

  const request = lastRequest();
  const url = new URL(request.url, "http://localhost");
  assert.equal(url.pathname, "/api/decision-evidence/by-advice");
  assert.equal(url.searchParams.get("trade_date"), "2026-07-29");
  assert.equal(url.searchParams.get("generated_at"), "2026-07-29T10:00:00Z");
  assert.equal(url.searchParams.get("code"), "600519");
});

test("decision evidence API handles errors correctly", async () => {
  for (const status of [400, 404, 500]) {
    reset({ status, body: { detail: `Error ${status}` } });
    await assert.rejects(
      () => api.getDecisionEvidence("dr_missing"),
      (error: unknown) =>
        error instanceof ApiError && error.status === status && error.message === `Error ${status}`
    );
  }
});
