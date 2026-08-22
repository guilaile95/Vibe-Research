import assert from "node:assert/strict";
import test from "node:test";

// P0-CS1 Campaign API 前端契约测试：
// - 创建 payload 只含 security_code + strategy（绝不提交 status/campaign_id/created_at）
// - transition payload 只含 expected_status + to_status
// - 后端 409 等错误如实抛出（绝不伪装成功）

type RecordedRequest = {
  url: string;
  method: string;
  body: string | null;
};

const requests: RecordedRequest[] = [];
let nextResponse: { status: number; body: unknown } = { status: 200, body: { data: [] } };

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
  return new Response(JSON.stringify(nextResponse.body), {
    status: nextResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}) as typeof fetch;

const {
  api,
  ApiError,
  CommittedDecisionReadError,
  DecisionChallengeReadError,
  parseCommittedDecisionRuntimeRead,
} = await import("../src/lib/api.ts");

const CHALLENGE_READ = {
  schema_version: "decision_challenge.v0.1",
  challenge: { challenge_id: "decision_challenge_" + "d".repeat(32) },
  decision_quality: "NOT_EVALUATED",
};

function reset(response: { status: number; body: unknown } = { status: 200, body: { data: [] } }) {
  requests.length = 0;
  nextResponse = response;
}

function lastRequest(): RecordedRequest {
  const request = requests.at(-1);
  assert.ok(request, "expected a recorded request");
  return request;
}

