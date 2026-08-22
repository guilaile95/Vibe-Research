import assert from "node:assert/strict";
import test from "node:test";

const requests: Array<{ url: string; method: string; body: string | null }> = [];
let response: { status: number; body: unknown } = {
  status: 200,
  body: {
    status: "default",
    reason_code: null,
    data: {
      lot_size: 100,
      min_cash_reserve_pct: 0.1,
      max_single_stock_allocation_pct: 0.3,
      tie_breaker_order: "code_asc",
      allow_partial_execution: true,
    },
  },
};

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  requests.push({
    url,
    method: (init?.method || "GET").toUpperCase(),
    body: typeof init?.body === "string" ? init.body : null,
  });
  return new Response(JSON.stringify(response.body), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}) as typeof fetch;

const { api } = await import("../src/lib/api.ts");

function reset(body: unknown, status = 200) {
  requests.length = 0;
  response = { status, body };
}

test("getAccountExecutionPolicy preserves default envelope", async () => {
  reset({ status: "default", reason_code: null, data: { lot_size: 100 } });
  const result = await api.getAccountExecutionPolicy();
  assert.deepEqual(result, { status: "default", reason_code: null, data: { lot_size: 100 } });
  assert.equal(requests[0]?.url, "/api/account-execution-policy");
});

test("getAccountExecutionPolicy preserves corrupted envelope without default data", async () => {
  reset({
    status: "corrupted",
    reason_code: "ACCOUNT_EXECUTION_POLICY_CORRUPTED",
    data: null,
  });
  const result = await api.getAccountExecutionPolicy();
  assert.equal(result.status, "corrupted");
  assert.equal(result.reason_code, "ACCOUNT_EXECUTION_POLICY_CORRUPTED");
  assert.equal(result.data, null);
});

test("updateAccountExecutionPolicy sends policy and returns configured envelope", async () => {
  reset({
    status: "configured",
    reason_code: null,
    data: {
      lot_size: 200,
      min_cash_reserve_pct: 0.2,
      max_single_stock_allocation_pct: 0.3,
      tie_breaker_order: "code_asc",
      allow_partial_execution: true,
    },
  });
  const policy = {
    lot_size: 200,
    min_cash_reserve_pct: 0.2,
    max_single_stock_allocation_pct: 0.3,
    tie_breaker_order: "code_asc" as const,
    allow_partial_execution: true,
  };
  const result = await api.updateAccountExecutionPolicy(policy);
  assert.equal(requests[0]?.method, "PUT");
  assert.deepEqual(JSON.parse(requests[0]?.body || "{}"), policy);
  assert.equal(result.status, "configured");
  assert.equal(result.data?.lot_size, 200);
});
