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
  const bases = [process.env.PLAYWRIGHT_CHROMIUM_PATH, join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")];
  for (const base of bases) {
    if (!base || !existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [join(base, entry, "chrome-win64", "chrome.exe"), join(base, entry, "chrome-linux", "chrome"), join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium")];
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
    } catch {}
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function startStaticServer(dir, port) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" };
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
  return payload;
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before policy browser vertical");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-aep2-policy-e2e-"));
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
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VR_ALLOW_ORIGINS: frontend,
      PYTHONUNBUFFERED: "1",
    };
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);

    const policyPath = join(tempDataDir, "account_execution_policy.json");
    const configuredPolicy = {
      lot_size: 100,
      min_cash_reserve_pct: 0.1,
      max_single_stock_allocation_pct: 0.47,
      tie_breaker_order: "code_desc",
      allow_partial_execution: false,
    };
    writeFileSync(policyPath, JSON.stringify(configuredPolicy), "utf8");
    const initial = await jsonRequest(backend, "/api/account-execution-policy");
    assert.deepEqual(initial, { status: "configured", data: configuredPolicy, reason_code: null });

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
      const response = await fetch(`${backend}${url.pathname}${url.search}`, { method: request.method(), headers: request.headers(), body: ["GET", "HEAD"].includes(request.method()) ? undefined : request.postDataBuffer() });
      await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers.entries()), body: Buffer.from(await response.arrayBuffer()) });
    });

    await page.goto(`${frontend}/account-policy`, { waitUntil: "networkidle" });
    await page.getByTestId("account-execution-policy-configured").waitFor();
    assert.equal(await page.getByTestId("account-execution-policy-default").count(), 0);
    assert.equal(await page.getByTestId("account-execution-policy-corrupted").count(), 0);

    const maxAllocation = page.getByTestId("account-execution-policy-max-allocation-readonly");
    const tieBreaker = page.getByTestId("account-execution-policy-tie-breaker-readonly");
    const partialExecution = page.getByTestId("account-execution-policy-partial-execution-readonly");
    assert.equal(await maxAllocation.getAttribute("readonly"), "");
    assert.equal(await tieBreaker.isDisabled(), true);
    assert.equal(await partialExecution.isDisabled(), true);
    assert.ok((await page.locator("body").innerText()).includes("NOT_IMPLEMENTED"));
    assert.ok((await page.locator("body").innerText()).includes("当前仅保存该配置，尚未参与 runtime 仓位约束"));

    assert.equal(await page.locator("#lot_size").isEditable(), true);
    assert.equal(await page.locator("#min_cash_reserve_pct").isEditable(), true);
    assert.equal(await maxAllocation.inputValue(), "47");
    assert.equal(await tieBreaker.inputValue(), "code_desc");
    assert.equal(await partialExecution.isChecked(), false);

    await page.locator("#lot_size").fill("200");
    await page.getByRole("button", { name: "保存策略" }).click();
    await page.getByTestId("account-execution-policy-configured").waitFor();
    const saved = await jsonRequest(backend, "/api/account-execution-policy");
    assert.deepEqual(saved, {
      status: "configured",
      data: {
        ...configuredPolicy,
        lot_size: 200,
      },
      reason_code: null,
    });
    assert.equal(existsSync(`${policyPath}.tmp`), false);

    writeFileSync(policyPath, "{broken", "utf8");
    await page.reload({ waitUntil: "networkidle" });
    const corruptedCard = page.getByTestId("account-execution-policy-corrupted");
    await corruptedCard.waitFor();
    const corruptedText = await corruptedCard.innerText();
    assert.ok(corruptedText.includes("账户执行策略损坏/不可读取"));
    assert.ok(corruptedText.includes("ACCOUNT_EXECUTION_POLICY_CORRUPTED"));
    assert.equal(await page.getByTestId("account-execution-policy-default").count(), 0);
    assert.equal(readFileSync(policyPath, "utf8"), "{broken");

    const fatalConsole = consoleErrors.filter((text) => !text.includes("favicon") && !text.includes("Failed to load resource"));
    assert.deepEqual(fatalConsole, [], `unexpected console errors: ${fatalConsole.join("\n")}`);
    console.log("[E2E] P1-AEP2 effective policy surface vertical passed");
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

run().then(() => process.exit(0)).catch((error) => { console.error(error); process.exit(1); });
