import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTradeCreateInput,
  buildTradeListQuery,
  validateTradeDraft,
  validateTradeListFilters,
  type TradeDraft,
  type TradeListFilters,
} from "../src/lib/tradeLedgerView.ts";

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
let nextResponses: MockResponse[] = [{ status: 200, body: { data: [] } }];

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

  const nextResponse = nextResponses.shift() || { status: 200, body: { data: [] } };

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

function setResponses(...responses: MockResponse[]) {
  requests.length = 0;
  nextResponses = [...responses];
}

function lastRequest(): RecordedRequest {
  const request = requests.at(-1);
  assert.ok(request, "expected a recorded request");
  return request;
}

test("首次加载成功与 URL 规范", async () => {
  const mockTrade = {
    trade_id: "trade-001",
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: "full",
    actual_price: 1700,
    actual_quantity: 100,
    gross_amount: 170000,
    net_cash_flow: -170000,
    fee: 5,
    other_cost: 0,
    created_at: "2026-07-29T10:00:00Z",
    voided_at: null,
  };
  setResponses({ status: 200, body: { data: [mockTrade] } });

  const res = await api.listTrades({ include_voided: false, limit: 10, offset: 0 });
  assert.equal(res.length, 1);
  assert.equal(res[0].trade_id, "trade-001");

  const req = lastRequest();
  const url = new URL(req.url, "http://localhost");
  assert.equal(url.searchParams.get("limit"), "10");
  assert.equal(url.searchParams.get("offset"), "0");
  assert.equal(url.searchParams.get("include_voided"), "false");
});

test("空列表与加载失败", async () => {
  setResponses({ status: 200, body: { data: [] } });
  const emptyRes = await api.listTrades();
  assert.equal(emptyRes.length, 0);

  setResponses({ status: 500, body: { detail: "Database query failed" } });
  await assert.rejects(
    () => api.listTrades(),
    (err: unknown) => err instanceof ApiError && err.status === 500 && err.message === "Database query failed",
  );
});

test("失败后重试", async () => {
  setResponses(
    { status: 500, body: { detail: "Temporary failure" } },
    { status: 200, body: { data: [{ trade_id: "trade-retry" }] } },
  );

  await assert.rejects(() => api.listTrades());
  const retried = await api.listTrades();
  assert.equal(retried[0].trade_id, "trade-retry");
  assert.equal(requests.length, 2);
});

test("筛选提交、重置与格式校验", () => {
  const invalidCodeErr = validateTradeListFilters({ code: "123" });
  assert.equal(invalidCodeErr, "股票代码筛选必须是 6 位数字");

  const invalidDateErr = validateTradeListFilters({
    date_from: "2026-08-01",
    date_to: "2026-07-01",
  });
  assert.equal(invalidDateErr, "开始日期不得晚于结束日期");

  const validFilters: TradeListFilters = {
    code: "600519",
    operation: "buy",
    execution_status: "full",
    date_from: "2026-07-01",
    date_to: "2026-07-29",
    include_voided: true,
  };
  assert.equal(validateTradeListFilters(validFilters), null);

  const query = buildTradeListQuery(validFilters, 10, 0);
  assert.deepEqual(query, {
    code: "600519",
    operation: "buy",
    execution_status: "full",
    date_from: "2026-07-01",
    date_to: "2026-07-29",
    include_voided: true,
    limit: 10,
    offset: 0,
  });

  const queryReset = buildTradeListQuery({}, 10, 0);
  assert.deepEqual(queryReset, { limit: 10, offset: 0 });
});

test("创建 full 交易规则", () => {
  const draft: TradeDraft = {
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: "full",
    planned_price: 1700,
    planned_quantity: 100,
    actual_price: 1700,
    actual_quantity: 100,
    executed_at: "2026-07-29T10:00:00",
    fee: 5,
    other_cost: 0,
  };
  assert.equal(validateTradeDraft(draft), null);

  const input = buildTradeCreateInput(draft);
  assert.equal(input.code, "600519");
  assert.equal(input.actual_price, 1700);
  assert.equal(input.actual_quantity, 100);
  assert.ok(input.executed_at?.includes("Z") || input.executed_at?.includes("T"));
});

