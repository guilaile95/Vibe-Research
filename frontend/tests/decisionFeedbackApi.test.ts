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

test("listDecisionFeedbacks sends filters and query params correctly", async () => {
  reset();
  await api.listDecisionFeedbacks({
    code: "600519",
    adoption_status: "followed",
    outcome_status: "as_expected",
    date_from: "2026-07-01",
    date_to: "2026-07-29",
    include_voided: false,
    limit: 10,
    offset: 0,
  });

  const request = lastRequest();
  assert.equal(request.method, "GET");
  const url = new URL(request.url, "http://localhost");
  assert.equal(url.pathname, "/api/decision-feedback");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    code: "600519",
    adoption_status: "followed",
    outcome_status: "as_expected",
    date_from: "2026-07-01",
    date_to: "2026-07-29",
    include_voided: "false",
    limit: "10",
    offset: "0",
  });
});

test("getDecisionFeedback encodes feedback_id", async () => {
  reset({ status: 200, body: { data: { feedback_id: "fb_123" } } });
  await api.getDecisionFeedback("fb_123");
  assert.equal(lastRequest().url, "/api/decision-feedback/fb_123");
});

test("createDecisionFeedback posts payload correctly", async () => {
  reset({ status: 200, body: { data: { feedback_id: "fb_123" } } });
  const body = {
    code: "600519",
    advice_trade_date: "2026-07-29",
    advice_generated_at: "2026-07-29T08:00:00Z",
    adoption_status: "followed" as const,
    outcome_status: "as_expected" as const,
    note: "测试决策反馈",
  };
  await api.createDecisionFeedback(body);

  const request = lastRequest();
  assert.equal(request.method, "POST");
  assert.equal(request.url, "/api/decision-feedback");
  assert.deepEqual(JSON.parse(request.body || "{}"), body);
});

test("voidDecisionFeedback posts void reason", async () => {
  reset({ status: 200, body: { data: { feedback_id: "fb_123" } } });
  await api.voidDecisionFeedback("fb_123", "输入有误");

  const request = lastRequest();
  assert.equal(request.method, "POST");
  assert.equal(request.url, "/api/decision-feedback/fb_123/void");
  assert.deepEqual(JSON.parse(request.body || "{}"), { reason: "输入有误" });
});

test("decision feedback API handles error responses", async () => {
  for (const status of [404, 409, 422]) {
    reset({ status, body: { detail: `feedback error ${status}` } });
    await assert.rejects(
      () => api.getDecisionFeedback("missing"),
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === status &&
        error.message === `feedback error ${status}`,
    );
  }
});
