/**
 * P0-CF1 real browser vertical on the OL1 Formal Outcome surface.
 *
 * Creates two real Frozen Decisions, one exact TAR1 attribution, one
 * same-security UNPLANNED trade, and one same-security UNALLOCATED trade in
 * isolated databases and two Fact Lake daily closes. The browser reads the
 * Formal Outcome surface from FastAPI and verifies the security close-to-close
 * path, refresh/readback and two-pass replay stability.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

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

function createFixtures(env) {
  const payload = {
    security_code: "600519",
    strategy: "SWING",
    campaign_id: "campaign_" + "a".repeat(32),
    thesis_id: "b".repeat(32),
    thesis_revision: 1,
    asset_view: {},
    trade_view: {},
    portfolio_view: {},
    next_best_action: "BUY SMALL",
    action_envelope: {},
    maintain_conditions: ["condition"],
    upgrade_conditions: [],
    downgrade_conditions: [],
    invalidation_conditions: ["invalidation"],
    strategy_horizon: "2w",
    review_by: "2026-08-16T00:00:00Z",
    key_assumptions: ["assumption"],
    event_invalidation_conditions: [],
    risk_policy_version: "ol1-risk",
    opportunity_policy_version: "ol1-opportunity",
    decision_policy_version: "ol1-decision",
    behavior_model_version: "ol1-behavior",
    data_quality: {},
    evidence_confidence: null,
    inference_confidence: null,
    decision_confidence: null,
    evidence_refs: [],
    risk_refs: [],
    source_refs: [],
    user_confirmed: true,
  };
  const script = `
import json, os
import formal_trade_attribution as fta
import formal_trade_attribution_store as ats
import frozen_decision_service as fds
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

payload = json.loads(os.environ['OL1_PAYLOAD'])
first = fds.freeze_decision(payload)
second_payload = dict(payload)
second_payload['thesis_id'] = 'c' * 32
second = fds.freeze_decision(second_payload)
lake = initialize_fact_lake(os.environ['VR_FACT_LAKE_ROOT'])
evaluation_as_of = os.environ['OL1_CF_EVALUATION_AS_OF']
start_trade_date = completed_trade_date_at(first['committed_at'])
end_trade_date = completed_trade_date_at(evaluation_as_of)
assert start_trade_date and end_trade_date and end_trade_date > start_trade_date
def publish_price(trade_date, close, event):
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
        fetched_at=f'{trade_date}T08:00:00.000000Z')
    observation, normalization = persist_tushare_daily_evidence(lake, capture)
    fact = build_tushare_daily_canonical_fact(observation.observation, normalization)
    publish_tushare_daily_canonical_fact(lake, fact)
publish_price(start_trade_date, 100.0, 1)
publish_price(end_trade_date, 110.0, 2)
exact = tls.create_trade({'code': '600519', 'name': '贵州茅台', 'operation': 'buy', 'execution_status': 'full', 'actual_price': 100, 'actual_quantity': 1, 'executed_at': '2026-08-18T01:00:00Z'})
unplanned = tls.create_trade({'code': '600519', 'name': '贵州茅台', 'operation': 'add', 'execution_status': 'full', 'actual_price': 101, 'actual_quantity': 1, 'executed_at': '2026-08-18T01:01:00Z'})
unallocated = tls.create_trade({'code': '600519', 'name': '贵州茅台', 'operation': 'add', 'execution_status': 'full', 'actual_price': 102, 'actual_quantity': 1, 'executed_at': '2026-08-18T01:02:00Z'})
record = fta.create_attribution(first, exact, attribution_id=fta.new_attribution_id(), created_at='2026-08-18T02:00:00.000000Z').to_dict()
ats.write_attribution(db_path=ats.resolve_formal_trade_attribution_db_path(), record=record)
tar.mark_unplanned(unplanned['trade_id'], {'confirm': True})
print(json.dumps({'first': first, 'second': second, 'exact': exact, 'unplanned': unplanned, 'unallocated': unallocated}))
`;
  const result = spawnSync(env.PYTHON || "python3", ["-c", script], {
    cwd: backendDir,
    env: { ...env, OL1_PAYLOAD: JSON.stringify(payload) },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout.trim());
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
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VR_FACT_LAKE_ROOT: join(tempDataDir, "fact-lake"),
      OL1_CF_EVALUATION_AS_OF: "2026-09-01T00:00:00.000000Z",
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: join(tempDataDir, "formal_trade_attributions.sqlite3"),
      VIBE_RESEARCH_TRADE_ORIGIN_DB: join(tempDataDir, "trade_origins.sqlite3"),
      PYTHONUNBUFFERED: "1",
    };
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);

    const fixtures = createFixtures(env);
    const evaluationAsOf = "2026-09-01T00:00:00.000000Z";
    const firstBefore = await jsonRequest(
      backend,
      `/api/formal-decisions/${fixtures.first.decision_id}/outcome?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`,
    );
    assert.deepEqual(firstBefore.actual_capital_outcome.trade_ids, [fixtures.exact.trade_id]);
    assert.equal(firstBefore.counterfactual_outcome.state, "EVALUATED");
    assert.equal(firstBefore.counterfactual_outcome.metric_kind, "SECURITY_CLOSE_TO_CLOSE_RETURN");
    assert.equal(firstBefore.counterfactual_outcome.security_return, "0.1");
    assert.equal(firstBefore.counterfactual_outcome.start_price_point.close, 100);
    assert.equal(firstBefore.counterfactual_outcome.end_price_point.close, 110);
    assert.equal(firstBefore.decision_time_replay.snapshot.actual_view, undefined);
    const replayHashBefore = firstBefore.decision_time_replay.replay_hash;
    const snapshotHashBefore = firstBefore.decision_snapshot_hash;

    const laterTrade = await jsonRequest(backend, "/api/trades", "POST", {
      code: "600519", name: "贵州茅台", operation: "add", execution_status: "full",
      actual_price: 103, actual_quantity: 1, executed_at: "2026-09-01T01:00:00Z",
    }, 200);
    assert.ok(laterTrade.trade_id);
    const firstAfter = await jsonRequest(
      backend,
      `/api/formal-decisions/${fixtures.first.decision_id}/outcome?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`,
    );
    assert.equal(firstAfter.decision_time_replay.replay_hash, replayHashBefore);
    assert.equal(firstAfter.decision_snapshot_hash, snapshotHashBefore);
    assert.deepEqual(firstAfter.actual_capital_outcome.trade_ids, [fixtures.exact.trade_id]);

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    await page.route("**/api/**", (route) => {
      const url = new URL(route.request().url());
      return route.continue({ url: `${backend}${url.pathname}${url.search}` });
    });

    await page.goto(`${frontend}/decision-performance?evaluation_as_of=${encodeURIComponent(evaluationAsOf)}`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Formal Decision Outcome" }).waitFor();
    await page.getByText("NO_ACTUAL_TRADE / NOT_APPLICABLE", { exact: true }).waitFor();
    await page.getByText("Security close-to-close path", { exact: true }).first().waitFor();
    await page.getByText("security path only; not portfolio P&L or decision quality", { exact: true }).first().waitFor();
    assert.equal(await page.getByText("Security close-to-close path", { exact: true }).count(), 2);
    assert.equal(await page.locator('[data-testid^="formal-outcome-"]').count(), 2);
    const actionableConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("ERR_NETWORK_ACCESS_DENIED"),
    );
    assert.equal(actionableConsoleErrors.length, 0, actionableConsoleErrors.join("\n"));

    await page.reload({ waitUntil: "networkidle" });
    await page.getByText("NO_ACTUAL_TRADE / NOT_APPLICABLE", { exact: true }).waitFor();
    assert.equal(await page.locator('[data-testid^="formal-outcome-"]').count(), 2);
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
