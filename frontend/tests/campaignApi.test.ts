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

const { api, ApiError, DecisionChallengeReadError } = await import("../src/lib/api.ts");

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
