/**
 * Intel Daily Digest v0.1 — Real Backend & Playwright Browser E2E Test
 */

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, readdirSync, createReadStream } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import path from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try { const r = await fetch(url); if (r.ok || r.status < 500) return r; } catch { }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2",
  };
  const server = createServer((req, res) => {
    let pn = (req.url || "/").split("?")[0];
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
    const rd = path.resolve(dir);
    const rt = path.resolve(target);
    if (!rt.startsWith(rd + path.sep) && rt !== rd) { res.writeHead(403); res.end("forbidden"); return; }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    const ext = path.extname(target);
    res.setHeader("Content-Type", mime[ext] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function findChromium() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of candidates) {
    if (!base || !existsSync(base)) continue;
    try {
      for (const d of readdirSync(base)) {
        if (d.startsWith("chromium-") && !d.includes("headless")) {
          const exe = join(base, d, "chrome-win64", "chrome.exe");
          if (existsSync(exe)) { console.log(`[E2E] Chromium: ${d}`); return exe; }
        }
      }
    } catch { }
  }
  return undefined;
}

function getPythonConfig() {
  const envPy = process.env.PYTHON;
  if (envPy) return { cmd: envPy, extraArgs: ["-m", "uvicorn"] };
  const isWin = process.platform === "win32";
  return isWin
    ? { cmd: "py", extraArgs: ["-3", "-m", "uvicorn"] }
    : { cmd: "python3", extraArgs: ["-m", "uvicorn"] };
}

async function main() {
  console.log("=== Running Intel Digest Real Backend E2E Test ===");

  const tmpDataDir = mkdtempSync(join(tmpdir(), "vr-intel-e2e-data-"));
  const tmpReportsDir = mkdtempSync(join(tmpdir(), "vr-intel-e2e-reports-"));

  const backendPort = await getFreePort();
  const frontendPort = await getFreePort();

  const staticServer = await startStaticServer(frontendDist, frontendPort);
  console.log(`Static server running at http://127.0.0.1:${frontendPort}`);

  const py = getPythonConfig();
  const pyEnv = {
    ...process.env,
    VR_DATA_DIR: tmpDataDir,
    VR_REPORTS_DIR: tmpReportsDir,
    PYTHONPATH: `${backendDir}${path.delimiter}${process.env.PYTHONPATH || ""}`,
  };

  const backendProc = spawn(
    py.cmd,
    [...py.extraArgs, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
    { cwd: backendDir, env: pyEnv, stdio: ["ignore", "pipe", "pipe"] }
  );

  let backendErrLog = "";
  backendProc.stderr.on("data", (d) => {
    backendErrLog += d.toString();
    process.stderr.write(`[backend] ${d}`);
  });
  backendProc.stdout.on("data", (d) => {
    backendErrLog += d.toString();
    process.stdout.write(`[backend] ${d}`);
  });

  try {
    try {
      await waitHttp(`http://127.0.0.1:${backendPort}/api/intel-digests/latest?sector_key=ai`, 60);
    } catch (e) {
      console.error("Backend failed to start. Logs:\n", backendErrLog);
      throw e;
    }
    console.log(`Backend server running at http://127.0.0.1:${backendPort}`);

    const browser = await chromium.launch({ headless: true, executablePath: findChromium() });
    const context = await browser.newContext();
    const page = await context.newPage();

    page.on("console", (msg) => console.log(`[page console] ${msg.type()}: ${msg.text()}`));
    page.on("pageerror", (err) => console.error("[page error]", err));

    // 1. Fallback route proxy for all other /api/** calls to real FastAPI backend
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = request.url().replace(`http://127.0.0.1:${frontendPort}`, `http://127.0.0.1:${backendPort}`);
      try {
        const response = await fetch(url, {
          method: request.method(),
          headers: request.headers(),
          body: request.postDataBuffer(),
        });
        const headers = {};
        response.headers.forEach((v, k) => { headers[k] = v; });
        const body = Buffer.from(await response.arrayBuffer());
        await route.fulfill({ status: response.status, headers, body });
      } catch (err) {
        await route.abort();
      }
    });

    // 2. Mock /api/radar so InvestmentNewsPanel has industries data immediately
    await page.route("**/api/radar", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          generated_at: "2026-07-31 10:00:00",
          recent_days: 7,
          stats: { total_sources: 12 },
          industries: [
            {
              key: "ai",
              name: "AI 人工智能",
              accent: "#f97316",
              items: [
                { title: "AI Chip Innovation Announced", zh: "AI 芯片重大突破发布", source: "TechCrunch", time: "2026-07-31", url: "https://example.com/ai-chip" }
              ]
            }
          ]
        })
      });
    });

    // 3. Mock /api/chat to return successful NDJSON stream
    await page.route("**/api/chat", async (route) => {
      const streamData = [
        JSON.stringify({ type: "delta", text: "- 今日 AI 芯片重大突破" }),
        JSON.stringify({ type: "done", trace: [], rounds: 1 })
      ].join("\n") + "\n";
      await route.fulfill({
        status: 200,
        contentType: "application/x-ndjson",
        body: streamData,
      });
    });

    let saveCallCount = 0;
    page.on("request", (req) => {
      if (req.url().includes("/api/intel-digests") && req.method() === "POST") {
        saveCallCount++;
      }
    });

    // Set LLM config in localStorage before navigating
    await page.goto(`http://127.0.0.1:${frontendPort}/intel`);
    await page.evaluate(() => {
      localStorage.setItem("vr-llm", JSON.stringify({ provider: "api-compatible", baseURL: "http://mock", apiKey: "mock", model: "mock-model" }));
    });
    await page.reload();

    // 2. Click generate digest
    const genButton = page.locator("button:has-text('让 AI 提炼今日要点')");
    await genButton.waitFor({ state: "visible" });
    await genButton.click();

    // 3. Verify saved badge appears & save POST call occurred
    await page.waitForSelector("span:has-text('已保存')");
    console.log("✓ Stream complete, saved badge visible");
    if (saveCallCount !== 1) throw new Error(`Expected 1 save POST call, got ${saveCallCount}`);

    // 4. Click regenerate -> verify deduped badge appears
    const regenButton = page.locator("button:has-text('重新提炼')");
    await regenButton.click();
    await page.waitForSelector("span:has-text('已去重')");
    console.log("✓ Deduplicated badge visible on re-generate");
    if (saveCallCount !== 2) throw new Error(`Expected 2 save POST calls, got ${saveCallCount}`);

    // 5. Test interrupted stream does NOT call POST save
    await page.route("**/api/chat", async (route) => {
      await route.abort(); // simulate network break
    });

    const preFailSaveCount = saveCallCount;
    await regenButton.click();
    await page.waitForTimeout(500);
    if (saveCallCount !== preFailSaveCount) {
      throw new Error("Failed stream should NOT trigger POST save!");
    }
    console.log("✓ Failed stream correctly avoided POST save");

    // 6. Refresh page -> verify reads latest digest from API on load
    await page.reload();
    await page.waitForSelector("text=今日 AI 芯片重大突破");
    await page.waitForSelector("span:has-text('已保存')");
    console.log("✓ Page reload successfully loaded latest digest from API");

    await browser.close();
    console.log("=== All E2E assertions passed successfully ===");
  } finally {
    if (backendProc) {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(backendProc.pid), "/t", "/f"], { stdio: "ignore" });
      } else {
        backendProc.kill("SIGKILL");
      }
    }
    if (staticServer) {
      staticServer.close();
    }
    await sleep(600);
    try { rmSync(tmpDataDir, { recursive: true, force: true }); } catch { }
    try { rmSync(tmpReportsDir, { recursive: true, force: true }); } catch { }
  }
}

main().catch((err) => {
  console.error("E2E Test Failed:", err);
  process.exit(1);
});