test("Decision Challenge read maps only 404 to ABSENT and preserves other failures", async () => {
  reset({ status: 200, body: { data: CHALLENGE_READ } });
  const found = await api.getDecisionChallengeForProposal("campaign_" + "a".repeat(32), "a".repeat(64));
  assert.equal(found?.challenge.challenge_id, CHALLENGE_READ.challenge.challenge_id);

  reset({ status: 404, body: { detail: "Decision Challenge 不存在" } });
  assert.equal(
    await api.getDecisionChallengeForProposal("campaign_" + "a".repeat(32), "a".repeat(64)),
    null,
  );

  for (const status of [422, 500]) {
    reset({ status, body: { detail: `failure-${status}` } });
    await assert.rejects(
      () => api.getDecisionChallengeForProposal("campaign_" + "a".repeat(32), "a".repeat(64)),
      (err: unknown) => err instanceof ApiError && err.status === status,
    );
  }

  globalThis.fetch = (async () => {
    throw new Error("simulated network failure");
  }) as typeof fetch;
  await assert.rejects(
    () => api.getDecisionChallengeForProposal("campaign_" + "a".repeat(32), "a".repeat(64)),
    (err: unknown) => err instanceof ApiError && err.status === 0,
  );
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requests.push({
      url,
      method: (init?.method || "GET").toUpperCase(),
      body: typeof init?.body === "string" ? init.body : null,
    });
    return new Response(JSON.stringify(nextResponse.body), {
      status: nextResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  reset({ status: 200, body: { data: { challenge: {} } } });
  await assert.rejects(
    () => api.getDecisionChallengeForProposal("campaign_" + "a".repeat(32), "a".repeat(64)),
    (err: unknown) => err instanceof DecisionChallengeReadError,
  );
});

const DRAFT_CAMPAIGN = {
  campaign_id: "campaign_" + "a".repeat(32),
  security_code: "600519",
  strategy: "SWING",
  status: "DRAFT",
  created_at: "2026-08-14T00:00:00.000000Z",
};

const COMMITTED_CAMPAIGN_ID = "campaign_" + "a".repeat(32);
const COMMITTED_DECISION_ID = "decision_" + "b".repeat(32);
const COMMITTED_AS_OF = "2026-08-16T00:00:00.000000Z";

function committedRuntimeFixture(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "decision_commit_runtime.v0.1",
    as_of: COMMITTED_AS_OF,
    committed: {
      snapshot_schema_version: "frozen-decision-ledger.v0.1",
      decision_id: COMMITTED_DECISION_ID,
      campaign_id: COMMITTED_CAMPAIGN_ID,
      security_code: "600519",
      strategy: "SWING",
      committed_at: COMMITTED_AS_OF,
      created_at: COMMITTED_AS_OF,
      thesis_id: "c".repeat(32),
      thesis_revision: 1,
      asset_view: {},
      trade_view: {},
      portfolio_view: {},
      next_best_action: "WAIT",
      action_envelope: {},
      maintain_conditions: [],
      upgrade_conditions: [],
      downgrade_conditions: [],
      invalidation_conditions: [],
      strategy_horizon: "2 至 4 周",
      review_by: "2026-08-30T00:00:00.000000Z",
      key_assumptions: [],
      event_invalidation_conditions: [],
      validity_status_at_commit: "CURRENT",
      risk_policy_version: "hard-risk.v0.1",
      opportunity_policy_version: "opportunity.v0.1",
      decision_policy_version: "decision.v0.1",
      behavior_model_version: "behavior.v0.1",
      data_quality: null,
      evidence_confidence: null,
      inference_confidence: null,
      decision_confidence: null,
      evidence_refs: [],
      risk_refs: [],
      source_refs: ["proposal:fingerprint"],
      snapshot_hash: "d".repeat(64),
      snapshot_json: "{}",
      user_confirmed: true,
    },
    formal_thesis: { evaluation: "EVALUATED", reason_codes: [] },
    critical_data: { critical_data_state: "UNKNOWN", critical_data_evaluation: "UNKNOWN" },
    formal_decision: {
      evaluation: "EVALUATED",
      reason_codes: [],
      decision_id: COMMITTED_DECISION_ID,
      committed_at: COMMITTED_AS_OF,
      authority_refs: ["frozen_decision_service"],
    },
    hard_risk: {
      schema_version: "hard_risk_runtime.v0.1",
      policy_version: "hard_risk_policy.v0.1",
      security_code: "600519",
      strategy: "SWING",
      campaign_id: COMMITTED_CAMPAIGN_ID,
      as_of: COMMITTED_AS_OF,
      hard_risk_state: "UNKNOWN",
      hard_risk_evaluation: "UNKNOWN",
      reason_codes: ["NOT_PROVEN"],
      authority_refs: [],
    },
    material_change: {
      state: "NOT_EVALUATED",
      evaluation: "NOT_EVALUATED",
      reason_codes: ["NO_PRIOR_DECISION_BOUNDARY"],
    },
    sell_engine: { evaluation: "NOT_EVALUATED" },
    decision_assurance: { evaluation: "NOT_EVALUATED" },
    ...overrides,
  };
}

test("Committed Decision durable readback validates the live identity and authority envelope", async () => {
  reset({ status: 200, body: { data: committedRuntimeFixture() } });
  const result = await api.getCommittedDecisionRuntime(COMMITTED_CAMPAIGN_ID, COMMITTED_DECISION_ID);
  assert.equal(result.committed.decision_id, COMMITTED_DECISION_ID);
  assert.equal(result.committed.campaign_id, COMMITTED_CAMPAIGN_ID);
  assert.equal(lastRequest().url, `/api/campaigns/${COMMITTED_CAMPAIGN_ID}/decision-proposal/committed/${COMMITTED_DECISION_ID}`);
});

test("Committed Decision malformed 200 and identity mismatches fail closed", () => {
  const cases: Array<[string, Record<string, unknown>]> = [
    ["missing committed decision_id", { committed: { ...committedRuntimeFixture().committed as Record<string, unknown>, decision_id: undefined } }],
    ["decision mismatch", { committed: { ...committedRuntimeFixture().committed as Record<string, unknown>, decision_id: "decision_" + "e".repeat(32) } }],
    ["campaign mismatch", { committed: { ...committedRuntimeFixture().committed as Record<string, unknown>, campaign_id: "campaign_" + "f".repeat(32) } }],
    ["missing formal_decision", { formal_decision: undefined }],
    ["missing formal_thesis", { formal_thesis: undefined }],
    ["missing hard_risk", { hard_risk: undefined }],
    ["missing material_change", { material_change: undefined }],
  ];
  for (const [label, override] of cases) {
    assert.throws(
      () => parseCommittedDecisionRuntimeRead({ ...committedRuntimeFixture(), ...override }, COMMITTED_CAMPAIGN_ID, COMMITTED_DECISION_ID),
      (err: unknown) => err instanceof CommittedDecisionReadError && err.message.includes("COMMITTED_DECISION_READ_ERROR"),
      label,
    );
  }
});

test("Committed Decision HTTP and network failures preserve ApiError", async () => {
  reset({ status: 500, body: { detail: "backend unavailable" } });
  await assert.rejects(
    () => api.getCommittedDecisionRuntime(COMMITTED_CAMPAIGN_ID, COMMITTED_DECISION_ID),
    (err: unknown) => err instanceof ApiError && err.status === 500,
  );
  globalThis.fetch = (async () => { throw new Error("simulated network failure"); }) as typeof fetch;
  await assert.rejects(
    () => api.getCommittedDecisionRuntime(COMMITTED_CAMPAIGN_ID, COMMITTED_DECISION_ID),
    (err: unknown) => err instanceof ApiError && err.status === 0,
  );
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requests.push({ url, method: (init?.method || "GET").toUpperCase(), body: typeof init?.body === "string" ? init.body : null });
    return new Response(JSON.stringify(nextResponse.body), { status: nextResponse.status, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
});

test("createCampaign POSTs to /api/campaigns with exact payload (security_code + strategy only)", async () => {
  reset({ status: 201, body: { data: DRAFT_CAMPAIGN } });
  const result = await api.createCampaign("600519", "SWING");
  const req = lastRequest();
  assert.equal(req.method, "POST");
  assert.equal(req.url, "/api/campaigns");
  const body = JSON.parse(req.body as string);
  assert.deepEqual(body, { security_code: "600519", strategy: "SWING" });
  // 绝不提交 status / campaign_id / created_at
  assert.equal(body.status, undefined);
  assert.equal(body.campaign_id, undefined);
  assert.equal(body.created_at, undefined);
  // 响应解包 data
  assert.equal(result.campaign_id, DRAFT_CAMPAIGN.campaign_id);
  assert.equal(result.status, "DRAFT");
});

test("createCampaign backend detail surfaced on 409 (no fake success)", async () => {
  reset({ status: 409, body: { detail: "Campaign 状态冲突" } });
  await assert.rejects(
    () => api.createCampaign("600519", "SWING"),
    (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal((err as ApiError).status, 409);
      assert.equal((err as ApiError).message, "Campaign 状态冲突");
      return true;
    },
  );
});

test("transitionCampaign POSTs exact payload expected_status + to_status", async () => {
  reset({
    status: 200,
    body: {
      data: {
        campaign: { ...DRAFT_CAMPAIGN, status: "RESEARCHING" },
        transition: {
          transition_id: "campaign_transition_" + "b".repeat(32),
          campaign_id: DRAFT_CAMPAIGN.campaign_id,
          from_status: "DRAFT",
          to_status: "RESEARCHING",
          transitioned_at: "2026-08-14T01:00:00.000000Z",
        },
      },
    },
  });
  const result = await api.transitionCampaign(DRAFT_CAMPAIGN.campaign_id, "DRAFT", "RESEARCHING");
  const req = lastRequest();
  assert.equal(req.method, "POST");
  assert.equal(req.url, `/api/campaigns/${DRAFT_CAMPAIGN.campaign_id}/transitions`);
  assert.deepEqual(JSON.parse(req.body as string), {
    expected_status: "DRAFT",
    to_status: "RESEARCHING",
  });
  assert.equal(result.campaign.status, "RESEARCHING");
  assert.equal(result.transition.from_status, "DRAFT");
});

test("transitionCampaign 409 conflict reflected honestly", async () => {
  reset({ status: 409, body: { detail: "Campaign 状态冲突" } });
  await assert.rejects(
    () => api.transitionCampaign(DRAFT_CAMPAIGN.campaign_id, "DRAFT", "ACTIVE"),
    (err: unknown) => err instanceof ApiError && (err as ApiError).status === 409,
  );
});

test("getCampaignNextActions GETs read-model and unwraps data", async () => {
  reset({
    status: 200,
    body: {
      data: {
        campaign_id: DRAFT_CAMPAIGN.campaign_id,
        security_code: "600519",
        strategy: "SWING",
        status: "DRAFT",
        next_actions: ["RESEARCHING", "REJECTED", "EXPIRED"],
      },
    },
  });
  const result = await api.getCampaignNextActions(DRAFT_CAMPAIGN.campaign_id);
  const req = lastRequest();
  assert.equal(req.method, "GET");
  assert.equal(req.url, `/api/campaigns/${DRAFT_CAMPAIGN.campaign_id}/next-actions`);
  assert.deepEqual(result.next_actions, ["RESEARCHING", "REJECTED", "EXPIRED"]);
  assert.equal(result.status, "DRAFT");
});

test("getDecisionInbox GETs /api/decision-inbox and unwraps data", async () => {
  reset({
    status: 200,
    body: {
      data: {
        schema_version: "decision_inbox_runtime.v0.1",
        as_of: "2026-08-14T04:00:00.000000Z",
        evaluation_status: "EVALUATED",
        canonical: true,
        reason_codes: [],
        holding_setup_items: [],
        campaign_items: [],
        total_holdings: 0,
        total_campaign_items: 0,
      },
    },
  });
  const result = await api.getDecisionInbox();
  const req = lastRequest();
  assert.equal(req.method, "GET");
  assert.equal(req.url, "/api/decision-inbox");
  assert.equal(result.canonical, true);
  assert.equal(result.total_holdings, 0);
});

test("listCampaigns builds query params and unwraps list", async () => {
  reset({ status: 200, body: { data: [DRAFT_CAMPAIGN] } });
  const result = await api.listCampaigns({ security_code: "600519", status: "DRAFT" });
  const req = lastRequest();
  assert.equal(req.method, "GET");
  assert.ok(req.url.startsWith("/api/campaigns?"));
  assert.ok(req.url.includes("security_code=600519"));
  assert.ok(req.url.includes("status=DRAFT"));
  assert.equal(result.length, 1);
  assert.equal(result[0].campaign_id, DRAFT_CAMPAIGN.campaign_id);
});
