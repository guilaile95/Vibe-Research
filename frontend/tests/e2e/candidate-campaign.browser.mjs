import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(here, "../../dist");

function chromiumPath() {
  const roots = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    path.join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    path.join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  const candidates = [];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    if (base.endsWith(".exe") && existsSync(base)) candidates.push(base);
    let entries = [];
    try {
      entries = readdirSync(base);
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.startsWith("chromium")) continue;
      candidates.push(
        path.join(base, entry, "chrome-win64", "chrome.exe"),
        path.join(base, entry, "chrome-win", "chrome.exe"),
        path.join(base, entry, "chrome-linux", "chrome"),
      );
    }
  }
  return candidates.find((candidate) => existsSync(candidate));
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function startStaticServer(directory, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(directory, pathname);
    if (!existsSync(target) || path.extname(target) === "") target = path.join(directory, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

const ok = (data) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ data }) });
const unavailable = (detail = "candidate browser fixture: unavailable") => ({
  status: 503,
  contentType: "application/json",
  body: JSON.stringify({ detail }),
});

const valuation = {
  name: "贵州茅台",
  code: "600519",
  price: 1300,
  mcap_yi: 16000,
  pe_ttm: 25,
  pb: 8,
  eps_26e: null,
  eps_27e: null,
  pe_26e: null,
  cagr_pct: null,
  peg: null,
  digest_years: null,
  analyst_count: 0,
};

const financials = {
  period: "2026Q2",
  period_end: "2026-06-30",
  report_date: null,
  revenue: null,
  revenue_yoy: null,
  net_profit: null,
  net_profit_yoy: null,
  deduct_net_profit: null,
  deduct_net_profit_yoy: null,
  eps: null,
  bvps: null,
  roe: null,
  gross_margin: null,
  net_margin: null,
  op_cf_ps: null,
  current_ratio: null,
  quick_ratio: null,
  debt_to_equity_ratio: null,
  debt_ratio: null,
  revenue_amount: null,
  net_profit_amount: null,
  parent_holder_net_profit_amount: null,
  operating_cash_flow: null,
  capital_expenditure: null,
  free_cash_flow: null,
  assets_total: null,
  cash: null,
  accounts_receivable: null,
  total_debt: null,
  holder_equity_total: null,
  cash_conversion_ratio: null,
  free_cash_flow_margin: null,
  accrual_ratio: null,
  receivables_pressure: null,
  net_cash_ratio: null,
  history: [],
  data_quality: {
    status: "partial",
    source: "tonghuashun_via_akshare",
    fetch_mode: "snapshot",
    report_basis: "cumulative_report_period",
    point_in_time_supported: false,
    publication_date_known: false,
    missing_fields: [],
    warnings: [],
  },
};

const campaignsByStatus = {
  DRAFT: ["RESEARCHING", "REJECTED", "EXPIRED"],
  RESEARCHING: ["PRE-ENTRY", "REJECTED", "EXPIRED"],
  "PRE-ENTRY": ["REJECTED", "EXPIRED"],
};

const nativeIntelContext = {
  status: "normal",
  retrieved_at: "2026-08-27T10:00:00Z",
  authority_ref: "vibe:native_intel:v0.1",
  usage_boundary: "observation_only_not_an_investment_authority",
  window_hours: 168,
  security: { code: "600519", company_name: "贵州茅台" },
  mapping: {
    status: "MAPPED",
    term_count: 2,
    terms: [
      { term: "600519", term_kind: "security_code", source_ref: "user_query_exact" },
      { term: "白酒", term_kind: "industry", source_ref: "fixture" },
    ],
    errors: [],
  },
  observation: {
    items: [],
    item_count: 0,
    mention_count: 0,
    source_count: 0,
    first_seen_at: null,
    last_seen_at: null,
  },
  rank_history: { available: false, reason: "registry_sources_have_no_real_rank" },
};

const evidenceRecords = [{
  id: "evidence_financial",
  subject_type: "stock",
  subject_id: "600519",
  evidence_type: "financial_filing",
  claim: "2026H1 财务披露",
  source_title: "半年报",
  source_url: null,
  source_date: "2026-08-01",
  accessed_at: "2026-08-02T00:00:00Z",
  classification: "fact",
  confidence: "high",
  created_at: "2026-08-02T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
  deleted: 0,
  deleted_at: null,
}];

const CAMPAIGN_A = `campaign_${"c".repeat(32)}`;
const CAMPAIGN_B = `campaign_${"d".repeat(32)}`;
const CAMPAIGN_C = `campaign_${"e".repeat(32)}`;
const DECISION_A = `decision_${"f".repeat(32)}`;
const CHALLENGE_A = `decision_challenge_${"a".repeat(32)}`;
const FINGERPRINTS = {
  [CAMPAIGN_A]: "1".repeat(64),
  [CAMPAIGN_B]: "2".repeat(64),
  [CAMPAIGN_C]: "3".repeat(64),
};

const fixedCampaigns = [
  { campaign_id: CAMPAIGN_B, security_code: "000001", strategy: "SWING", status: "PRE-ENTRY", created_at: "2026-08-26T00:00:00.000Z" },
  { campaign_id: CAMPAIGN_C, security_code: "300750", strategy: "MEDIUM", status: "PRE-ENTRY", created_at: "2026-08-26T00:00:00.000Z" },
];

