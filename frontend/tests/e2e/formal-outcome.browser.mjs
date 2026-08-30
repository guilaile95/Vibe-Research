/**
 * P0-CF1 real browser vertical on the OL1 Formal Outcome surface.
 *
 * Creates two real Campaign/Thesis siblings and freezes both through the
 * FastAPI + Chromium Decision Proposal surface. One sibling finalizes and
 * binds a Decision Challenge; the other freezes without a challenge. The
 * Python helper only prepares trades, attribution, and Fact Lake prices from
 * the decisions returned by the real API.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { seedActiveCampaign } from "./campaign-active-fixture.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = join(root, "backend");
const frontendDist = join(root, "frontend", "dist");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function pythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: ["-m", "uvicorn"] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3", "-m", "uvicorn"] };
  return { cmd: "python3", args: ["-m", "uvicorn"] };
}

function pythonScriptConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: [] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3"] };
  return { cmd: "python3", args: [] };
}

function chromiumPath() {
  const bases = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of bases) {
    if (!base || !existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [
        join(base, entry, "chrome-win64", "chrome.exe"),
        join(base, entry, "chrome-linux", "chrome"),
        join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      ];
      const found = candidates.find((candidate) => existsSync(candidate));
      if (found) return found;
    }
  }
  return undefined;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      // Backend is still starting.
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let pathname = (request.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function jsonRequest(base, pathname, method = "GET", body, expected = 200) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expected, `${method} ${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function createFrozenCurrentThesis(base, env, title) {
  const campaign = await jsonRequest(base, "/api/campaigns", "POST", {
    security_code: "600519",
    strategy: "SWING",
  }, 201);
  const created = await jsonRequest(base, "/api/thesis", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    title,
    summary: "isolated current thesis",
    core_claims: ["claim one", "claim two", "claim three"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    change_summary: "CF1 browser fixture",
  }, 200);
  const thesisId = created.thesis.id;
  const begun = await jsonRequest(base, `/api/thesis/${thesisId}/begin-formalization`, "POST", {}, 200);
  const updated = await jsonRequest(base, `/api/thesis/${thesisId}`, "PUT", {
    title: begun.thesis.title,
    summary: begun.thesis.summary,
    status: "active",
    core_claims: begun.thesis.core_claims,
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
    free_notes: null,
    expected_revision: begun.thesis.current_revision,
    change_summary: "CF1 browser formal content",
  }, 200);
  const confirmed = await jsonRequest(base, `/api/thesis/${thesisId}/confirm`, "POST", {
    expected_revision: updated.thesis.current_revision,
  }, 200);
  const frozen = await jsonRequest(base, `/api/thesis/${thesisId}/freeze`, "POST", {
    expected_revision: confirmed.thesis.current_revision,
  }, 200);
  assert.equal(frozen.thesis.formal_state, "frozen");
  await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/thesis-binding`, "POST", {
    thesis_id: thesisId,
  }, 201);
  for (const [from, to] of [["DRAFT", "RESEARCHING"], ["RESEARCHING", "PRE-ENTRY"]]) {
    await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/transitions`, "POST", {
      expected_status: from,
      to_status: to,
    }, 200);
  }
  seedActiveCampaign(backendDir, env, campaign.campaign_id);
  return campaign;
}

const draft = {
  horizon: "10 至 30 交易日",
  assumptions: "流动性保持稳定",
  invalidations: "业绩发生重大反转",
};

async function fillProposalDraft(page, reviewBy) {
  await page.getByLabel("Review by").fill(reviewBy);
  await page.getByLabel("Strategy horizon").fill(draft.horizon);
  await page.getByLabel("Key assumptions").fill(draft.assumptions);
  await page.getByLabel("Event invalidation conditions").fill(draft.invalidations);
  await page.waitForFunction(({ reviewBy, horizon }) => {
    const review = document.querySelector('[aria-label="Review by"]');
    const horizonInput = document.querySelector('[aria-label="Strategy horizon"]');
    return Boolean(
      review && review.value === reviewBy
      && horizonInput && horizonInput.value === horizon
    );
  }, { reviewBy, horizon: draft.horizon });
}

async function freezeThroughBrowser(page, backend, frontend, campaignId, withChallenge, dataDir, reviewBy) {
  await page.goto(`${frontend}/campaigns/${campaignId}/decision-proposal`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Formal Decision Review" }).waitFor();
  await page.locator(`[data-decision-proposal-page="${campaignId}"]`).waitFor();
  await fillProposalDraft(page, reviewBy);

  const previewResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && response.url().includes(`/api/campaigns/${campaignId}/decision-proposal/preview`)
  ), { timeout: 180000 });
  await page.getByRole("button", { name: "Preview Proposal" }).click();
  const previewResponse = await previewResponsePromise;
  const previewBody = await previewResponse.text();
  assert.equal(previewResponse.ok(), true, `[CF1] preview failed: status=${previewResponse.status()} body=${previewBody}`);
  await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
  await page.locator('[data-challenge-state="ABSENT"]').waitFor();
  if (withChallenge) {
    assert.equal(existsSync(join(dataDir, "decision_challenges.sqlite3")), false, "Preview must not write Challenge DB");
  }

  let challengeId;
  if (withChallenge) {
    await page.getByRole("textbox", { name: "Strongest supporting evidence" }).fill("渠道与报表支持当前等待");
    await page.getByRole("textbox", { name: "Strongest opposing evidence" }).fill("估值不便宜");
    await page.getByLabel("Pre-mortem status", { exact: true }).selectOption("UNKNOWN");
    await page.getByRole("textbox", { name: "Pre-mortem" }).fill("还没有足够的失效路径样本");
    await page.getByRole("textbox", { name: "Invalidation facts" }).fill("连续两个季度毛利率下修则失效");
    const finalize = page.getByRole("button", { name: "Finalize Decision Challenge" });
    assert.equal(await finalize.isEnabled(), false, "Finalize must require explicit confirmation");
    await page.getByRole("checkbox", { name: /我已显式填写四个挑战维度/ }).check();
    assert.equal(await finalize.isEnabled(), true);
    assert.equal(await finalize.isEnabled(), true, "Finalize must be enabled after four dimensions and confirmation");
    let finalizeResponse;
    let finalizeBody = "";
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const finalizeResponsePromise = page.waitForResponse((response) => (
        response.request().method() === "POST"
        && response.url().includes(`/api/campaigns/${campaignId}/decision-challenge/finalize`)
      ), { timeout: 180000 });
      await finalize.click();
      finalizeResponse = await finalizeResponsePromise;
      finalizeBody = await finalizeResponse.text();
      if (finalizeResponse.ok()) break;
      assert.equal(finalizeResponse.status(), 409, `[CF1] unexpected finalize failure: ${finalizeBody}`);
      assert.equal(attempt, 0, `[CF1] finalize remained stale after one re-preview: ${finalizeBody}`);
      assert.equal(existsSync(join(dataDir, "decision_challenges.sqlite3")), false, "Stale finalize must be zero-write");
      const retryPreviewResponsePromise = page.waitForResponse((response) => (
        response.request().method() === "POST"
        && response.url().includes(`/api/campaigns/${campaignId}/decision-proposal/preview`)
      ), { timeout: 180000 });
      await page.getByRole("button", { name: "Preview Proposal" }).click();
      const retryPreviewResponse = await retryPreviewResponsePromise;
      assert.equal(retryPreviewResponse.ok(), true, `[CF1] re-preview failed: ${await retryPreviewResponse.text()}`);
      await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
      await page.getByRole("checkbox", { name: /我已显式填写四个挑战维度/ }).check();
      assert.equal(await finalize.isEnabled(), true, "Finalize must re-enable after re-preview confirmation");
    }
    assert.ok(finalizeResponse);
    assert.equal(finalizeResponse.ok(), true, `[CF1] finalize failed: status=${finalizeResponse.status()} body=${finalizeBody}`);
    await page.locator('[data-challenge-state="FOUND"]').waitFor();
    challengeId = await page.locator("[data-challenge-id]").getAttribute("data-challenge-id");
    assert.match(challengeId, /^decision_challenge_[0-9a-f]{32}$/);
    const durable = await jsonRequest(backend, `/api/decision-challenges/${challengeId}`);
    assert.equal(durable.challenge.challenge_id, challengeId);
    assert.equal(durable.challenge.packet_state, "COMPLETE");
    assert.equal(durable.decision_quality, "NOT_EVALUATED");
    assert.equal(durable.challenge.two_pass_semantic_independence_verified, "NO");
    await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
  } else {
    await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
  }

  await page.getByRole("button", { name: "Freeze Formal Decision" }).click();
  await page.locator('[data-formal-decision-evaluation="EVALUATED"]').waitFor({ timeout: 180000 });
  const committedLine = await page.locator("[data-formal-decision-evaluation] p.font-mono").innerText();
  const decisionId = committedLine.replace(/^decision_id：/, "").trim();
  assert.match(decisionId, /^decision_[0-9a-f]{32}$/);
  const committed = await jsonRequest(backend, `/api/campaigns/${campaignId}/decision-proposal/committed/${decisionId}`);
  if (withChallenge) {
    assert.ok(committed.committed.source_refs.includes(`decision_challenge:${challengeId}`));
  } else {
    assert.equal(
      committed.committed.source_refs.some((item) => String(item).startsWith("decision_challenge:")),
      false,
      "no-challenge freeze must not invent a challenge ref",
    );
  }
  return { decisionId, challengeId, committed };
}

function prepareTradeAndFactLake(env, python, first, second) {
  const script = `
import json
import os
from datetime import datetime, timedelta
import formal_trade_attribution as fta
import formal_trade_attribution_store as ats
import trade_attribution_runtime as tar
import trade_ledger_service as tls
from fact_lake_store import initialize_fact_lake, payload_sha256
from trade_calendar import completed_trade_date_at
from tushare_daily_shadow import (
    DAILY_FIELD_MANIFEST,
    TushareDailyRawResponseCapture,
    TushareDailyRequestContract,
    build_request_fingerprint,
    build_tushare_daily_canonical_fact,
    persist_tushare_daily_evidence,
    publish_tushare_daily_canonical_fact,
)

first = json.loads(os.environ['OL1_FIRST_COMMITTED'])
second = json.loads(os.environ['OL1_SECOND_COMMITTED'])
lake = initialize_fact_lake(os.environ['VR_FACT_LAKE_ROOT'])
evaluation_as_of = os.environ['OL1_CF_EVALUATION_AS_OF']
committed_at = datetime.fromisoformat(first['committed_at'].replace('Z', '+00:00'))
evaluation_at = datetime.fromisoformat(evaluation_as_of.replace('Z', '+00:00'))
executed_at = committed_at + timedelta(seconds=1)
assert committed_at <= executed_at < evaluation_at
executed_at_text = executed_at.isoformat(timespec='seconds').replace('+00:00', 'Z')
unplanned_at_text = (executed_at + timedelta(seconds=1)).isoformat(timespec='seconds').replace('+00:00', 'Z')
unallocated_at_text = (executed_at + timedelta(seconds=2)).isoformat(timespec='seconds').replace('+00:00', 'Z')
created_at_text = (executed_at + timedelta(seconds=3)).isoformat(timespec='microseconds').replace('+00:00', 'Z')
start_trade_date = completed_trade_date_at(first['committed_at'])
end_trade_date = completed_trade_date_at(evaluation_as_of)
assert start_trade_date and end_trade_date and end_trade_date > start_trade_date
def visible_before(value):
    return (value - timedelta(microseconds=1)).isoformat(timespec='microseconds').replace('+00:00', 'Z')
def publish_price(trade_date, close, event, fetched_at):
    defaults = {'open': close, 'high': close + 1, 'low': close - 1,
                'close': close, 'pre_close': close - 1,
                'change': 1, 'pct_chg': 1, 'vol': 1000, 'amount': 100000}
    row = {**defaults, 'ts_code': '600519.SH', 'trade_date': trade_date.replace('-', '')}
    raw = json.dumps({'code': 0, 'msg': 'synthetic',
                      'data': {'fields': list(DAILY_FIELD_MANIFEST),
                               'items': [[row[field] for field in DAILY_FIELD_MANIFEST]]}},
                     separators=(',', ':')).encode()
    contract = TushareDailyRequestContract(trade_date)
    capture = TushareDailyRawResponseCapture(
        capture_event_id=f'capture-{event:032x}', contract=contract,
        raw_bytes=raw, request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw), http_status=200,
        content_type='application/json; charset=utf-8',
        fetched_at=fetched_at)
    observation, normalization = persist_tushare_daily_evidence(lake, capture)
    fact = build_tushare_daily_canonical_fact(observation.observation, normalization)
    publish_tushare_daily_canonical_fact(lake, fact)
publish_price(start_trade_date, 100.0, 1, visible_before(committed_at))
publish_price(end_trade_date, 110.0, 2, visible_before(evaluation_at))
exact = tls.create_trade({'code': '600519', 'name': '贵州茅台', 'operation': 'buy', 'execution_status': 'full', 'actual_price': 100, 'actual_quantity': 1, 'executed_at': executed_at_text})
unplanned = tls.create_trade({'code': '600519', 'name': '贵州茅台', 'operation': 'add', 'execution_status': 'full', 'actual_price': 101, 'actual_quantity': 1, 'executed_at': unplanned_at_text})
unallocated = tls.create_trade({'code': '600519', 'name': '贵州茅台', 'operation': 'add', 'execution_status': 'full', 'actual_price': 102, 'actual_quantity': 1, 'executed_at': unallocated_at_text})
record = fta.create_attribution(first, exact, attribution_id=fta.new_attribution_id(), created_at=created_at_text).to_dict()
ats.write_attribution(db_path=ats.resolve_formal_trade_attribution_db_path(), record=record)
tar.mark_unplanned(unplanned['trade_id'], {'confirm': True})
print(json.dumps({'first': first, 'second': second, 'exact': exact, 'unplanned': unplanned, 'unallocated': unallocated}))
`;
  const result = spawnSync(python.cmd, [...python.args.slice(0, -1), "-c", script], {
    cwd: backendDir,
    env: {
      ...env,
      OL1_FIRST_COMMITTED: JSON.stringify(first),
      OL1_SECOND_COMMITTED: JSON.stringify(second),
    },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout.trim());
}

function createOutcomeHistoryFillers(env, python, template, count = 50) {
  const script = `
import json
import os
import frozen_decision_service as frozen

template = json.loads(os.environ['RQ1_FILLER_TEMPLATE'])
count = int(os.environ['RQ1_FILLER_COUNT'])
service_fields = {
    'decision_id', 'committed_at', 'snapshot_schema_version',
    'snapshot_hash', 'validity_status_at_commit', 'created_at',
    'snapshot_json',
}
payload = {key: value for key, value in template.items() if key not in service_fields}
payload['review_by'] = '2099-09-09T10:00:00Z'
payload['source_refs'] = ['rq1:e2e-history-filler']
created = [frozen.freeze_decision(payload)['decision_id'] for _ in range(count)]
print(json.dumps(created))
`;
  const result = spawnSync(python.cmd, [...python.args, "-c", script], {
    cwd: backendDir,
    env: {
      ...env,
      RQ1_FILLER_TEMPLATE: JSON.stringify(template),
      RQ1_FILLER_COUNT: String(count),
    },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const ids = JSON.parse(result.stdout.trim());
  assert.equal(ids.length, count);
  assert.equal(new Set(ids).size, count);
  return ids;
}

function createHistoricalActionFixtures(env, python, template, specs) {
  const script = `
import json
import os
import frozen_decision_service as frozen

template = json.loads(os.environ['REV2_ACTION_TEMPLATE'])
specs = json.loads(os.environ['REV2_ACTION_SPECS'])
service_fields = {
    'decision_id', 'committed_at', 'snapshot_schema_version',
    'snapshot_hash', 'validity_status_at_commit', 'created_at',
    'snapshot_json',
}
all_actions = ('WAIT', 'HOLD', 'BUY NOW', 'BUY SMALL', 'SCALE IN', 'WATCH TO REDUCE', 'REDUCE', 'EXIT', 'AVOID', 'RESEARCH MORE')
allowed_by_action = {
    'WAIT': ('WAIT', 'RESEARCH MORE'),
    'HOLD': ('HOLD', 'WAIT', 'RESEARCH MORE'),
    'EXIT': ('EXIT', 'WAIT', 'RESEARCH MORE'),
}
created = []
for spec in specs:
    action = spec['next_best_action']
    payload = {key: value for key, value in template.items() if key not in service_fields}
    payload['review_by'] = spec['review_by']
    payload['strategy'] = spec.get('strategy', payload['strategy'])
    payload['next_best_action'] = action
    payload['action_envelope'] = {
        **payload['action_envelope'],
        'allowed_actions': list(allowed_by_action[action]),
        'blocked_actions': [value for value in all_actions if value not in allowed_by_action[action]],
    }
    payload['source_refs'] = [f"rev2:e2e-historical-nba:{action}"]
    created.append(frozen.freeze_decision(payload)['decision_id'])
print(json.dumps(created))
`;
  const result = spawnSync(python.cmd, [...python.args, "-c", script], {
    cwd: backendDir,
    env: {
      ...env,
      REV2_ACTION_TEMPLATE: JSON.stringify(template),
      REV2_ACTION_SPECS: JSON.stringify(specs),
    },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const ids = JSON.parse(result.stdout.trim());
  assert.equal(ids.length, specs.length);
  assert.equal(new Set(ids).size, specs.length);
  return ids;
}

async function removeTempDir(dir) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      rmSync(dir, { recursive: true, force: true });
      return;
    } catch (error) {
      if (attempt === 19) throw error;
      await sleep(100);
    }
  }
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before OL1 browser E2E");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-ol1-formal-outcome-e2e-"));
  let backendProc;
  let staticServer;
  let browser;
  let backendLog = "";
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;
    const py = pythonConfig();
    const env = {
      ...process.env,
      VR_ALLOW_ORIGINS: frontend,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VR_FACT_LAKE_ROOT: join(tempDataDir, "fact-lake"),
      OL1_CF_EVALUATION_AS_OF: "2026-09-01T00:00:00.000000Z",
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_DECISION_CHALLENGE_DB: join(tempDataDir, "decision_challenges.sqlite3"),
      VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: join(tempDataDir, "formal_trade_attributions.sqlite3"),
      VIBE_RESEARCH_TRADE_ORIGIN_DB: join(tempDataDir, "trade_origins.sqlite3"),
      PYTHONPATH: [__dirname, backendDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      PYTHONUNBUFFERED: "1",
    };
    backendProc = spawn(py.cmd, [...py.args, "decision_challenge_backend_harness:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);

    const firstCampaign = await createFrozenCurrentThesis(backend, env, "CF1 with challenge");
    const secondCampaign = await createFrozenCurrentThesis(backend, env, "CF1 without challenge");
    const thirdCampaign = await createFrozenCurrentThesis(backend, env, "RQ1 NOT_DUE sibling");
    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    const exactOutcomeRequests = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        request.method() === "GET"
        && /^\/api\/formal-decisions\/decision_[0-9a-f]{32}\/outcome$/.test(url.pathname)
      ) {
        exactOutcomeRequests.push(url);
      }
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      try {
        const response = await fetch(`${backend}${url.pathname}${url.search}`, {
          method: request.method(),
          headers: request.headers(),
          body: request.method() === "GET" || request.method() === "HEAD" ? undefined : request.postDataBuffer(),
        });
        await route.fulfill({
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          body: Buffer.from(await response.arrayBuffer()),
        });
      } catch (error) {
        await route.fulfill({
          status: 599,
          contentType: "application/json",
          body: JSON.stringify({ detail: "E2E backend proxy failed", error: String(error) }),
        });
      }
    });

    const firstRun = await freezeThroughBrowser(
      page,
      backend,
      frontend,
      firstCampaign.campaign_id,
      true,
      tempDataDir,
      "2026-08-01T10:00",
    );
    const secondRun = await freezeThroughBrowser(
      page,
      backend,
      frontend,
      secondCampaign.campaign_id,
      false,
      tempDataDir,
      "2026-08-02T10:00",
    );
    const historyFillerIds = createOutcomeHistoryFillers(
      env,
      pythonScriptConfig(),
      secondRun.committed.committed,
    );
    const historicalActionIds = createHistoricalActionFixtures(
      env,
      pythonScriptConfig(),
      firstRun.committed.committed,
      [
        { next_best_action: "WAIT", review_by: "2099-09-11T10:00:00Z", strategy: "SWING" },
        { next_best_action: "HOLD", review_by: "2099-09-12T10:00:00Z", strategy: "MEDIUM" },
        { next_best_action: "EXIT", review_by: "2099-09-13T10:00:00Z", strategy: "SWING" },
      ],
    );
    const thirdRun = await freezeThroughBrowser(
      page,
      backend,
      frontend,
      thirdCampaign.campaign_id,
      false,
      tempDataDir,
      "2099-09-10T10:00",
    );
    const fixtures = prepareTradeAndFactLake(env, pythonScriptConfig(), firstRun.committed.committed, secondRun.committed.committed);
    const evaluationAsOf = "2026-09-01T00:00:00.000000Z";
    assert.ok(firstRun.committed.committed.source_refs, JSON.stringify(firstRun.committed));
    const firstBefore = await jsonRequest(
      backend,
      `/api/formal-decisions/${firstRun.decisionId}/outcome?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`,
    );
    assert.deepEqual(firstBefore.actual_capital_outcome.trade_ids, [fixtures.exact.trade_id]);
    assert.equal(typeof firstBefore.decision_next_best_action, "string");
    assert.equal(firstBefore.actual_capital_outcome.state, "EVALUATED");
    assert.equal(firstBefore.process_review.state, "BOUND", JSON.stringify(firstBefore.process_review));
    assert.equal(firstBefore.process_review.challenge_id, firstRun.challengeId);
    assert.equal(firstBefore.process_review.packet_state, "COMPLETE");
    assert.equal(firstBefore.process_review.two_pass_state, "VALID");
    assert.equal(firstBefore.process_review.two_pass_semantic_independence_verified, "NO");
    assert.equal(firstBefore.process_review.dimensions.PRE_MORTEM.status, "UNKNOWN");
    assert.equal(firstBefore.process_quality.state, "NOT_EVALUATED");
    assert.deepEqual(firstBefore.process_quality.reason_codes, ["NO_PROCESS_QUALITY_AUTHORITY"]);
    assert.equal(firstBefore.counterfactual_outcome.state, "EVALUATED", JSON.stringify(firstBefore.counterfactual_outcome));
    assert.equal(firstBefore.counterfactual_outcome.metric_kind, "SECURITY_CLOSE_TO_CLOSE_RETURN");
    assert.equal(firstBefore.counterfactual_outcome.security_return, "0.1");
    assert.equal(firstBefore.counterfactual_outcome.start_price_point.close, 100);
    assert.equal(firstBefore.counterfactual_outcome.end_price_point.close, 110);
    assert.equal(firstBefore.decision_time_replay.snapshot.actual_view, undefined);
    const replayHashBefore = firstBefore.decision_time_replay.replay_hash;
    const snapshotHashBefore = firstBefore.decision_snapshot_hash;
    const outcomeRevealHashBefore = firstBefore.outcome_reveal?.outcome_reveal_hash;
    const actualCapitalBefore = JSON.stringify(firstBefore.actual_capital_outcome);
    const counterfactualBefore = JSON.stringify(firstBefore.counterfactual_outcome);

    const laterTrade = await jsonRequest(backend, "/api/trades", "POST", {
      code: "600519", name: "贵州茅台", operation: "add", execution_status: "full",
      actual_price: 103, actual_quantity: 1, executed_at: "2026-09-01T01:00:00Z",
    }, 200);
    assert.ok(laterTrade.trade_id);
    const firstAfter = await jsonRequest(
      backend,
      `/api/formal-decisions/${firstRun.decisionId}/outcome?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`,
    );
    assert.equal(firstAfter.decision_time_replay.replay_hash, replayHashBefore);
    assert.equal(firstAfter.decision_snapshot_hash, snapshotHashBefore);
    assert.deepEqual(firstAfter.actual_capital_outcome.trade_ids, [fixtures.exact.trade_id]);
    assert.equal(firstAfter.outcome_reveal?.outcome_reveal_hash, outcomeRevealHashBefore);
    assert.equal(JSON.stringify(firstAfter.actual_capital_outcome), actualCapitalBefore);
    assert.equal(JSON.stringify(firstAfter.counterfactual_outcome), counterfactualBefore);

    const secondOutcome = await jsonRequest(
      backend,
      `/api/formal-decisions/${secondRun.decisionId}/outcome?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`,
    );
    assert.equal(secondOutcome.outcome_status, "EVALUATED");
    assert.equal(secondOutcome.process_review.state, "NONE");
    assert.equal(typeof secondOutcome.decision_time_replay.replay_hash, "string");
    assert.equal(secondOutcome.process_quality.state, "NOT_EVALUATED");
    assert.equal(secondOutcome.actual_capital_outcome.state, "NO_ACTUAL_TRADE");
    assert.equal(secondOutcome.counterfactual_outcome.state, "EVALUATED");
    assert.equal(secondOutcome.counterfactual_outcome.security_return, "0.1");
    const thirdOutcome = await jsonRequest(
      backend,
      `/api/formal-decisions/${thirdRun.decisionId}/outcome?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`,
    );
    assert.equal(thirdOutcome.outcome_status, "PENDING");
    assert.equal(thirdOutcome.due_state, "NOT_DUE");
    assert.equal(thirdOutcome.actual_capital_outcome.state, "PENDING");

    const worklist = await jsonRequest(backend, "/api/formal-decision-review-worklist");
    assert.equal(worklist.due.length, 2, JSON.stringify(worklist));
    assert.equal(worklist.upcoming.length, historyFillerIds.length + 1 + historicalActionIds.length, JSON.stringify(worklist));
    assert.equal(worklist.unavailable.length, 0, JSON.stringify(worklist));
    assert.equal(worklist.schema_version, "formal_decision_review_worklist.v0.2");
    const firstDueItem = worklist.due.find((item) => item.decision_id === firstRun.decisionId);
    assert.equal(firstDueItem.decision_next_best_action, firstBefore.decision_next_best_action);
    for (const [decisionId, action] of historicalActionIds.map((id, index) => [id, ["WAIT", "HOLD", "EXIT"][index]])) {
      assert.equal(worklist.upcoming.find((item) => item.decision_id === decisionId).decision_next_best_action, action);
    }
    assert.deepEqual(worklist.due.map((item) => item.decision_id), [firstRun.decisionId, secondRun.decisionId]);
    assert.equal(worklist.due.every((item) => item.due_state === "DUE"), true);
    const upcomingDecisionIds = worklist.upcoming.map((item) => item.decision_id);
    assert.equal(upcomingDecisionIds.includes(thirdRun.decisionId), true);
    assert.equal(historyFillerIds.every((decisionId) => upcomingDecisionIds.includes(decisionId)), true);
    assert.equal(worklist.upcoming.every((item) => item.due_state === "NOT_DUE"), true);
    assert.equal(worklist.due.some((item) => item.due_state === "OVERDUE"), false);
    assert.equal(worklist.upcoming.some((item) => item.due_state === "UPCOMING"), false);
    assert.deepEqual(
      [...worklist.due, ...worklist.upcoming].map((item) => item.decision_review_by),
      [...worklist.due, ...worklist.upcoming]
        .map((item) => item.decision_review_by)
        .sort(),
    );
    assert.equal(
      readdirSync(tempDataDir).some((name) => /queue/i.test(name)),
      false,
      "RQ1 must not create queue persistence",
    );

    const legacyAnalyticsRequests = [];
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.startsWith("/api/decision-analytics/")) {
        legacyAnalyticsRequests.push(request.url());
      }
    });
    await page.goto(`${frontend}/decision-performance?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Formal Decision Outcome" }).waitFor();
    await page.getByTestId(`formal-outcome-${historyFillerIds[0]}`).getByText("PENDING / NOT_DUE", { exact: true }).waitFor();
    await page.getByText("Frozen Decision Context", { exact: true }).first().waitFor();
    await page.getByTestId(`formal-decision-context-${firstRun.decisionId}`).getByText(`Frozen NBA at decision time: ${firstBefore.decision_next_best_action}`, { exact: true }).waitFor();
    await page.getByText("NO_ACTUAL_TRADE / NOT_APPLICABLE", { exact: true }).waitFor();
    await page.getByTestId(`process-review-bound-${firstRun.decisionId}`).waitFor();
    await page.getByText("Challenge coverage is not decision correctness.", { exact: true }).waitFor();
    await page.getByTestId(`process-review-none-${secondRun.decisionId}`).waitFor();
    await page.getByText("Security close-to-close path", { exact: true }).first().waitFor();
    await page.getByText("security path only; not portfolio P&L or decision quality", { exact: true }).first().waitFor();
    assert.equal(await page.getByText("Security close-to-close path", { exact: true }).count(), 2);
    await page.getByTestId("review-worklist-group-due").waitFor();
    await page.getByTestId("review-worklist-group-upcoming").waitFor();
    await page.getByTestId("review-worklist-group-unavailable").waitFor();
    const dueItem = page.getByTestId(`review-worklist-due-${firstRun.decisionId}`);
    const secondDueItem = page.getByTestId(`review-worklist-due-${secondRun.decisionId}`);
    const upcomingItem = page.getByTestId(`review-worklist-upcoming-${thirdRun.decisionId}`);
    const historicalActionItems = historicalActionIds.map((decisionId) => page.getByTestId(`review-worklist-upcoming-${decisionId}`));
    await dueItem.waitFor();
    await secondDueItem.waitFor();
    await upcomingItem.waitFor();
    for (const item of historicalActionItems) await item.waitFor();
    await dueItem.getByTestId(`review-worklist-nba-${firstRun.decisionId}`).getByText(`Frozen NBA at decision time: ${firstDueItem.strategy || "—"} · ${firstBefore.decision_next_best_action}`, { exact: true }).waitFor();
    await historicalActionItems[0].getByText("Frozen NBA at decision time: SWING · WAIT", { exact: true }).waitFor();
    await historicalActionItems[1].getByText("Frozen NBA at decision time: MEDIUM · HOLD", { exact: true }).waitFor();
    await historicalActionItems[2].getByText("Frozen NBA at decision time: SWING · EXIT", { exact: true }).waitFor();
    assert.equal(await dueItem.getByText("DUE", { exact: true }).count(), 1);
    assert.equal(await secondDueItem.getByText("DUE", { exact: true }).count(), 1);
    assert.equal(await upcomingItem.getByText("NOT_DUE", { exact: true }).count(), 1);
    assert.equal(await page.getByTestId("review-worklist-unavailable").count(), 0);
    assert.equal(await page.locator('[data-testid^="formal-outcome-"]').count(), 50);
    assert.equal(await page.getByTestId(`formal-outcome-${thirdRun.decisionId}`).count(), 0);
    assert.equal(
      exactOutcomeRequests.filter((url) => url.pathname === `/api/formal-decisions/${thirdRun.decisionId}/outcome`).length,
      0,
    );
    const exactOutcomeRequestPromise = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return request.method() === "GET"
        && url.pathname === `/api/formal-decisions/${thirdRun.decisionId}/outcome`;
    });
    await upcomingItem.click();
    const exactOutcomeRequest = await exactOutcomeRequestPromise;
    assert.equal(new URL(exactOutcomeRequest.url()).searchParams.get("evaluation_as_of"), evaluationAsOf);
    const mergedTargetOutcome = page.getByTestId(`formal-outcome-${thirdRun.decisionId}`);
    await mergedTargetOutcome.waitFor();
    await mergedTargetOutcome.getByText("PENDING / NOT_DUE", { exact: true }).waitFor();
    await page.waitForFunction((decisionId) => document.activeElement?.id === `formal-outcome-${decisionId}`, thirdRun.decisionId);
    assert.equal(await page.locator('[data-testid^="formal-outcome-"]').count(), 51);

    for (const [index, decisionId] of historicalActionIds.entries()) {
      const action = ["WAIT", "HOLD", "EXIT"][index];
      const actionItem = page.getByTestId(`review-worklist-upcoming-${decisionId}`);
      const detailRequest = page.waitForRequest((request) => {
        const url = new URL(request.url());
        return request.method() === "GET"
          && url.pathname === `/api/formal-decisions/${decisionId}/outcome`;
      });
      await actionItem.click();
      await detailRequest;
      const actionOutcome = page.getByTestId(`formal-outcome-${decisionId}`);
      await actionOutcome.waitFor();
      await actionOutcome.getByText(`Frozen NBA at decision time: ${action}`, { exact: true }).waitFor();
      await actionOutcome.getByText("PENDING / NOT_DUE", { exact: true }).waitFor();
    }
    assert.equal(typeof firstBefore.decision_next_best_action, "string");
    assert.equal(
      await page.getByTestId(`formal-outcome-${firstRun.decisionId}`).getByText(firstBefore.decision_next_best_action, { exact: true }).count() >= 1,
      true,
    );
    assert.equal(await page.getByTestId(`formal-outcome-${firstRun.decisionId}`).getByText("BUY", { exact: true }).count(), 0);
    const actionableConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("ERR_NETWORK_ACCESS_DENIED")
        && !message.includes("Failed to load resource: the server responded with a status of 404"),
    );
    assert.equal(actionableConsoleErrors.length, 0, actionableConsoleErrors.join("\n"));

    // P1-REV1: 决策复盘面权威分离——Formal Outcome 是默认主内容；legacy 反馈分析
    // 明确标记 Legacy、默认折叠；进入页面不触发 decision-analytics 请求，展开才加载。
    assert.equal(await page.getByRole("heading", { name: "决策复盘", exact: true }).count(), 1);
    assert.equal(
      legacyAnalyticsRequests.length,
      0,
      `进入复盘页不应触发 legacy decision-analytics 请求：${legacyAnalyticsRequests.join(", ")}`,
    );
    const legacyToggle = page.getByTestId("legacy-analytics-toggle");
    assert.ok(await legacyToggle.isVisible(), "legacy analytics 折叠开关应可见");
    assert.match(await legacyToggle.innerText(), /Legacy/, "legacy 区域必须带 Legacy 标识");
    assert.equal(await page.getByTestId("legacy-analytics-panel").count(), 0, "legacy analytics 默认折叠");
    await legacyToggle.click();
    await page.getByTestId("legacy-analytics-panel").waitFor();
    await page.getByRole("heading", { name: "采纳率" }).waitFor();
    assert.ok(
      legacyAnalyticsRequests.length >= 3,
      `展开 legacy analytics 应触发三组请求，实际：${legacyAnalyticsRequests.join(", ")}`,
    );

    await page.reload({ waitUntil: "networkidle" });
    await page.getByTestId(`formal-outcome-${historyFillerIds[0]}`).getByText("PENDING / NOT_DUE", { exact: true }).waitFor();
    await page.getByText("NO_ACTUAL_TRADE / NOT_APPLICABLE", { exact: true }).waitFor();
    await page.getByTestId(`process-review-bound-${firstRun.decisionId}`).waitFor();
    await page.getByTestId(`process-review-none-${secondRun.decisionId}`).waitFor();
    await page.getByTestId("review-worklist-group-due").waitFor();
    await page.getByTestId("review-worklist-group-upcoming").waitFor();
    await page.getByTestId(`review-worklist-due-${firstRun.decisionId}`).waitFor();
    await page.getByTestId(`review-worklist-due-${secondRun.decisionId}`).waitFor();
    const reloadedUpcoming = page.getByTestId(`review-worklist-upcoming-${thirdRun.decisionId}`);
    await reloadedUpcoming.waitFor();
    assert.equal(await reloadedUpcoming.getByText("NOT_DUE", { exact: true }).count(), 1);
    assert.equal(await page.locator('[data-testid^="formal-outcome-"]').count(), 50);
    assert.equal(await page.getByTestId(`formal-outcome-${thirdRun.decisionId}`).count(), 0);
    console.log("[E2E] P0-CF1 Formal Decision Outcome vertical passed");
  } catch (error) {
    const detail = backendLog ? `\nBackend log:\n${backendLog}` : "";
    throw new Error(`${error.message}${detail}`, { cause: error });
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backendProc) backendProc.kill();
    await removeTempDir(tempDataDir);
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