test("创建 partial 交易规则", () => {
  const draft: TradeDraft = {
    code: "600519",
    name: "贵州茅台",
    operation: "add",
    execution_status: "partial",
    planned_quantity: 200,
    actual_price: 1680,
    actual_quantity: 100,
    executed_at: "2026-07-29T10:00:00",
    unexecuted_reason: "资金不足",
  };
  assert.equal(validateTradeDraft(draft), null);

  const invalidDraft: TradeDraft = {
    ...draft,
    actual_quantity: 250,
  };
  assert.equal(validateTradeDraft(invalidDraft), "部分执行状态下，实际数量必须小于计划数量");
});

test("创建 not_executed 交易规则及字段防护", () => {
  const draft: TradeDraft = {
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: "not_executed",
    unexecuted_reason: "尚未破位",
    actual_price: 1700,
    actual_quantity: 100,
    executed_at: "2026-07-29T10:00:00",
    fee: 10,
    other_cost: 5,
  };
  assert.equal(validateTradeDraft(draft), null);

  const input = buildTradeCreateInput(draft);
  assert.equal(input.unexecuted_reason, "尚未破位");
  assert.equal("actual_price" in input, false);
  assert.equal("actual_quantity" in input, false);
  assert.equal("executed_at" in input, false);
  assert.equal("fee" in input, false);
  assert.equal("other_cost" in input, false);
});

test("创建失败后保留输入 (API 异常冒泡)", async () => {
  setResponses({ status: 422, body: { detail: "Actual price too high" } });

  const input = buildTradeCreateInput({
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: "full",
    actual_price: 9999,
    actual_quantity: 10,
    executed_at: "2026-07-29T10:00:00Z",
  });

  await assert.rejects(
    () => api.createTrade(input),
    (err: unknown) => err instanceof ApiError && err.status === 422 && err.message === "Actual price too high",
  );
});

test("详情加载与建议快照结构", async () => {
  const mockDetail = {
    trade_id: "trade-detail-1",
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: "full",
    actual_price: 1700,
    actual_quantity: 100,
    gross_amount: 170000,
    total_cost: 5,
    net_cash_flow: -170005,
    fee: 5,
    other_cost: 0,
    advice_snapshot: {
      action: "add",
      execution_quantity: 100,
      price_conditions: ["< 1750"],
      execution_plan: ["分批买入"],
      risk_conditions: ["大盘回调"],
      invalidation_conditions: ["跌破 1600"],
      confidence: "high",
    },
    created_at: "2026-07-29T10:00:00Z",
  };
  setResponses({ status: 200, body: { data: mockDetail } });

  const detail = await api.getTrade("trade-detail-1");
  assert.equal(detail.trade_id, "trade-detail-1");
  assert.ok(detail.advice_snapshot);
  assert.equal(detail.advice_snapshot.action, "add");
  assert.equal(detail.advice_snapshot.confidence, "high");
});

test("作废成功与 409 冲突", async () => {
  setResponses({ status: 200, body: { data: { trade_id: "trade-1", voided_at: "2026-07-29T11:00:00Z" } } });
  const voided = await api.voidTrade("trade-1", "下错单");
  assert.equal(voided.trade_id, "trade-1");

  setResponses({ status: 409, body: { detail: "Trade already voided" } });
  await assert.rejects(
    () => api.voidTrade("trade-1", "重复作废"),
    (err: unknown) => err instanceof ApiError && err.status === 409 && err.message === "Trade already voided",
  );
});

test("上一页与下一页 pagination 偏移量推演", () => {
  let offset = 0;
  const limit = 10;

  // 第一页
  let query = buildTradeListQuery({}, limit, offset);
  assert.equal(query.offset, 0);

  // 下一页 -> offset 10
  offset += limit;
  query = buildTradeListQuery({}, limit, offset);
  assert.equal(query.offset, 10);

  // 上一页 -> offset 0
  offset -= limit;
  query = buildTradeListQuery({}, limit, offset);
  assert.equal(query.offset, 0);
});