function thesisContext(campaign) {
  const thesisId = campaign.campaign_id.slice(-32);
  const horizon = campaign.strategy === "MEDIUM" ? { unit: "TRADING_DAY", min: 40, max: 120, anchor: "FREEZE_AT" } : { unit: "TRADING_DAY", min: 5, max: 30, anchor: "FREEZE_AT" };
  const binding = {
    campaign_id: campaign.campaign_id,
    thesis_id: thesisId,
    thesis_revision_at_bind: 1,
    campaign_strategy_at_bind: campaign.strategy,
    bound_at: "2026-08-25T00:00:00.000Z",
  };
  const thesis = {
    id: thesisId,
    subject_type: "stock",
    subject_id: campaign.security_code,
    market: "CN",
    title: `${campaign.security_code} Candidate Thesis`,
    summary: "fixture",
    core_claims: ["claim 1", "claim 2", "claim 3"],
    catalysts: ["catalyst"],
    risks: ["risk"],
    invalidation_conditions: ["invalidation"],
    status: "active",
    current_revision: 1,
    created_at: "2026-08-24T00:00:00.000Z",
    updated_at: "2026-08-25T00:00:00.000Z",
    formal_state: "frozen",
    formalization_started_at: "2026-08-24T00:00:00.000Z",
    confirmed_at: "2026-08-24T12:00:00.000Z",
    frozen_at: "2026-08-25T00:00:00.000Z",
    frozen_revision: 1,
    archived_at: null,
    strategy: campaign.strategy,
    expected_horizon: horizon,
    free_notes: null,
  };
  const snapshot = {
    thesis,
    evidence_links: [],
    formal_state: "frozen",
    formalization_started_at: thesis.formalization_started_at,
    confirmed_at: thesis.confirmed_at,
    frozen_at: thesis.frozen_at,
    frozen_revision: 1,
    archived_at: null,
    status: "active",
    current_revision: 1,
    updated_at: thesis.updated_at,
  };
  return {
    binding,
    aggregate: { thesis, evidence_links: [] },
    current: {
      campaign_id: campaign.campaign_id,
      thesis_id: thesisId,
      binding: {
        thesis_revision_at_bind: 1,
        campaign_strategy_at_bind: campaign.strategy,
        bound_at: binding.bound_at,
      },
      frozen_revision: 1,
      original_snapshot: snapshot,
      deltas: [],
      effective_state: "STABLE",
      ready: true,
      formal_status: "READY",
    },
  };
}

function capitalContextFor(scenario) {
  const base = {
    schema_version: "portfolio_capital_context.v0.1",
    position_sizing_status: "AVAILABLE",
    authority_refs: ["portfolio_capital_allocation:fixture"],
  };
  if (scenario === "C") return {
    ...base,
    position_sizing_status: "UNKNOWN",
    capital_availability: { state: "UNKNOWN", confirmed_cash: null, reason_codes: ["ACCOUNT_REALITY_UNKNOWN"] },
    portfolio_fit: { state: "UNKNOWN", existing_position_count: null, reason_codes: ["ACCOUNT_REALITY_UNKNOWN"] },
    replacement_review: { state: "UNKNOWN", reason_codes: ["ACCOUNT_REALITY_UNKNOWN"], candidates: [] },
  };
  if (scenario === "E") return {
    ...base,
    capital_availability: { state: "CONSTRAINED", confirmed_cash: 50000, reason_codes: ["CAPITAL_CONSTRAINED"] },
    portfolio_fit: { state: "CONSTRAINED", existing_position_count: 1, reason_codes: ["CAPITAL_CONSTRAINED"] },
    replacement_review: {
      state: "WORTH_REVIEW",
      reason_codes: ["INCUMBENT_THESIS_WEAKENED"],
      candidates: [{ security_code: "000001", campaign_id: `campaign_${"9".repeat(32)}`, strategy: "SWING", reason_codes: ["INCUMBENT_THESIS_WEAKENED"] }],
    },
  };
  if (scenario === "B" || scenario === "D") return {
    ...base,
    capital_availability: { state: "CONSTRAINED", confirmed_cash: 50000, reason_codes: ["CAPITAL_CONSTRAINED"] },
    portfolio_fit: { state: "CONSTRAINED", existing_position_count: 1, reason_codes: ["CAPITAL_CONSTRAINED"] },
    replacement_review: {
      state: "NOT_PROVEN",
      reason_codes: [scenario === "D" ? "REPLACEMENT_SUPERIORITY_NOT_PROVEN" : "CAPITAL_CONSTRAINED_NO_AUTOMATIC_REPLACEMENT"],
      candidates: [],
    },
  };
  return {
    ...base,
    capital_availability: { state: "AVAILABLE", confirmed_cash: 200000, reason_codes: [] },
    portfolio_fit: { state: "SUPPORTIVE", existing_position_count: 0, reason_codes: [] },
    replacement_review: { state: "NOT_REQUIRED", reason_codes: [], candidates: [] },
  };
}

