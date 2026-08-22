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
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
  },
});

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  requests.push({
    url,
    method: (init?.method || "GET").toUpperCase(),
    body: typeof init?.body === "string" ? init.body : null,
  });
  const body = nextResponse.contentType === "text/html"
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

test("listTrades sends strict filters and pagination", async () => {
  reset();
  await api.listTrades({
    code: "600519",
    operation: "buy",
    execution_status: "partial",
    date_from: "2026-07-01",
    date_to: "2026-07-29",
    include_voided: false,
    limit: 50,
    offset: 0,
  });

  const request = lastRequest();
  assert.equal(request.method, "GET");
  const url = new URL(request.url, "http://localhost");
  assert.equal(url.pathname, "/api/trades");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    code: "600519",
    operation: "buy",
    execution_status: "partial",
    date_from: "2026-07-01",
    date_to: "2026-07-29",
    include_voided: "false",
    limit: "50",
    offset: "0",
  });
});

test("getTrade encodes the trade id", async () => {
  reset({ status: 200, body: { data: { trade_id: "trade/1" } } });
  await api.getTrade("trade/1");
  assert.equal(lastRequest().url, "/api/trades/trade%2F1");
});

test("createTrade posts the provided body without adding advice_snapshot", async () => {
  reset({ status: 200, body: { data: { trade_id: "trade-1" } } });
  const body = {
    code: "600519",
    name: "贵州茅台",
    operation: "buy" as const,
    execution_status: "not_executed" as const,
    unexecuted_reason: "等待价格",
  };
  await api.createTrade(body);

  const request = lastRequest();
  assert.equal(request.method, "POST");
  assert.equal(request.url, "/api/trades");
  assert.deepEqual(JSON.parse(request.body || "{}"), body);
  assert.equal("advice_snapshot" in JSON.parse(request.body || "{}"), false);
});

test("voidTrade posts the reason", async () => {
  reset({ status: 200, body: { data: { trade_id: "trade-1" } } });
  await api.voidTrade("trade-1", "重复记录");
  const request = lastRequest();
  assert.equal(request.method, "POST");
  assert.equal(request.url, "/api/trades/trade-1/void");
  assert.deepEqual(JSON.parse(request.body || "{}"), { reason: "重复记录" });
});

test("TAR1 reads reconciliation and candidates from backend authority", async () => {
  reset({ status: 200, body: { data: { allocation_state: "UNALLOCATED", reconciliation_requirement: "REQUIRED" } } });
  await api.getTradeReconciliation("trade/1");
  assert.equal(lastRequest().url, "/api/trades/trade%2F1/reconciliation");

  reset({ status: 200, body: { data: {
    candidates: [],
    scan_state: "COMPLETE_EMPTY",
    reason_codes: ["NO_ELIGIBLE_CANDIDATE"],
  } } });
  const scan = await api.listTradeAttributionCandidates("trade/1");
  assert.equal(lastRequest().url, "/api/trades/trade%2F1/attribution-candidates");
  assert.equal(scan.scan_state, "COMPLETE_EMPTY");
  assert.deepEqual(scan.candidates, []);
});

test("TAR1 keeps invalid witness scans non-complete and machine-readable", async () => {
  reset({
    status: 200,
    body: {
      data: {
        candidates: [],
        scan_state: "INVALID_WITNESS",
        reason_codes: ["FROZEN_DECISION_WITNESS_INVALID"],
      },
    },
  });
  const scan = await api.listTradeAttributionCandidates("trade/1");
  assert.notEqual(scan.scan_state, "COMPLETE");
  assert.equal(scan.scan_state, "INVALID_WITNESS");
  assert.deepEqual(scan.candidates, []);
  assert.ok(scan.reason_codes.includes("FROZEN_DECISION_WITNESS_INVALID"));
});

test("TAR1 writes only decision_id or explicit confirm", async () => {
  reset({ status: 200, body: { data: { record: {}, idempotent: false } } });
  await api.attributeTrade("trade/1", "decision_1");
  assert.deepEqual(JSON.parse(lastRequest().body || "{}"), { decision_id: "decision_1" });
  reset({ status: 200, body: { data: { record: {}, idempotent: false } } });
  await api.markTradeUnplanned("trade/1");
  assert.deepEqual(JSON.parse(lastRequest().body || "{}"), { confirm: true });
});

test("trade API exposes backend detail for 404, 409 and 422", async () => {
  for (const status of [404, 409, 422]) {
    reset({ status, body: { detail: `trade error ${status}` } });
    await assert.rejects(
      () => api.getTrade("missing"),
      (error: unknown) => error instanceof ApiError
        && error.status === status
        && error.message === `trade error ${status}`,
    );
  }
});

test("trade API does not expose HTML error bodies", async () => {
  reset({ status: 500, body: "<html>internal path C:\\secret</html>", contentType: "text/html" });
  await assert.rejects(
    () => api.listTrades(),
    (error: unknown) => error instanceof ApiError
      && error.status === 500
      && error.message === "HTTP 500"
      && !error.message.includes("secret"),
  );
});
