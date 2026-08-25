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
  "PRE-ENTRY": ["ACTIVE", "REJECTED", "EXPIRED"],
};

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
        campaign_id: "campaign_candidate",
        security_code: body.security_code,
        strategy: body.strategy,
        status: "DRAFT",
        created_at: "2026-08-26T00:00:00.000Z",
      };
      state.campaigns = [campaign];
      await route.fulfill({ status: 201, ...ok(campaign) });
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

  assert.deepEqual(state.createdPayloads, [
    { security_code: "600519", strategy: "SHORT" },
    { security_code: "600519", strategy: "SWING" },
  ]);
  assert.deepEqual(state.transitionPayloads, [
    { expected_status: "DRAFT", to_status: "RESEARCHING" },
    { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
    { expected_status: "PRE-ENTRY", to_status: "REJECTED" },
    { expected_status: "DRAFT", to_status: "RESEARCHING" },
    { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
    { expected_status: "PRE-ENTRY", to_status: "EXPIRED" },
  ]);
  const forbiddenAuthorityPaths = /\/api\/(?:thesis(?:\/|$)|decision(?:[-/]|$)|trades?(?:\/|$)|buy(?:\/|$)|position(?:\/|$)|freeze(?:\/|$)|commit(?:\/|$)|formal-decisions?(?:\/|$)|frozen-decisions?(?:\/|$)|orders?(?:\/|$)|broker(?:\/|$))|\/api\/campaigns\/[^/]+\/(?:thesis-binding|current-thesis)(?:\/|$)/;
  assert.equal(
    state.apiPaths.some((pathname) => forbiddenAuthorityPaths.test(pathname)),
    false,
    "Candidate Research must not call Thesis, Decision, Trade, BUY, position, freeze, commit, order, or broker authorities",
  );
  assert.deepEqual(pageErrors, []);
  console.log("candidate campaign browser vertical: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