function previewFor(campaign, body, capitalScenario = "A") {
  const isA = campaign.campaign_id === CAMPAIGN_A;
  const isB = campaign.campaign_id === CAMPAIGN_B;
  const scenario = isA ? capitalScenario : isB ? "C" : "E";
  const capitalContext = capitalContextFor(scenario);
  const capitalUnknown = capitalContext.capital_availability.state === "UNKNOWN";
  const replacementReview = capitalContext.replacement_review.state === "WORTH_REVIEW";
  const nextBestAction = isA
    ? capitalUnknown || replacementReview || scenario === "D" ? "WAIT" : "BUY SMALL"
    : isB ? "RESEARCH MORE" : "AVOID";
  const candidate = {
    valuation_status: isB ? "UNKNOWN" : "EVALUATED",
    position_state: isA ? "NOT_HELD" : "UNKNOWN",
    account_state: isB ? "UNAVAILABLE" : "AVAILABLE",
    account_canonical: isA,
    account_confidence: isB ? "UNKNOWN" : "MEDIUM",
    hard_risk_state: campaign.campaign_id === CAMPAIGN_C ? "CONFIRMED" : "CLEAR",
    critical_data_state: isB ? "UNAVAILABLE" : "USABLE",
    confidence: isB ? "UNKNOWN" : "MEDIUM",
    confidence_ceiling: isB ? "UNKNOWN" : "MEDIUM",
    evidence: {
      status: isB ? "INSUFFICIENT" : "SUFFICIENT",
      total_count: isB ? 0 : 3,
      supporting_count: isB ? 0 : 2,
      opposing_count: campaign.campaign_id === CAMPAIGN_C ? 1 : 0,
      supporting_fact_count: isB ? 0 : 2,
      opposing_high_count: campaign.campaign_id === CAMPAIGN_C ? 1 : 0,
      classification_counts: { fact: isB ? 0 : 2, inference: isB ? 0 : 1, unknown: 0 },
    },
    evidence_refs: isB ? [] : ["evidence:fixture"],
    risk_reward: isB ? null : { ratio: isA ? 2.2 : 3.0, gate: 2.0 },
    risk_cap: isB ? null : { status: "AVAILABLE_CANDIDATE", max_position_value: 10000 },
    reason_codes: isB ? ["CANDIDATE_VALUATION_UNKNOWN"] : campaign.campaign_id === CAMPAIGN_C ? ["HARD_RISK_CONFIRMED"] : ["BOUNDED_BUY"],
    analysis_metadata: { as_of: "2026-08-30T00:00:00.000Z" },
    risk_policy_version: "candidate-risk.v0.1",
    opportunity_policy_version: "candidate-opportunity.v0.1",
    decision_policy_version: "decision-proposal.v0.1",
  };
  return {
    schema_version: "decision_proposal.v0.1",
    proposal: {
      schema_version: "decision_proposal.v0.1",
      proposal_status: "UNCOMMITTED",
      constraint_evaluation: "EVALUATED",
      security_code: campaign.security_code,
      strategy: campaign.strategy,
      campaign_id: campaign.campaign_id,
      thesis_id: campaign.campaign_id.slice(-32),
      thesis_revision: 1,
      as_of: "2026-08-30T00:00:00.000Z",
      asset_view: isB ? { view: "ASSET", stance: body.asset_view.stance, candidate_valuation: { status: "UNKNOWN", cases: {} } } : body.asset_view,
      trade_view: body.trade_view,
      portfolio_view: {
        ...body.portfolio_view,
        position_state: candidate.position_state,
        account_state: candidate.account_state,
        portfolio_capital_context: capitalContext,
      },
      view_provenance: { asset_view: { view_origin: "USER_DRAFT" }, trade_view: { view_origin: "USER_DRAFT" }, portfolio_view: { view_origin: "USER_DRAFT" } },
      next_best_action: nextBestAction,
      action_envelope: {
        allowed_actions: isA
          ? capitalUnknown || replacementReview || scenario === "D" ? ["WAIT", "RESEARCH MORE"] : ["BUY SMALL", "WAIT"]
          : isB ? ["RESEARCH MORE", "WAIT"] : ["AVOID", "RESEARCH MORE", "WAIT"],
        blocked_actions: campaign.campaign_id === CAMPAIGN_C ? ["BUY NOW", "BUY SMALL", "SCALE IN"] : [],
        maintain_conditions: [], upgrade_conditions: [], downgrade_conditions: [], invalidation_conditions: [],
      },
      maintain_conditions: [], upgrade_conditions: [], downgrade_conditions: [], invalidation_conditions: [],
      authority_facts: { candidate_opportunity: candidate },
      authority_refs: ["candidate-opportunity:fixture"],
    },
    proposal_fingerprint: FINGERPRINTS[campaign.campaign_id],
    commit_fields: {
      review_by: body.review_by,
      key_assumptions: body.key_assumptions,
      event_invalidation_conditions: body.event_invalidation_conditions,
      strategy_horizon: body.strategy_horizon,
    },
    authority_evaluations: {
      formal_thesis: { evaluation: "EVALUATED" }, formal_decision: { evaluation: "NOT_EVALUATED" },
      hard_risk: { evaluation: "EVALUATED", hard_risk_state: candidate.hard_risk_state },
      critical_data: { critical_data_evaluation: isB ? "ERROR" : "EVALUATED", critical_data_state: candidate.critical_data_state, reason_codes: candidate.reason_codes },
      material_change: { evaluation: "EVALUATED" }, sell_engine: { evaluation: "NOT_EVALUATED" },
    },
    decision_assurance: { dimension_states: {} },
    commit_requirements: { user_confirmed: true, expected_proposal_fingerprint: FINGERPRINTS[campaign.campaign_id], challenge_required: isA },
  };
}

async function fillDecisionBasics(page) {
  await page.getByLabel("Review by").fill("2026-09-30T12:00");
  await page.getByLabel("Key assumptions").fill("业务保持稳定");
  await page.getByLabel("Event invalidation conditions").fill("关键事实反转");
  await page.getByLabel("Asset stance").selectOption("SUPPORT");
  await page.getByLabel("Trade stance").selectOption("SUPPORT");
  await page.getByLabel("Portfolio constraint").fill("单笔风险受限");
}

async function fillConfidence(page, value) {
  for (const name of ["Data quality", "Evidence confidence", "Inference confidence", "Decision confidence"]) {
    await page.getByLabel(name).selectOption(value);
  }
}

