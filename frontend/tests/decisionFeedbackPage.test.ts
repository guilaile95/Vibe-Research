import assert from "node:assert/strict";
import test from "node:test";
import {
  adoptionStatusLabel,
  buildFeedbackCreateInput,
  buildFeedbackListQuery,
  outcomeStatusLabel,
  validateFeedbackDraft,
  validateFeedbackListFilters,
  type DecisionFeedbackDraft,
  type DecisionFeedbackListFilters,
} from "../src/lib/decisionFeedbackView.ts";

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

test("首次加载与 API 请求构造规范", async () => {
  const mockFeedback = {
    feedback_id: "fb-001",
    code: "600519",
    advice_trade_date: "2026-07-29",
    advice_generated_at: "2026-07-29T08:00:00Z",
    trade_id: null,
    adoption_status: "followed",
    outcome_status: "as_expected",
    note: "符合预期测试",
    created_at: "2026-07-29T08:30:00Z",
    voided_at: null,
    void_reason: null,
  };

  setResponses({ status: 200, body: { data: [mockFeedback] } });

  const query = buildFeedbackListQuery(
    { code: "600519", adoption_status: "followed", outcome_status: "as_expected" },
    10,
    0,
  );
  const result = await api.listDecisionFeedbacks(query);

  assert.equal(result.length, 1);
  assert.equal(result[0].feedback_id, "fb-001");

  const req = lastRequest();
  assert.equal(req.method, "GET");
  assert.ok(req.url.includes("/api/decision-feedback"));
  assert.ok(req.url.includes("code=600519"));
});

test("新建与作废决策反馈完整数据流", async () => {
  const draft: DecisionFeedbackDraft = {
    code: "600519",
    advice_trade_date: "2026-07-29",
    advice_generated_at: "2026-07-29T08:00:00Z",
    adoption_status: "followed",
    outcome_status: "better_than_expected",
    note: "超预期的利好表现",
  };

  assert.equal(validateFeedbackDraft(draft), null);
  const input = buildFeedbackCreateInput(draft);

  setResponses(
    {
      status: 200,
      body: {
        data: {
          feedback_id: "fb-002",
          ...input,
          trade_id: null,
          created_at: "2026-07-29T09:00:00Z",
          voided_at: null,
          void_reason: null,
        },
      },
    },
    {
      status: 200,
      body: {
        data: {
          feedback_id: "fb-002",
          ...input,
          trade_id: null,
          created_at: "2026-07-29T09:00:00Z",
          voided_at: "2026-07-29T09:05:00Z",
          void_reason: "误操作创建",
        },
      },
    },
  );

  const created = await api.createDecisionFeedback(input);
  assert.equal(created.feedback_id, "fb-002");
  assert.equal(created.adoption_status, "followed");

  const voided = await api.voidDecisionFeedback(created.feedback_id, "误操作创建");
  assert.equal(voided.feedback_id, "fb-002");
  assert.equal(voided.void_reason, "误操作创建");
  assert.ok(voided.voided_at != null);
});
