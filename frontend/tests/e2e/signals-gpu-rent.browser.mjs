/**
 * P1-UPSYNC1 vertical: 产业信号 · GPU租金 on the real frontend.
 *
 * Proves on the built frontend + real backend (isolated data dir, offline):
 * A  GET /api/signals/gpu-rent serves the shipped seed snapshot with the full
 *    contract (spot/history/forward/how_to_read) — no network needed;
 * B  /signals renders the seed: trend chart, three spot cards, forward months,
 *    and the 口径 how-to-read list;
 * C  refresh with a partial-failure payload renders the stale badge + errors
 *    panel (fail-loud semantics visible in UI), success keeps rendering;
 * D  the AI tool contract (query_gpu_rent summary shape) holds against the
 *    same backend module — the data behind the page is what AI reads.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
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

function pythonCmd() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venvPython = process.platform === "win32"
    ? join(backendDir, ".venv", "Scripts", "python.exe")
    : join(backendDir, ".venv", "bin", "python");
  if (existsSync(venvPython)) return venvPython;
  if (process.platform === "win32") return "py";
  return "python3";
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
    createReadStreamSafe(target, response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function createReadStreamSafe(target, response) {
  import("node:fs").then(({ createReadStream }) => {
    createReadStream(target).pipe(response);
  });
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before signals vertical");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-signals-e2e-"));
  let backendProc;
  let staticServer;
  let browser;
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
      VR_ALLOW_ORIGINS: frontend,
      PYTHONUNBUFFERED: "1",
    };
    backendProc = spawn(py.cmd, [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    await waitHttp(`${backend}/api/health`);

    // ---- A. seed snapshot served through the real API ----------------------
    const health = await (await fetch(`${backend}/api/health`)).json();
    assert.equal(health.ok, true);
    const seedEnvelope = await (await fetch(`${backend}/api/signals/gpu-rent`)).json();
    const seed = seedEnvelope.data;
    assert.equal(seed.schema, 4, "seed schema version");
    assert.ok(seed.generated_at, "seed generated_at present");
    assert.deepEqual(
      seed.spot.gpus.map((g) => g.gpu),
      ["B200", "H100 SXM", "A100 SXM4"],
    );
    assert.ok(seed.history.gpus.every((g) => (g.points || []).length > 300), "seed history series present");
    assert.ok((seed.forward?.months || []).length >= 10, "seed forward months present");
    assert.equal(seed.how_to_read.length, 4, "口径说明齐全");

    // ---- D. AI tool contract against the same backend module ---------------
    const toolOut = JSON.parse(
      execFileSync(
        pythonCmd(),
        ["-c", "import json,ai_tools; print(json.dumps(ai_tools.exec_tool('query_gpu_rent', {}), ensure_ascii=False))"],
        { cwd: backendDir, env, encoding: "utf8" },
      ),
    );
    assert.equal(toolOut.generated_at, seed.generated_at, "tool reads the same snapshot as the page");
    assert.ok(Array.isArray(toolOut.history_summary) && toolOut.history_summary.length === 3);
    const histRow = toolOut.history_summary.find((g) => g.gpu === "B200");
    assert.ok(histRow.latest && typeof histRow.latest.usd_per_gpu_hr === "number");
    assert.ok(Array.isArray(toolOut.forward.months));
    assert.ok("stale" in toolOut.forward && "observed_at" in toolOut.forward, "freshness metadata carried");

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const context = await browser.newContext();
    const page = await context.newPage();

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
      } catch {
        await route.fulfill({ status: 599, contentType: "application/json", body: JSON.stringify({ detail: "proxy failed" }) });
      }
    });

    await page.goto(`${frontend}/signals`, { waitUntil: "domcontentloaded" });

    // ---- B. seed renders ----------------------------------------------------
    await page.getByText("近一年租金走势 · 每日中位价").waitFor({ timeout: 30000 });
    await page.getByText("现货租金 · 最新观测值").waitFor();
    await page.getByText("远期 · 全球资金的预期概率（仅 B200）").waitFor();
    await page.getByText("怎么读这组数（三条口径边界）").waitFor();
    const b200Label = page.getByText("B200", { exact: true }).first();
    await b200Label.waitFor({ timeout: 15000 });
    const medianCards = await page.getByText("/卡·时（中位）").count();
    assert.equal(medianCards, 3, `three spot median cards rendered (${medianCards})`);
    const monthButtons = await page.getByRole("button", { name: /^\d{4}-\d{2}$/ }).count();
    assert.ok(monthButtons >= 10, `forward month buttons rendered (${monthButtons})`);
    // 图表 canvas 真实渲染（ECharts）
    await page.locator("canvas").first().waitFor({ timeout: 15000 });
    assert.ok((await page.locator("canvas").count()) >= 2, "trend + forward charts mounted");

    // ---- C. refresh states ---------------------------------------------------
    const stalePayload = JSON.parse(JSON.stringify(seedEnvelope));
    stalePayload.data.errors = ["500.farm H100 SXM: HTTP 503"];
    const h100Spot = stalePayload.data.spot.gpus.find((g) => g.gpu === "H100 SXM");
    h100Spot.stale = true;
    h100Spot.fetch_error = "HTTP 503";
    h100Spot.observed_at = seed.generated_at;
    const h100Hist = stalePayload.data.history.gpus.find((g) => g.gpu === "H100 SXM");
    h100Hist.stale = true;
    h100Hist.fetch_error = "HTTP 503";
    h100Hist.observed_at = seed.generated_at;
    stalePayload.data.forward.stale = true;
    stalePayload.data.forward.fetch_error = "HTTP 503";
    stalePayload.data.forward.observed_at = seed.generated_at;

    await page.route("**/api/signals/gpu-rent/refresh", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(stalePayload),
      });
    });

    await page.getByRole("button", { name: /^刷新$/ }).click();
    await page.getByText("本轮有数据源抓取失败（对应区块显示上一次的数据）：").waitFor({ timeout: 15000 });
    const staleBadges = await page.getByText("本轮抓取失败 · 显示").count();
    assert.ok(staleBadges >= 3, `stale badges on spot/history/forward (${staleBadges})`);
    await page.getByText(/500\.farm H100 SXM: HTTP 503/).waitFor();

    console.log("[E2E] Signals GPU-rent vertical passed");
  } finally {
    try { if (browser) await browser.close(); } catch { /* ignore */ }
    try { if (staticServer) staticServer.close(); } catch { /* ignore */ }
    if (backendProc) {
      backendProc.kill();
      await sleep(300);
      try { backendProc.kill("kill"); } catch { /* already gone */ }
    }
    try { rmSync(tempDataDir, { recursive: true, force: true }); } catch { /* ignore */ }
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
