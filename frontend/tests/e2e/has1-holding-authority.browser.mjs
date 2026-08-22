/**
 * P1-HAS1 real Chromium vertical: Holding Authority Switchover & Single-Writer Closure.
 *
 * Proves on the real FastAPI + built-frontend surface, inside an isolated data dir:
 * A  pre-bootstrap legacy Portfolio contract works;
 * B  canonical bootstrap succeeds;
 * C  post-bootstrap /portfolio reads ledger-derived positions;
 * D  Decision Inbox reads the same canonical holdings;
 * E  both surfaces agree on security/quantity/cost;
 * F  a new Trade propagates to both surfaces;
 * G  a Position Correction propagates to both surfaces;
 * H  post-bootstrap legacy Holding CRUD cannot create a second truth (409 + hidden UI);
 * I  a deliberate portfolio.json mismatch stays explicit and untouched;
 * J  portfolio.json is preserved;
 * K  everything runs in an isolated temp dir (no real user data).
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
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
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before HAS1 browser vertical");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-has1-holding-authority-e2e-"));
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
          body: JSON.stringify({ detail: "HAS1 E2E backend proxy failed", error: String(error) }),
        });
      }
    });

    const openPortfolio = async () => {
      await page.goto(`${frontend}/portfolio`, { waitUntil: "networkidle" });
      await page.getByTestId("portfolio-authority-banner").waitFor();
      return page.getByTestId("portfolio-authority-banner");
    };

    // ---- A. pre-bootstrap legacy contract --------------------------------
    const preApi = await jsonRequest(backend, "/api/portfolio");
    assert.equal(preApi.holding_authority, "LEGACY_PORTFOLIO");

    let banner = await openPortfolio();
    assert.equal(await banner.getAttribute("data-authority"), "LEGACY_PORTFOLIO");
    assert.ok(await page.getByText("添加持仓").count() >= 1, "pre-bootstrap add form must be visible");

    // 定位包含「添加持仓」标题的最内层卡片，避免与清仓表单的同名占位符冲突。
    const addCard = page
      .locator('div:has(h3:text-is("添加持仓"))')
      .last();
    await addCard.locator('input[placeholder="6 位代码"]').fill("600519");
    await addCard.locator('input[placeholder="如 100"]').fill("100");
    await addCard.locator('input[placeholder="如 12.5，可负"]').fill("8");
    await page.getByRole("button", { name: "添加", exact: true }).click();
    await page.locator("table tbody tr").first().waitFor();
    assert.ok(await page.getByText("600519").first().isVisible());

    // ---- B. canonical bootstrap ------------------------------------------
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      note: "HAS1 vertical bootstrap",
      positions: [{ code: "600519", shares: 100, cost_basis: 8 }],
    });

    // ---- C. post-bootstrap /portfolio reads canonical positions ----------
    // Simulate an empty legacy archive after bootstrap: the ledger remains the
    // current authority and the empty archive is only reconciliation evidence.
    const pfFile = join(tempDataDir, "portfolio.json");
    writeFileSync(pfFile, JSON.stringify({ holdings: [], last_refresh: null }), "utf-8");
    banner = await openPortfolio();
    assert.equal(await banner.getAttribute("data-authority"), "LEDGER_DERIVED");
    const missingInArchiveBanner = page.getByTestId("portfolio-mismatch-banner");
    await missingInArchiveBanner.waitFor();
    assert.equal(await missingInArchiveBanner.getAttribute("data-reconciliation"), "LEGACY_ARCHIVE_DIVERGENCE");
    const missingInArchiveText = await missingInArchiveBanner.innerText();
    assert.ok(missingInArchiveText.includes("MISSING_IN_PORTFOLIO"));
    assert.ok(missingInArchiveText.includes("Legacy archive"));
    assert.ok(missingInArchiveText.includes("Position Ledger 是 post-bootstrap 的当前持仓事实"));
    assert.equal(missingInArchiveText.includes("持仓对账不一致"), false);
    assert.equal(missingInArchiveText.includes("为了消除 archive 差异"), true);
    assert.ok((await page.locator("table tbody tr").first().innerText()).includes("600519"));
    assert.equal(missingInArchiveText.includes("自动写入"), true);
    assert.equal(await page.getByTestId("portfolio-legacy-entry-disabled").count(), 1);
    assert.equal(
      await page.getByRole("heading", { name: "添加持仓" }).count(),
      0,
      "legacy add form heading must be hidden post-bootstrap",
    );
    const row = page.locator("table tbody tr").first();
    await row.waitFor();
    assert.ok((await row.innerText()).includes("600519"));

    // ---- D/E. Decision Inbox reads the same canonical holdings -----------
    const inboxSnapshot = await jsonRequest(backend, "/api/decision-inbox");
    assert.equal(inboxSnapshot.canonical, true);
    assert.equal(inboxSnapshot.total_holdings, 1);
    assert.equal(inboxSnapshot.holding_setup_items.length, 1);
    const setupItem = inboxSnapshot.holding_setup_items[0];
    assert.equal(setupItem.security_code, "600519");
    const inboxShares = Number(setupItem.holding?.shares ?? setupItem.holding?.quantity);
    const portfolioApi = await jsonRequest(backend, "/api/portfolio");
    assert.equal(portfolioApi.holding_authority, "LEDGER_DERIVED");
    assert.equal(portfolioApi.holdings.length, 1);
    assert.equal(portfolioApi.holdings[0].code, setupItem.security_code);
    assert.equal(Number(portfolioApi.holdings[0].shares), inboxShares);

    await page.goto(`${frontend}/decision-inbox`, { waitUntil: "networkidle" });
    await page.getByText("待建立 Campaign 的持仓").waitFor();
    assert.ok(await page.getByText("600519").first().isVisible());

    // ---- F. trade propagation to both surfaces ---------------------------
    await jsonRequest(backend, "/api/trades", "POST", {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "full",
      actual_price: 10,
      actual_quantity: 50,
      executed_at: "2026-08-05T10:00:00Z",
    });

    const afterTradePortfolio = await jsonRequest(backend, "/api/portfolio");
    assert.equal(afterTradePortfolio.holdings[0].shares, 150);
    const afterTradeInbox = await jsonRequest(backend, "/api/decision-inbox");
    const afterTradeInboxShares = Number(
      afterTradeInbox.holding_setup_items[0].holding?.shares
        ?? afterTradeInbox.holding_setup_items[0].holding?.quantity
    );
    assert.equal(afterTradeInbox.total_holdings, 1);
    assert.equal(afterTradeInboxShares, 150);

    // ---- G. correction propagation to both surfaces ----------------------
    const tradesList = await jsonRequest(backend, "/api/trades?code=600519");
    const tradeId = tradesList.items?.[0]?.trade_id ?? tradesList[0]?.trade_id;
    assert.ok(tradeId, "created trade must be listable");
    await jsonRequest(backend, `/api/position/correction`, "POST", {
      target_event_type: "trade",
      target_event_id: tradeId,
      after_payload: { actual_quantity: 80 },
      reason: "HAS1 vertical correction",
    });

    const afterCorrectionPortfolio = await jsonRequest(backend, "/api/portfolio");
    assert.equal(afterCorrectionPortfolio.holdings[0].shares, 180);
    const afterCorrectionInbox = await jsonRequest(backend, "/api/decision-inbox");
    const afterCorrectionInboxShares = Number(
      afterCorrectionInbox.holding_setup_items[0].holding?.shares
        ?? afterCorrectionInbox.holding_setup_items[0].holding?.quantity
    );
    assert.equal(afterCorrectionInboxShares, 180);

    // ---- H. legacy CRUD cannot create a second truth ---------------------
    banner = await openPortfolio();
    assert.equal(await banner.getAttribute("data-authority"), "LEDGER_DERIVED");
    const blockedStatus = await page.evaluate(async () => {
      const response = await fetch("/api/portfolio/holding", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: "000001", shares: 7, cost: 7 }),
      });
      return response.status;
    });
    assert.equal(blockedStatus, 409, "post-bootstrap legacy mutation must fail closed");
    assert.equal(await page.getByTestId("portfolio-legacy-entry-disabled").count(), 1);
    const canonicalRow = page.locator("table tbody tr").first();
    await canonicalRow.waitFor();
    assert.ok((await canonicalRow.innerText()).includes("600519"));
    assert.ok((await canonicalRow.innerText()).includes("180"));

    const stillCanonical = await jsonRequest(backend, "/api/portfolio");
    assert.equal(stillCanonical.holdings.length, 1);
    assert.equal(stillCanonical.holdings[0].code, "600519");

    // ---- I/J. deliberate mismatch stays explicit; file preserved ---------
    assert.ok(existsSync(pfFile), "J: portfolio.json must be preserved");
    writeFileSync(
      pfFile,
      JSON.stringify({
        holdings: [
          { code: "600519", shares: 999, cost: 1 },
          { code: "000001", shares: 20, cost: 12 },
        ],
        last_refresh: null,
      }),
      "utf-8",
    );

    banner = await openPortfolio();
    assert.equal(await banner.getAttribute("data-authority"), "LEDGER_DERIVED");
    const mismatchBanner = page.getByTestId("portfolio-mismatch-banner");
    await mismatchBanner.waitFor();
    assert.equal(await mismatchBanner.getAttribute("data-reconciliation"), "LEGACY_ARCHIVE_DIVERGENCE");
    const mismatchText = await mismatchBanner.innerText();
    assert.ok(mismatchText.includes("600519"));
    assert.ok(mismatchText.includes("000001"));
    assert.ok(mismatchText.includes("MISSING_IN_LEDGER"));
    assert.ok(mismatchText.includes("MISMATCH"));
    assert.ok(mismatchText.includes("Ledger 180 股"));
    assert.ok(mismatchText.includes("archive 999 股"));
    assert.equal(mismatchText.includes("持仓对账不一致"), false);
    assert.equal(mismatchText.includes("不要为了消除 archive 差异而修改当前账本"), true);

    const mismatchView = await jsonRequest(backend, "/api/portfolio");
    assert.equal(mismatchView.holdings[0].shares, 180, "display must stay canonical despite mismatch");
    assert.ok(mismatchView.ledger_view.reconciliation.summary.mismatch >= 1);
    assert.ok(existsSync(pfFile), "J: portfolio.json still preserved after mismatch read");

    // ---- K. isolation sanity ---------------------------------------------
    assert.equal(readdirSync(tempDataDir).some((name) => /queue|second.*store|holding-store/i.test(name)), false);

    const fatalConsole = consoleErrors.filter(
      (text) => !text.includes("favicon") && !text.includes("Failed to load resource"),
    );
    assert.deepEqual(fatalConsole, [], `unexpected console errors: ${fatalConsole.join("\n")}`);

    console.log("[E2E] P1-HAS1 Holding Authority Switchover vertical passed");
  } catch (error) {
    console.error("--- backend log tail ---");
    console.error(backendLog.slice(-4000));
    throw error;
  } finally {
    try { if (browser) await browser.close(); } catch {}
    try { if (staticServer) staticServer.close(); } catch {}
    try { if (backendProc) backendProc.kill(); } catch {}
    try { rmSync(tempDataDir, { recursive: true, force: true }); } catch {}
  }
}

run().then(() => process.exit(0)).catch((error) => {
  console.error(error);
  process.exit(1);
});
