/**
 * TREND-RADAR1 TR1-P1 vertical: /intel 「关注雷达」panel on the built frontend.
 *
 * Scenario 1 (REAL backend, gateway DISABLED): the panel must show the
 *   explicit disabled guidance and MUST NOT fabricate any hotlist rows.
 * Scenario 2 (trendradar_harness_app.py, fake gateway "ok"): status strip
 *   shows pinned upstream identity + server name; canned hotlist rows render
 *   with platform chips; trending probe section is interactive.
 * Scenario 3 (harness "down"): explicit UNAVAILABLE banner per envelope,
 *   still zero fabricated rows.
 */
import assert from "node:assert/strict";
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
function pythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: ["-m", "uvicorn"] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3", "-m", "uvicorn"] };
  return { cmd: "python3", args: ["-m", "uvicorn"] };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
      // starting up
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function startStaticServer(dir, port) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript" };
  const server = createServer((request, response) => {
    let pathname = (request.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    if (!existsSync(target)) target = path.join(dir, "index.html");
    response.setHeader(
      "Content-Type",
      mime[path.extname(target)] || "application/octet-stream",
    );
    import("node:fs").then(({ createReadStream }) => {
      createReadStream(target).pipe(response);
    });
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function chromiumPath() {
  const configured = process.env.PLAYWRIGHT_CHROMIUM_PATH;
  if (configured && existsSync(configured)) return configured;
  const bases = [
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of bases) {
    if (!base || !existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      if (!entry.startsWith("chromium-")) continue;
      for (const candidate of [
        join(base, entry, "chrome-win64", "chrome.exe"),
        join(base, entry, "chrome-linux", "chrome"),
      ]) {
        if (existsSync(candidate)) return candidate;
      }
    }
  }
  return undefined;
}

/** Run one harness scenario and drive assertions in a fresh page. */
async function runScenario({ label, spawnBackend, check }) {
  const tempDataDir = mkdtempSync(join(tmpdir(), `vr-tr-${label}-`));
  let backendProc;
  let staticServer;
  let browser;
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;

    backendProc = spawnBackend(backendPort, tempDataDir);
    await waitHttp(`${backend}/api/trendradar/status`);

    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();

    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      try {
        const response = await fetch(`${backend}${url.pathname}${url.search}`, {
          method: request.method(),
          headers: request.headers(),
          body:
            request.method() === "GET" || request.method() === "HEAD"
              ? undefined
              : request.postDataBuffer(),
        });
        await route.fulfill({
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          body: Buffer.from(await response.arrayBuffer()),
        });
      } catch {
        await route.fulfill({
          status: 599,
          contentType: "application/json",
          body: JSON.stringify({ detail: "proxy failed" }),
        });
      }
    });

    await page.goto(`${frontend}/intel`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /关注雷达/ }).click();
    await page.getByText("Sidecar 状态").waitFor({ timeout: 30000 });

    await check(page);

    console.log(`[E2E] TrendRadar ${label} scenario passed`);
  } finally {
    try {
      if (browser) await browser.close();
    } catch { /* ignore */ }
    try {
      if (staticServer) staticServer.close();
    } catch { /* ignore */ }
    if (backendProc) {
      backendProc.kill();
      await sleep(300);
      try {
        backendProc.kill("kill");
      } catch { /* already gone */ }
    }
    try {
      rmSync(tempDataDir, { recursive: true, force: true });
    } catch { /* ignore */ }
  }
}

function startRealBackend(port, tempDataDir) {
  const py = pythonConfig();
  return spawn(
    py.cmd,
    [...py.args, "app:app", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        VR_DATA_DIR: tempDataDir,
        VR_REPORTS_DIR: tempDataDir,
        PYTHONUNBUFFERED: "1",
        // 故意不设 VIBE_TRENDRADAR_MCP_URL → 默认 DISABLED 诚实路径
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
}

function startHarness(mode) {
  return (port, tempDataDir) => {
    const py = pythonConfig();
    return spawn(
      py.cmd,
      [
        ...py.args,
        "--app-dir",
        join(root, "frontend", "tests", "e2e"),
        "trendradar_harness_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        String(port),
      ],
      {
        cwd: backendDir,
        env: {
          ...process.env,
          PYTHONPATH: `${join(root, "backend")}${path.delimiter}${join(root, "frontend", "tests", "e2e")}`,
          VR_DATA_DIR: tempDataDir,
          TR_HARNESS_MODE: mode,
          PYTHONUNBUFFERED: "1",
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
  };
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built first");

  // ---- Scenario 1: real backend, default-DISABLED honesty -----------------
  await runScenario({
    label: "disabled-real-backend",
    spawnBackend: startRealBackend,
    check: async (page) => {
      await page.getByText(/sidecar 网关未启用/i).waitFor({ timeout: 20000 });
      await page.getByText(/雷达各区块依赖可用的 sidecar/).waitFor();
      const fakeRows = await page.getByText("FAKE 热榜").count();
      assert.equal(fakeRows, 0, "disabled state must not render fabricated rows");
    },
  });

  // ---- Scenario 2: harness OK — identity + rows + probe strip --------------
  await runScenario({
    label: "ok-harness",
    spawnBackend: startHarness("ok"),
    check: async (page) => {
      await page.getByText("trendradar-news").waitFor({ timeout: 20000 });
      await page.getByText(/8ee26026/).first().waitFor();
      await page.getByText("FAKE 热榜 甲 · 固态电池量产提速").waitFor({ timeout: 20000 });
      await page.getByText("微博").first().waitFor();
      await page.getByText("固态电池", { exact: false }).first().waitFor(); // 热点话题或探针区
      const placeholderProbe = await page.getByPlaceholder(/输入主题词/).count();
      assert.equal(placeholderProbe, 1, "topic probe input present");
    },
  });

  // ---- Scenario 3: harness down — explicit UNAVAILABLE, no rows ------------
  await runScenario({
    label: "unavailable-harness",
    spawnBackend: startHarness("down"),
    check: async (page) => {
      await page.getByText(/sidecar 不可达\/未安装客户端/).waitFor({ timeout: 20000 });
      const fakeRows = await page.getByText("FAKE 热榜").count();
      assert.equal(fakeRows, 0, "failure must not fabricate rows");
    },
  });

  console.log("[E2E] TrendRadar radar vertical passed (3 scenarios)");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