async function fillCandidateAnchors(page) {
  let index = 0;
  for (const scenario of ["Bear", "Base", "Bull"]) {
    const low = 80 + index * 30;
    await page.getByLabel(`${scenario} price low`).fill(String(low));
    await page.getByLabel(`${scenario} price high`).fill(String(low + 10));
    await page.getByLabel(`${scenario} assumptions`).fill(`${scenario} assumption`);
    await page.getByLabel(`${scenario} input metric`).fill("forward_profit");
    await page.getByLabel(`${scenario} input value`).fill(String(100 + index * 10));
    await page.getByLabel(`${scenario} input period`).fill("FY2027");
    await page.getByLabel(`${scenario} source`).fill("公开财报");
    await page.getByLabel(`${scenario} data at`).fill("2026-08-15");
    await page.getByLabel(`${scenario} horizon`).fill("12 months");
    await page.getByLabel(`${scenario} change conditions`).fill("下一期利润事实改变");
    index += 1;
  }
  await page.getByLabel("Candidate entry low").fill("100");
  await page.getByLabel("Candidate entry high").fill("102");
  await page.getByLabel("Candidate invalidation price").fill("90");
}

let server;
let browser;
try {
  assert.ok(existsSync(path.join(dist, "index.html")), "dist/index.html missing; run npm run build");
  const port = await freePort();
  server = await startStaticServer(dist, port);
  browser = await chromium.launch({ headless: true, executablePath: chromiumPath() });
  const page = await browser.newPage();
  const state = {
    campaigns: [],
    createdPayloads: [],
    transitionPayloads: [],
    previewPayloads: {},
    challenge: null,
    committed: false,
    capitalScenario: "A",
    failNextCommitStale: false,
    apiPaths: [],
  };

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    state.apiPaths.push(pathname);

    if (pathname === "/api/valuation" && request.method() === "GET") {
      await route.fulfill(ok(valuation));
      return;
    }
    if (pathname === "/api/financials" && request.method() === "GET") {
      await route.fulfill(ok(financials));
      return;
    }
    if (pathname === "/api/market/cloud" && request.method() === "GET") {
      await route.fulfill(ok({
        status: "normal", warnings: [], is_stale: false, fetched_at: "2026-08-30T10:00:00Z",
        data: {
          scope: "all", period: "today", stock_count: 1, valid_count: 1, industry_count: 1, no_industry_count: 0,
          industries: [{ name: "白酒", stock_count: 1, total_float_cap: 100000000, avg_change_pct: 1, up_count: 1, down_count: 0, stocks: [{ code: "600519", name: "贵州茅台", price: 1300, change_pct: 1, amount: 1000000, float_market_cap: 100000000, turnover_pct: 1, industry: "白酒" }] }],
        },
      }));
      return;
    }
    if (pathname === "/api/watchlist" && request.method() === "GET") {
      await route.fulfill(ok({ status: "valid", data: { codes: ["600519"], updated_at: "2026-08-30T00:00:00Z" }, etag: "fixture" }));
      return;
    }
    if (pathname === "/api/watchlist/anomalies" && request.method() === "GET") {
      await route.fulfill(ok({ provider_id: "hithink_financial_api", provider_contract: "fixture", as_of_ms: null, unavailable_codes: [], items: [] }));
      return;
    }
    if (pathname === "/api/quote" && request.method() === "GET") {
      await route.fulfill(ok({ "600519": { code: "600519", name: "贵州茅台", price: 1300, change_pct: 1, amount_wan: 1000 } }));
      return;
    }
    if (pathname === "/api/native-intel/watchlist-context" && request.method() === "GET") {
      await route.fulfill(ok({ status: "normal", retrieved_at: "2026-08-30T00:00:00Z", authority_ref: "fixture", usage_boundary: "observation_only", watchlist_status: "valid", codes: ["600519"], degraded: [], securities: [] }));
      return;
    }
    if (pathname === "/api/native-intel/status" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "normal", sources: { total: 1, healthy: 1, failing: 0, never_run: 0, failing_names: [] }, source_health: [] }) });
      return;
    }
    if (pathname === "/api/native-intel/items" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "normal", items: [], total: 0, limit: 40, offset: 0 }) });
      return;
    }
    if (pathname === "/api/native-intel/trending" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "normal", window_hours: 24, item_count: 2, items: [], entities: [{ term: "贵州茅台", term_kind: "company_name", security_code: "600519", item_count: 2, source_count: 1, previous_item_count: 1, delta: 1 }] }) });
      return;
    }
    if (pathname === "/api/position/derived" && request.method() === "GET") {
      await route.fulfill(ok({
        derivation_status: "OK",
        bootstrap_status: "BOOTSTRAPPED",
        canonical: true,
        ledger_start: null,
        positions: [],
        data_limitations: [],
      }));
      return;
    }
    if (pathname === "/api/evidence" && request.method() === "GET") {
      assert.equal(url.searchParams.get("subject_type"), "stock");
      assert.equal(url.searchParams.get("subject_id"), "600519");
      await route.fulfill(ok({ items: evidenceRecords, total: evidenceRecords.length, limit: 200, offset: 0 }));
      return;
    }
    if (pathname === "/api/native-intel/security-context/600519" && request.method() === "GET") {
      await route.fulfill(ok(nativeIntelContext));
      return;
    }
    if (pathname === "/api/campaigns" && request.method() === "GET") {
      assert.equal(url.searchParams.get("security_code"), "600519", "Candidate Research must query the active security only");
      await route.fulfill(ok(state.campaigns));
      return;
    }
    if (pathname === "/api/campaigns" && request.method() === "POST") {
      const body = request.postDataJSON();
      state.createdPayloads.push(body);
      assert.deepEqual(Object.keys(body).sort(), ["security_code", "strategy"]);
      const campaign = {
        campaign_id: `campaign_${String.fromCharCode(96 + state.createdPayloads.length).repeat(32)}`,
        security_code: body.security_code,
        strategy: body.strategy,
        status: "DRAFT",
        created_at: "2026-08-26T00:00:00.000Z",
      };
      state.campaigns = [campaign];
      await route.fulfill({ status: 201, ...ok(campaign) });
      return;
    }

    const thesisBindingMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/thesis-binding$/);
    if (thesisBindingMatch && request.method() === "GET") {
      const campaign = [...state.campaigns, ...fixedCampaigns].find((item) => item.campaign_id === thesisBindingMatch[1]);
      if (campaign && [CAMPAIGN_A, CAMPAIGN_B, CAMPAIGN_C].includes(campaign.campaign_id)) {
        await route.fulfill(ok(thesisContext(campaign).binding));
        return;
      }
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Thesis Binding 不存在" }) });
      return;
    }
    if (pathname === "/api/thesis" && request.method() === "GET") {
      assert.equal(url.searchParams.get("subject_type"), "stock");
      assert.equal(url.searchParams.get("subject_id"), "600519");
      await route.fulfill(ok({ items: [], total: 0, limit: 200, offset: 0 }));
      return;
    }

    const campaignContextMatch = pathname.match(/^\/api\/campaigns\/([^/]+)$/);
    if (campaignContextMatch && request.method() === "GET") {
      const campaign = [...state.campaigns, ...fixedCampaigns].find((item) => item.campaign_id === campaignContextMatch[1]);
      assert.ok(campaign, "context requested for unknown campaign");
      await route.fulfill(ok(campaign));
      return;
    }
    const currentThesisMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/current-thesis$/);
    if (currentThesisMatch && request.method() === "GET") {
      const campaign = [...state.campaigns, ...fixedCampaigns].find((item) => item.campaign_id === currentThesisMatch[1]);
      assert.ok(campaign, "current thesis requested for unknown campaign");
      await route.fulfill(ok(thesisContext(campaign).current));
      return;
    }
    const thesisAggregateMatch = pathname.match(/^\/api\/thesis\/([^/]+)$/);
    if (thesisAggregateMatch && request.method() === "GET") {
      const campaign = [...state.campaigns, ...fixedCampaigns].find((item) => item.campaign_id.endsWith(thesisAggregateMatch[1]));
      assert.ok(campaign, "aggregate requested for unknown thesis");
      await route.fulfill(ok(thesisContext(campaign).aggregate));
      return;
    }

    const previewMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/decision-proposal\/preview$/);
    if (previewMatch && request.method() === "POST") {
      const campaign = [...state.campaigns, ...fixedCampaigns].find((item) => item.campaign_id === previewMatch[1]);
      assert.ok(campaign, "preview requested for unknown campaign");
      const body = request.postDataJSON();
      state.previewPayloads[campaign.campaign_id] = body;
      await route.fulfill(ok(previewFor(campaign, body, state.capitalScenario)));
      return;
    }
    const challengeLookupMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/decision-challenge$/);
    if (challengeLookupMatch && request.method() === "GET") {
      if (state.challenge && challengeLookupMatch[1] === CAMPAIGN_A) await route.fulfill(ok(state.challenge));
      else await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Decision Challenge 不存在" }) });
      return;
    }
    const challengeFinalizeMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/decision-challenge\/finalize$/);
    if (challengeFinalizeMatch && request.method() === "POST") {
      assert.equal(challengeFinalizeMatch[1], CAMPAIGN_A);
      const body = request.postDataJSON();
      const dimension_results = Object.fromEntries(Object.entries(body.dimensions).map(([key, value]) => [key, value]));
      state.challenge = {
        schema_version: "decision_challenge.v0.1",
        challenge: {
          challenge_id: CHALLENGE_A, packet_state: "COMPLETE", challenge_evaluation: "EVALUATED", challenge_coverage_state: "COMPLETE",
          decision_quality: "NOT_EVALUATED", two_pass_semantic_independence_verified: "NO", proposal_fingerprint: FINGERPRINTS[CAMPAIGN_A],
          proposal_as_of: body.as_of, finalized_at: "2026-08-30T00:01:00Z", first_pass_ref: "user", first_pass_at: "2026-08-30T00:01:00Z",
          second_pass_ref: "user", second_pass_at: "2026-08-30T00:01:00Z", two_pass_state: "SINGLE_USER_PASS", dimension_results,
        },
        decision_quality: "NOT_EVALUATED",
      };
      await route.fulfill(ok(state.challenge));
      return;
    }
    if (pathname === `/api/decision-challenges/${CHALLENGE_A}` && request.method() === "GET") {
      await route.fulfill(ok(state.challenge));
      return;
    }
    const commitMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/decision-proposal\/commit$/);
    if (commitMatch && request.method() === "POST") {
      assert.equal(commitMatch[1], CAMPAIGN_A);
      const body = request.postDataJSON();
      assert.equal(body.challenge_id, CHALLENGE_A, "bounded BUY Freeze must bind finalized Challenge");
      if (state.failNextCommitStale) {
        state.failNextCommitStale = false;
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "proposal fingerprint mismatch; re-preview required" }),
        });
        return;
      }
      state.committed = true;
      await route.fulfill(ok({
        schema_version: "decision_commit_runtime.v0.1", proposal_fingerprint: FINGERPRINTS[CAMPAIGN_A], idempotent: false,
        committed: { decision_id: DECISION_A, campaign_id: CAMPAIGN_A, next_best_action: "BUY SMALL" },
        formal_decision: { decision_id: DECISION_A, evaluation: "EVALUATED" }, critical_data: {}, decision_assurance: {},
      }));
      return;
    }
    if (pathname === `/api/campaigns/${CAMPAIGN_A}/decision-proposal/committed/${DECISION_A}` && request.method() === "GET") {
      const authority = { evaluation: "EVALUATED" };
      await route.fulfill(ok({
        schema_version: "decision_commit_runtime.v0.1", as_of: "2026-08-30T00:00:00.000Z",
        committed: { decision_id: DECISION_A, campaign_id: CAMPAIGN_A, next_best_action: "BUY SMALL" },
        formal_thesis: authority, critical_data: authority,
        formal_decision: { decision_id: DECISION_A, evaluation: "EVALUATED" },
        hard_risk: authority, material_change: authority, sell_engine: authority, decision_assurance: authority,
      }));
      return;
    }

    const nextActionsMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/next-actions$/);
    if (nextActionsMatch && request.method() === "GET") {
      const campaign = state.campaigns.find((item) => item.campaign_id === nextActionsMatch[1]);
      assert.ok(campaign, "next-actions requested for unknown candidate campaign");
      await route.fulfill(ok({
        campaign_id: campaign.campaign_id,
        security_code: campaign.security_code,
        strategy: campaign.strategy,
        status: campaign.status,
        next_actions: campaignsByStatus[campaign.status],
      }));
      return;
    }

    const transitionMatch = pathname.match(/^\/api\/campaigns\/([^/]+)\/transitions$/);
    if (transitionMatch && request.method() === "POST") {
      const campaign = state.campaigns.find((item) => item.campaign_id === transitionMatch[1]);
      assert.ok(campaign, "transition requested for unknown candidate campaign");
      const body = request.postDataJSON();
      state.transitionPayloads.push(body);
      assert.equal(body.expected_status, campaign.status);
      assert.ok(
        campaignsByStatus[campaign.status].includes(body.to_status),
        `transition target ${body.to_status} must come from backend next-actions for ${campaign.status}`,
      );
      const fromStatus = campaign.status;
      campaign.status = body.to_status;
      await route.fulfill(ok({
        campaign,
        transition: {
          transition_id: `transition_${state.transitionPayloads.length}`,
          campaign_id: campaign.campaign_id,
          from_status: fromStatus,
          to_status: campaign.status,
          transitioned_at: "2026-08-26T00:00:01.000Z",
        },
      }));
      return;
    }

    await route.fulfill(unavailable());
  });

  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}/stock-data?code=600519`, { waitUntil: "networkidle" });
  await page.locator('[data-active-code="600519"]').waitFor();
  assert.equal(
    state.apiPaths.filter((pathname) => pathname === "/api/campaigns").length,
    0,
    "normal StockData entry must not silently start the Candidate Workspace",
  );
  await page.getByTestId("stock-data-candidate-entry").click();
  await page.waitForURL(/\/candidates\/600519$/);
  const workspace = page.getByTestId("candidate-workspace");
  await workspace.waitFor();
  await workspace.locator('[data-position-state="NOT_HELD"]').waitFor();
  await workspace.getByTestId("native-intel-security-context").waitFor();
  await workspace.locator('[data-evidence-freshness="NOT_EVALUATED"]').waitFor();
  assert.equal(await workspace.locator('[data-evidence-source-conflict="UNKNOWN"]').count(), 1);
  await workspace.getByTestId("candidate-add-evidence").click();
  await page.waitForURL(/\/evidence\/new\?/);
  assert.equal(await page.getByPlaceholder("如 600519 / humanoid / AI算力").inputValue(), "600519");
  await page.getByRole("link", { name: "取消" }).click();
  await page.waitForURL(/\/candidates\/600519$/);

  // Every discovery surface keeps its normal StockData path and exposes a separate,
  // explicit Candidate Workspace continuation to the one canonical route.
  await page.goto(`http://127.0.0.1:${port}/market-cloud`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("候选研究代码").fill("600519");
  await page.getByTestId("market-cloud-candidate-entry").click();
  await page.waitForURL(/\/candidates\/600519$/);

  await page.goto(`http://127.0.0.1:${port}/watchlist`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("watchlist-candidate-600519").waitFor();
  assert.equal(await page.locator('[data-watchlist-code="600519"] a[href="/stock-data?code=600519"]').count(), 1);
  await page.getByTestId("watchlist-candidate-600519").click();
  await page.waitForURL(/\/candidates\/600519$/);

  await page.goto(`http://127.0.0.1:${port}/intel`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("market-intel-candidate-600519").waitFor();
  await page.getByTestId("market-intel-candidate-600519").click();
  await page.waitForURL(/\/candidates\/600519$/);
  await page.getByTestId("candidate-workspace").waitFor();

  const panel = page.getByTestId("candidate-campaign-panel");
  await panel.getByText("暂无候选 Campaign", { exact: true }).waitFor();
  const create = panel.getByTestId("create-candidate-campaign");
  assert.equal(await create.isDisabled(), true, "strategy must be explicitly selected before create");

  const shortRadio = panel.getByRole("radio", { name: "SHORT · 短线" });
  await shortRadio.evaluate((element) => element.click());
  await shortRadio.waitFor({ state: "attached" });
  assert.equal(await shortRadio.isChecked(), true);
  assert.equal(await create.isDisabled(), false);
  await create.click();
  await panel.locator('[data-campaign-status="DRAFT"]').waitFor();
  assert.deepEqual(state.createdPayloads, [{ security_code: "600519", strategy: "SHORT" }]);
  assert.equal(state.transitionPayloads.length, 0, "creation must not auto-transition beyond DRAFT");

  await panel.getByRole("button", { name: "继续研究", exact: true }).click();
  await panel.locator('[data-campaign-status="RESEARCHING"]').waitFor();
  await panel.getByRole("button", { name: "继续研究", exact: true }).click();
  await panel.locator('[data-campaign-status="PRE-ENTRY"]').waitFor();
  assert.equal(
    await panel.getByRole("button", { name: "停止研究（已拒绝）", exact: true }).count(),
    1,
    "backend REJECTED target must be presented as an explicit stop-research action",
  );
  assert.equal(
    await panel.getByRole("button", { name: "停止研究（已过期）", exact: true }).count(),
    1,
    "backend EXPIRED target must be presented as an explicit stop-research action",
  );
  await panel.getByRole("button", { name: "停止研究（已拒绝）", exact: true }).click();
  await panel.getByRole("button", { name: "确认停止研究（已拒绝）", exact: true }).click();
  await panel.getByText("暂无候选 Campaign", { exact: true }).waitFor();

  const swingRadio = panel.getByRole("radio", { name: "SWING · 波段" });
  await swingRadio.evaluate((element) => element.click());
  await panel.getByTestId("create-candidate-campaign").click();
  await panel.locator('[data-campaign-status="DRAFT"]').waitFor();
  await panel.getByRole("button", { name: "继续研究", exact: true }).click();
  await panel.locator('[data-campaign-status="RESEARCHING"]').waitFor();
  await panel.getByRole("button", { name: "继续研究", exact: true }).click();
  await panel.locator('[data-campaign-status="PRE-ENTRY"]').waitFor();
  await panel.getByRole("button", { name: "停止研究（已过期）", exact: true }).click();
  await panel.getByRole("button", { name: "确认停止研究（已过期）", exact: true }).click();
  await panel.getByText("暂无候选 Campaign", { exact: true }).waitFor();

  // A: complete evidence + NOT_HELD + structured scenarios + mandatory Challenge
  // produces a bounded BUY, can Freeze, and exposes the explicit Trade continuation.
  const mediumRadio = panel.getByRole("radio", { name: "MEDIUM · 中线" });
  await mediumRadio.evaluate((element) => element.click());
  await panel.getByTestId("create-candidate-campaign").click();
  await panel.locator('[data-campaign-status="DRAFT"]').waitFor();
  await panel.getByRole("button", { name: "继续研究", exact: true }).click();
  await panel.locator('[data-campaign-status="RESEARCHING"]').waitFor();
  await panel.getByRole("button", { name: "继续研究", exact: true }).click();
  await panel.locator('[data-campaign-status="PRE-ENTRY"]').waitFor();
  assert.equal(state.campaigns[0].campaign_id, CAMPAIGN_A);
  assert.equal(
    state.apiPaths.some((pathname) => pathname.includes("/decision-proposal/")),
    false,
    "Candidate Workspace must not Preview or Freeze before the explicit Review CTA",
  );
  await panel.getByTestId("formal-decision-review-cta").click();
  await page.locator(`[data-decision-proposal-page="${CAMPAIGN_A}"]`).waitFor();
  await page.locator('[data-decision-context="ready"]').waitFor();
  await fillDecisionBasics(page);
  await fillConfidence(page, "MEDIUM");
  await fillCandidateAnchors(page);
  await page.getByRole("button", { name: "Preview Proposal" }).click();
  await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
  await page.getByText("BUY SMALL", { exact: true }).first().waitFor();
  await page.getByTestId("candidate-opportunity-authority").getByText("NOT_HELD", { exact: true }).waitFor();
  const capitalCard = page.getByTestId("portfolio-capital-context");
  await capitalCard.locator('[data-capital-dimension="capital-availability"]').getByText("AVAILABLE", { exact: true }).waitFor();
  assert.equal(await capitalCard.getAttribute("data-portfolio-fit"), "SUPPORTIVE");
  assert.equal(await capitalCard.getAttribute("data-replacement-review"), "NOT_REQUIRED");
  const themeToggle = page.getByRole("button", { name: /^(亮色|暗色)模式$/ });
  await themeToggle.click();
  assert.equal(await capitalCard.isVisible(), true, "CAP1 context must remain visible after theme switch");
  await themeToggle.click();
  const aDraft = state.previewPayloads[CAMPAIGN_A];
  assert.deepEqual(Object.keys(aDraft.asset_view.candidate_valuation).sort(), ["base", "bear", "bull"]);
  assert.deepEqual(aDraft.trade_view.entry_range, { low: 100, high: 102 });
  assert.equal(Object.hasOwn(aDraft.portfolio_view, "position_state"), false, "browser must not submit a fake position state");
  assert.equal(Object.hasOwn(aDraft.portfolio_view, "portfolio_capital_context"), false, "browser must not submit CAP1 authority facts");

  // CAP1 A-E: one existing Candidate path renders each deterministic capital
  // state without introducing a replacement or trading control.
  for (const scenario of [
    ["B", "CONSTRAINED", "CONSTRAINED", "NOT_PROVEN", "CAPITAL_CONSTRAINED_NO_AUTOMATIC_REPLACEMENT"],
    ["C", "UNKNOWN", "UNKNOWN", "UNKNOWN", "ACCOUNT_REALITY_UNKNOWN"],
    ["D", "CONSTRAINED", "CONSTRAINED", "NOT_PROVEN", "REPLACEMENT_SUPERIORITY_NOT_PROVEN"],
    ["E", "CONSTRAINED", "CONSTRAINED", "WORTH_REVIEW", "INCUMBENT_THESIS_WEAKENED"],
  ]) {
    const [name, availability, fit, replacement, reason] = scenario;
    state.capitalScenario = name;
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    await page.locator(
      `[data-testid="portfolio-capital-context"][data-capital-availability="${availability}"][data-portfolio-fit="${fit}"][data-replacement-review="${replacement}"]`,
    ).waitFor();
    await capitalCard.getByText(reason, { exact: true }).first().waitFor();
  }
  assert.equal(await capitalCard.getByRole("button").count(), 0, "Replacement Review must not create an automatic action control");
  state.capitalScenario = "A";
  await page.getByRole("button", { name: "Preview Proposal" }).click();
  await page.locator('[data-testid="portfolio-capital-context"][data-capital-availability="AVAILABLE"]').waitFor();

  for (const label of ["Strongest supporting evidence", "Strongest opposing evidence", "Pre-mortem", "Invalidation facts"]) {
    await page.getByRole("textbox", { name: label }).fill(`${label} fixture`);
  }
  await page.getByRole("checkbox", { name: /我已显式填写四个挑战维度/ }).check();
  await page.getByRole("button", { name: "Finalize Decision Challenge" }).click();
  await page.locator('[data-challenge-state="FOUND"]').waitFor();
  await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
  state.failNextCommitStale = true;
  await page.getByRole("button", { name: "Freeze Formal Decision" }).click();
  await page.getByRole("alert").getByText(/Proposal 已失效/).waitFor();
  assert.equal(state.committed, false, "stale CAP1 Preview must not create a Frozen Decision");
  await page.getByRole("button", { name: "Preview Proposal" }).click();
  await page.locator('[data-testid="portfolio-capital-context"][data-capital-availability="AVAILABLE"]').waitFor();
  await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
  await page.getByRole("button", { name: "Freeze Formal Decision" }).click();
  await page.locator('[data-formal-decision-evaluation="EVALUATED"]').waitFor();
  const tradeContinuation = page.getByTestId("committed-decision-trade-continuation");
  const tradeHref = await tradeContinuation.getAttribute("href");
  assert.equal(tradeHref, `/trades?create=1&code=600519&campaign_id=${CAMPAIGN_A}&decision_id=${DECISION_A}&next_best_action=BUY+SMALL`);
  await tradeContinuation.click();
  await page.waitForURL((url) => url.pathname === "/trades" && url.searchParams.get("campaign_id") === CAMPAIGN_A);
  assert.equal(state.committed, true);

  // B: the user explicitly declares missing anchors. No price is fabricated;
  // UNKNOWN/UNAVAILABLE renders and backend keeps the action at RESEARCH MORE.
  await page.goto(`http://127.0.0.1:${port}/campaigns/${CAMPAIGN_B}/decision-proposal`, { waitUntil: "domcontentloaded" });
  await page.locator('[data-decision-context="ready"]').waitFor();
  await fillDecisionBasics(page);
  await fillConfidence(page, "UNKNOWN");
  await page.getByLabel("Candidate valuation anchors unavailable").check();
  await page.getByRole("button", { name: "Preview Proposal" }).click();
  await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
  await page.getByText("RESEARCH MORE", { exact: true }).first().waitFor();
  const bDraft = state.previewPayloads[CAMPAIGN_B];
  assert.equal(Object.hasOwn(bDraft.asset_view, "candidate_valuation"), false);
  assert.equal(Object.hasOwn(bDraft.trade_view, "entry_range"), false);
  assert.equal(bDraft.asset_view.data_quality, "UNKNOWN");
  const bAuthority = page.getByTestId("candidate-opportunity-authority");
  await bAuthority.getByText("UNAVAILABLE", { exact: true }).first().waitFor();
  await bAuthority.getByText(/INSUFFICIENT/).waitFor();
  const bCapital = page.getByTestId("portfolio-capital-context");
  assert.equal(await bCapital.getAttribute("data-capital-availability"), "UNKNOWN");
  assert.equal(await bCapital.getAttribute("data-portfolio-fit"), "UNKNOWN");
  assert.equal(await bCapital.getAttribute("data-replacement-review"), "UNKNOWN");
  assert.equal(await bCapital.getByTestId("portfolio-capital-confirmed-cash").textContent(), "UNKNOWN");

  // C: Hard Risk CONFIRMED blocks all added-risk actions and remains traceable.
  await page.goto(`http://127.0.0.1:${port}/campaigns/${CAMPAIGN_C}/decision-proposal`, { waitUntil: "domcontentloaded" });
  await page.locator('[data-decision-context="ready"]').waitFor();
  await fillDecisionBasics(page);
  await fillConfidence(page, "HIGH");
  await fillCandidateAnchors(page);
  await page.getByRole("button", { name: "Preview Proposal" }).click();
  await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
  await page.getByText("AVOID", { exact: true }).first().waitFor();
  await page.getByTestId("candidate-opportunity-authority").getByText("CONFIRMED", { exact: true }).waitFor();
  await page.getByText("HARD_RISK_CONFIRMED", { exact: true }).waitFor();
  assert.equal(await page.getByTestId("portfolio-capital-context").getAttribute("data-replacement-review"), "WORTH_REVIEW");
  await page.getByTestId("portfolio-capital-context").getByText("INCUMBENT_THESIS_WEAKENED", { exact: true }).first().waitFor();
  for (const action of ["BUY NOW", "BUY SMALL", "SCALE IN"]) {
    await page.locator('[data-action-envelope]').getByText(action, { exact: true }).waitFor();
  }

  assert.deepEqual(state.createdPayloads, [
    { security_code: "600519", strategy: "SHORT" },
    { security_code: "600519", strategy: "SWING" },
    { security_code: "600519", strategy: "MEDIUM" },
  ]);
  assert.deepEqual(state.transitionPayloads, [
    { expected_status: "DRAFT", to_status: "RESEARCHING" },
    { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
    { expected_status: "PRE-ENTRY", to_status: "REJECTED" },
    { expected_status: "DRAFT", to_status: "RESEARCHING" },
    { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
    { expected_status: "PRE-ENTRY", to_status: "EXPIRED" },
    { expected_status: "DRAFT", to_status: "RESEARCHING" },
    { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
  ]);
  assert.equal(
    state.apiPaths.some((pathname) => pathname.includes("activate-from-trade")),
    false,
    "browser vertical must never call Trade activation backend",
  );
  assert.deepEqual(pageErrors, []);
  console.log("candidate campaign browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
