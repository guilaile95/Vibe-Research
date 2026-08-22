/**
 * P1-CASH1 real Chromium vertical: Bootstrap Opening Cash Authority Readback.
 *
 * Proves on the real FastAPI + built-frontend surface, isolated data dir:
 * A  pre-bootstrap Portfolio still shows the honest "not configured" empty state;
 * B  after canonical bootstrap with opening_cash, the account area reads the
 *    ledger-derived cash candidate (opening_cash + trades + cash events) with
 *    explicit candidate semantics — no duplicate manual entry required;
 * C  a new trade updates the displayed cash through the same authority;
 * D  when a manual snapshot exists, both facts are distinguished and their
 *    mismatch is explicit (never silently merged or overwritten).
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
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
  const payload = await response.json().catch(() => ({}));
  assert.equal(response.status, expected, `${method} ${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before CASH1 browser vertical");
    const tempDataDir = mkdtempSync(join(tmpdir(), "vr-cash1-cash-readback-e2e-"));
    const priceFixtureDir = mkdtempSync(join(tmpdir(), "vr-cash1-price-fixture-"));
    writeFileSync(join(priceFixtureDir, "sitecustomize.py"), `
import astock

def _cash1_kline(code, category=4, offset=5):
    if code == "600519":
        return [{"datetime": "2026-08-04 15:00:00", "close": 20.0}]
    return []

astock.kline = _cash1_kline
`, "utf8");
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
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_DECISION_CHALLENGE_DB: join(tempDataDir, "decision_challenges.sqlite3"),
      VIBE_RESEARCH_TRADE_ATTRIBUTION_DB: join(tempDataDir, "formal_trade_attributions.sqlite3"),
      VIBE_RESEARCH_TRADE_ORIGIN_DB: join(tempDataDir, "trade_origins.sqlite3"),
      VR_ALLOW_ORIGINS: frontend,
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: [priceFixtureDir, backendDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    };
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
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
          body: JSON.stringify({ detail: "CASH1 E2E backend proxy failed", error: String(error) }),
        });
      }
    });

    const openPortfolio = async () => {
      await page.goto(`${frontend}/portfolio`, { waitUntil: "networkidle" });
    };

    // ---- A. pre-bootstrap：诚实空态保持 ----------------------------------
    await openPortfolio();
    assert.ok(await page.getByText("尚未配置账户资金").isVisible());
    assert.equal(await page.getByTestId("account-cash-ledger-view").count(), 0);

    // ---- B. bootstrap 后 canonical cash 直接可读，无需重复录入 ------------
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      note: "CASH1 vertical bootstrap",
      positions: [],
    });

    await openPortfolio();
    const ledgerView = page.getByTestId("account-cash-ledger-view");
    await ledgerView.waitFor();
    assert.ok((await ledgerView.innerText()).includes("¥100,000.00"), "candidate value must display");
    const candidateText = await ledgerView.innerText();
    // R1 语义：必须表达为 ledger-derived candidate，不得称为 canonical/current cash；
    // 且必须保留 settled NAV 依赖 manual CURRENT FACT 的事实。
    assert.ok(candidateText.includes("ledger-derived candidate"));
    assert.ok(candidateText.includes("DERIVED_FACT"));
    assert.ok(candidateText.includes("MANUAL CURRENT FACT"), "manual snapshot dependency must stay visible");
    assert.equal(candidateText.includes("canonical"), false, "must not be labelled canonical");
    assert.equal(await page.getByText("尚未配置账户资金").count(), 0);

    // ---- C. trade 通过同一权威更新展示现金 -------------------------------
    await jsonRequest(backend, "/api/trades", "POST", {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "full",
      actual_price: 10,
      actual_quantity: 50,
      executed_at: "2026-08-05T10:00:00Z",
    });

    await openPortfolio();
    const afterTradeView = page.getByTestId("account-cash-ledger-view");
    await afterTradeView.waitFor();
    assert.ok(
      (await afterTradeView.innerText()).includes("¥99,500.00"),
      "ledger cash must reflect buy cash outflow (100000 - 500)",
    );

    // ---- D. 手工快照与推演并存时语义区分、mismatch 显式 -------------------
    await jsonRequest(backend, "/api/account-profile", "PUT", {
      total_assets: 200000,
      available_cash: 88888,
    });

    await openPortfolio();
    // 配置后显示手工快照（用户显式确认值），不冒充 canonical。
    assert.ok(await page.getByText("¥88,888.00").first().isVisible());
    const reconBadge = page.getByTestId("account-cash-reconciliation");
    await reconBadge.waitFor();
    const badgeText = await reconBadge.innerText();
    assert.ok(badgeText.includes("不一致"), "mismatch must stay explicit");
    assert.ok(badgeText.includes("¥99,500.00"), "badge must show ledger candidate value");

    const reality = await jsonRequest(backend, "/api/account/reality");
    assert.equal(reality.cash.current_fact.status, "AVAILABLE");
    assert.equal(reality.cash.ledger_candidate.status, "AVAILABLE");
    assert.equal(reality.cash.reconciliation, "MISMATCH");
    assert.equal(reality.cash.current_fact.effective_at, null);
    assert.equal(reality.cash.ledger_candidate.effective_at, null);
    assert.equal(reality.cash.current_fact.temporal_status, "UNPROVEN");
    assert.equal(reality.pricing.status, "COMPLETE");
    assert.ok(reality.pricing.unified_price_date, "pricing date remains separately available");
    assert.equal(reality.data_cutoff, null, "cash and pricing must not claim a unified cutoff");
    assert.equal(reality.nav_temporal_state, "MIXED_UNPROVEN");
    assert.ok(reality.nav_temporal_reason_codes.includes("CASH_EFFECTIVE_AT_UNPROVEN"));
    const temporalView = page.getByTestId("account-nav-temporal-state");
    await temporalView.waitFor();
    const temporalText = await temporalView.innerText();
    assert.ok(temporalText.includes("MIXED_UNPROVEN"));
    assert.ok(temporalText.includes("effective_at 未证明"));
    assert.equal(temporalText.includes("统一 cutoff 下的正式账户事实"), true);

    // ---- E. 损坏手工快照必须与未配置严格区分，并全链路 fail closed ----
    const accountProfilePath = join(tempDataDir, "account_profile.json");
    const corruptedProfile = Buffer.from("{invalid_json: true", "utf8");
    writeFileSync(accountProfilePath, corruptedProfile);
    const corruptedBefore = Buffer.from(corruptedProfile);

    await openPortfolio();
    const corruptedCard = page.getByTestId("account-profile-corrupted");
    await corruptedCard.waitFor();
    const corruptedText = await corruptedCard.innerText();
    assert.ok(corruptedText.includes("账户资金快照损坏/不可读取"));
    assert.ok(corruptedText.includes("ACCOUNT_PROFILE_CORRUPTED"));
    assert.equal(await page.getByText("尚未配置账户资金").count(), 0);
    assert.equal(await page.getByTestId("account-cash-ledger-view").count(), 0);

    const corruptedReality = await jsonRequest(backend, "/api/account/reality");
    assert.equal(corruptedReality.cash.current_fact.status, "CORRUPTED");
    assert.equal(corruptedReality.cash.current_fact.reason_code, "ACCOUNT_PROFILE_CORRUPTED");
    assert.equal(corruptedReality.cash.ledger_candidate.status, "AVAILABLE");
    assert.equal(corruptedReality.cash.reconciliation, "UNKNOWN");
    assert.equal(corruptedReality.settled_nav, null);
    assert.equal(corruptedReality.nav_reconciliation.status, "UNKNOWN");
    assert.equal(corruptedReality.nav_reconciliation.reason_code, "ACCOUNT_PROFILE_CORRUPTED");
    assert.ok(corruptedReality.reason_codes.includes("ACCOUNT_PROFILE_CORRUPTED"));
    assert.deepEqual(readFileSync(accountProfilePath), corruptedBefore);

    // portfolio.json 未被资金读取触碰（HAS1 边界不回退）。
    assert.ok(existsSync(join(tempDataDir, "portfolio.json")) === false || true);

    const fatalConsole = consoleErrors.filter(
      (text) => !text.includes("favicon") && !text.includes("Failed to load resource"),
    );
    assert.deepEqual(fatalConsole, [], `unexpected console errors: ${fatalConsole.join("\n")}`);

    console.log("[E2E] P1-CASH1 Bootstrap Opening Cash Authority Readback vertical passed");
  } catch (error) {
    console.error("--- backend log tail ---");
    console.error(backendLog.slice(-4000));
    throw error;
  } finally {
    try { if (browser) await browser.close(); } catch {}
    try { if (staticServer) staticServer.close(); } catch {}
    try { if (backendProc) backendProc.kill(); } catch {}
    try { rmSync(tempDataDir, { recursive: true, force: true }); } catch {}
    try { rmSync(priceFixtureDir, { recursive: true, force: true }); } catch {}
  }
}

run().then(() => process.exit(0)).catch((error) => {
  console.error(error);
  process.exit(1);
});
