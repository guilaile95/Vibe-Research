import assert from "node:assert/strict";
import test from "node:test";
import {
  traceStatusLabel,
  qualityStatusLabel,
  scopeLabel,
  filterDecisionRuns,
} from "../src/lib/decisionEvidenceView.ts";
import type { DecisionRunRecord, DecisionEvidenceDetailResult } from "../src/lib/api/types.ts";

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
let nextResponses: MockResponse[] = [];

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

const { api } = await import("../src/lib/api.ts");

function setResponses(...responses: MockResponse[]) {
  requests.length = 0;
  nextResponses = [...responses];
}

function lastRequest(): RecordedRequest {
  const request = requests.at(-1);
  assert.ok(request, "expected a recorded request");
  return request;
}

test("Decision evidence page list request and detail workflow", async () => {
  const mockRun: DecisionRunRecord = {
    id: "dr_600519_2026-07-29",
    code: "600519",
    trade_date: "2026-07-29",
    generated_at: "2026-07-29T10:00:00Z",
    trace_status: "complete",
    quality_status: "valid",
    evidence_count: 5,
    missing_count: 0,
  };

  const mockDetail: DecisionEvidenceDetailResult = {
    run: mockRun,
    evidence_items: [
      {
        id: "ev_1",
        decision_run_id: "dr_600519_2026-07-29",
        scope: "stock",
        category: "财务指标",
        title: "毛利率维持高位",
        quality_status: "valid",
        observation_time: "2026-07-29T09:30:00Z",
      },
    ],
    explanations: [
      {
        id: "exp_1",
        decision_run_id: "dr_600519_2026-07-29",
        claim: "长线看好基本面",
        conclusion: "建议买入/持有",
        supporting_evidence_ids: ["ev_1"],
        confidence_score: 0.9,
      },
    ],
  };

  setResponses(
    { status: 200, body: { data: { items: [mockRun], total: 1 } } },
    { status: 200, body: { data: mockDetail } }
  );

  const listRes = await api.listDecisionEvidence({ code: "600519", page: 1, limit: 10 });
  assert.equal(listRes.items.length, 1);
  assert.equal((listRes.items[0] as DecisionRunRecord).code, "600519");

  const detailRes = await api.getDecisionEvidence("dr_600519_2026-07-29");
  assert.equal(detailRes.evidence_items.length, 1);
  assert.equal(detailRes.evidence_items[0].title, "毛利率维持高位");
  assert.equal(detailRes.explanations?.[0].claim, "长线看好基本面");
});

test("Decision evidence view filters and labels work in harmony", () => {
  const runs: DecisionRunRecord[] = [
    {
      id: "dr_1",
      code: "600519",
      trade_date: "2026-07-29",
      generated_at: "2026-07-29T10:00:00Z",
      trace_status: "complete",
      quality_status: "valid",
    },
    {
      id: "dr_2",
      code: "000001",
      trade_date: "2026-07-29",
      generated_at: "2026-07-29T10:00:00Z",
      trace_status: "partial",
      quality_status: "missing",
    },
  ];

  const filtered = filterDecisionRuns(runs, { quality_status: "missing" });
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].code, "000001");
  assert.equal(traceStatusLabel(filtered[0].trace_status), "部分追踪");
  assert.equal(qualityStatusLabel(filtered[0].quality_status), "关键缺失");
});
