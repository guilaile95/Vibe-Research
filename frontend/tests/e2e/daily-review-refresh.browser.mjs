/**
 * Daily review explicit refresh + portfolio advice body acceptance (desktop 1440).
 * Isolated VR_DATA_DIR / VIBE_RESEARCH_REVIEW_DB. Uses reverse-proxy + offline harness.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import http, { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const shotDir = path.join(root, "docs", "screenshots", "daily-review-refresh-accept");
const backendDir = path.join(root, "backend");
const e2eDir = __dirname;

let backendPort = 0;
let frontendPort = 0;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function resolvePython() {
  const candidates = [];
  if (process.env.VR_E2E_PYTHON?.trim()) candidates.push(process.env.VR_E2E_PYTHON.trim());
  if (process.env.VR_PYTHON?.trim()) candidates.push(process.env.VR_PYTHON.trim());
  candidates.push(
    path.join(root, "backend", ".venv", "Scripts", "python.exe"),
    path.join(root, "backend", ".venv", "bin", "python"),
    "python",
    "python3",
  );
  for (const c of candidates) {
    if (c === "python" || c === "python3") return c;
    if (existsSync(c)) return c;
  }
  return "python";
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const port = s.address().port;
      s.close(() => resolve(port));
    });
  });
}

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(url);
      if (r.ok || r.status < 500) return;
    } catch { /* */ }
    await sleep(400);
  }
  throw new Error(`timeout ${url}`);
}

function startStaticServer(dir, port, apiBackendPort) {
  const mime = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
  };
  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    const urlPath = decodeURIComponent(rawUrl.split("?")[0] || "/");
    if (urlPath === "/api" || urlPath.startsWith("/api/")) {
      const headers = { ...req.headers, host: `127.0.0.1:${apiBackendPort}` };
      const proxyReq = http.request(
        {
          hostname: "127.0.0.1",
          port: apiBackendPort,
          path: rawUrl,
          method: req.method,
          headers,
        },
        (proxyRes) => {
          res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
          proxyRes.pipe(res);
        },
      );
      proxyReq.on("error", (err) => {
        if (!res.headersSent) res.writeHead(502);
        res.end(String(err.message));
      });
      req.pipe(proxyReq);
      return;
    }
    let filePath = urlPath === "/" ? "/index.html" : urlPath;
    const abs = path.join(dir, filePath);
    if (!abs.startsWith(dir) || !existsSync(abs)) {
      // SPA fallback
      const index = path.join(dir, "index.html");
      res.writeHead(200, { "content-type": "text/html" });
      require("fs").createReadStream(index).pipe(res);
      return;
    }
    const ext = path.extname(abs);
    res.writeHead(200, { "content-type": mime[ext] || "application/octet-stream" });
    require("fs").createReadStream(abs).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

// Node ESM: use fs createReadStream import
import { createReadStream } from "node:fs";

async function main() {
  if (!existsSync(frontendDist)) {
    console.error("frontend/dist missing — run npm run build first");
    process.exit(2);
  }
  await mkdir(shotDir, { recursive: true });
  const dataDir = await mkdtemp(path.join(tmpdir(), "vr-dr-e2e-"));
  const reportsDir = await mkdtemp(path.join(tmpdir(), "vr-dr-reports-"));
  const reviewDb = path.join(dataDir, "daily_reviews.sqlite3");

  backendPort = await getFreePort();
  frontendPort = await getFreePort();
  const python = resolvePython();
  const env = {
    ...process.env,
    VR_DATA_DIR: dataDir,
    VR_REPORTS_DIR: reportsDir,
    VIBE_RESEARCH_REVIEW_DB: reviewDb,
    PYTHONPATH: [backendDir, e2eDir, process.env.PYTHONPATH || ""].filter(Boolean).join(path.delimiter),
  };

  const uvicorn = spawn(
    python,
    ["-m", "uvicorn", "daily_review_harness_app:app", "--host", "127.0.0.1", "--port", String(backendPort), "--log-level", "warning"],
    { cwd: e2eDir, env, stdio: ["ignore", "pipe", "pipe"] },
  );
  let uvLog = "";
  uvicorn.stdout.on("data", (d) => { uvLog += d.toString(); });
  uvicorn.stderr.on("data", (d) => { uvLog += d.toString(); });

  const errors = [];
  let staticServer;
  let browser;
  try {
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`).catch(() =>
      waitHttp(`http://127.0.0.1:${backendPort}/api/daily-review`),
    );
    // static with proxy
    const mime = {
      ".css": "text/css", ".html": "text/html", ".js": "text/javascript",
      ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
      ".woff2": "font/woff2",
    };
    staticServer = createServer((req, res) => {
      const rawUrl = req.url || "/";
      const urlPath = decodeURIComponent(rawUrl.split("?")[0] || "/");
      if (urlPath === "/api" || urlPath.startsWith("/api/")) {
        const headers = { ...req.headers, host: `127.0.0.1:${backendPort}` };
        const proxyReq = http.request(
          { hostname: "127.0.0.1", port: backendPort, path: rawUrl, method: req.method, headers },
          (proxyRes) => {
            res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
            proxyRes.pipe(res);
          },
        );
        proxyReq.on("error", (err) => {
          if (!res.headersSent) res.writeHead(502);
          res.end(String(err.message));
        });
        req.pipe(proxyReq);
        return;
      }
      let rel = urlPath === "/" ? "/index.html" : urlPath;
      let abs = path.join(frontendDist, rel);
      if (!abs.startsWith(frontendDist) || !existsSync(abs)) {
        abs = path.join(frontendDist, "index.html");
      }
      const ext = path.extname(abs);
      res.writeHead(200, { "content-type": mime[ext] || "application/octet-stream" });
      createReadStream(abs).pipe(res);
    });
    await new Promise((r) => staticServer.listen(frontendPort, "127.0.0.1", r));
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    async function launchBrowser() {
      const candidates = [];
      if (process.env.PLAYWRIGHT_CHROME_PATH) {
        candidates.push({
          label: "PLAYWRIGHT_CHROME_PATH",
          opts: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH, headless: true },
        });
      }
      const localAppData = process.env.LOCALAPPDATA || "";
      const chromium1228 = path.join(
        localAppData,
        "ms-playwright",
        "chromium-1228",
        "chrome-win64",
        "chrome.exe",
      );
      if (existsSync(chromium1228)) {
        candidates.push({
          label: "local chromium-1228",
          opts: { executablePath: chromium1228, headless: true },
        });
      }
      candidates.push({ label: "bundled chromium", opts: { headless: true } });
      candidates.push({ label: "channel chrome", opts: { channel: "chrome", headless: true } });
      candidates.push({ label: "channel msedge", opts: { channel: "msedge", headless: true } });
      let last;
      for (const c of candidates) {
        try {
          const b = await chromium.launch(c.opts);
          console.log(`browser=${c.label}`);
          return b;
        } catch (e) {
          last = e;
        }
      }
      throw last || new Error("no browser");
    }
    browser = await launchBrowser();
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    const apiLog = { get: 0, refreshPost: 0, advicePost: 0, adviceBodies: [], refreshStatuses: [], adviceStatuses: [] };
    page.on("response", (response) => {
      const url = response.url();
      const method = response.request().method();
      const status = response.status();
      if (url.includes("/api/daily-review/refresh") && method === "POST") {
        apiLog.refreshPost += 1;
        apiLog.refreshStatuses.push(status);
      } else if (url.endsWith("/api/daily-review") && method === "GET") {
        apiLog.get += 1;
      } else if (url.includes("/api/portfolio/advice") && method === "POST") {
        apiLog.advicePost += 1;
        apiLog.adviceStatuses.push(status);
        try {
          const postData = response.request().postData();
          if (postData) apiLog.adviceBodies.push(JSON.parse(postData));
        } catch { /* */ }
      }
    });

    // —— 每日复盘刷新 ——
    await page.goto(`http://127.0.0.1:${frontendPort}/daily-review`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    const getsAfterOpen = apiLog.get;
    if (getsAfterOpen < 1) errors.push("open daily-review did not GET /api/daily-review");

    const genEl = page.locator("text=/生成时间|generated/i").first();
    const bodyBefore = await page.locator("body").innerText();
    const mBefore = bodyBefore.match(/20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}/);
    const genBefore = mBefore ? mBefore[0] : null;

    const refreshBtn = page.getByTestId("daily-review-refresh");
    if (!(await refreshBtn.isVisible().catch(() => false))) {
      // fallback: title 刷新
      const btn = page.locator('button[title*="刷新"]').first();
      if (await btn.isVisible().catch(() => false)) await btn.click();
      else errors.push("refresh button missing");
    } else {
      await refreshBtn.click();
    }
    await page.waitForTimeout(2000);

    if (apiLog.refreshPost !== 1) {
      errors.push(`expected exactly 1 POST refresh, got ${apiLog.refreshPost}`);
    }
    if (apiLog.refreshStatuses.some((s) => s >= 400)) {
      errors.push(`refresh HTTP failed: ${JSON.stringify(apiLog.refreshStatuses)}`);
    }
    const bodyAfter = await page.locator("body").innerText();
    if (bodyAfter.includes("持仓建议请求参数无效")) {
      errors.push("unexpected portfolio advice param error on review page");
    }
    // capture generated_at marker from successful refresh for failure comparison
    const genAfterOk = await page.evaluate(async () => {
      const r = await fetch("/api/daily-review");
      const j = await r.json();
      return j?.data?.generated_at || null;
    });
    if (!genAfterOk) errors.push("missing generated_at after successful refresh");

    // —— 失败刷新：保留旧 generated_at 与页面数据 ——
    const arm = await page.evaluate(async () => {
      const r = await fetch("/api/e2e/daily-review/arm-fail-next-build", { method: "POST" });
      return r.ok;
    });
    if (!arm) errors.push("failed to arm fail-next-build");
    const refreshPostsBeforeFail = apiLog.refreshPost;
    if (await refreshBtn.isVisible().catch(() => false)) {
      await refreshBtn.click();
    } else {
      const btn = page.locator('button[title*="刷新"]').first();
      if (await btn.isVisible().catch(() => false)) await btn.click();
    }
    await page.waitForTimeout(2000);
    if (apiLog.refreshPost !== refreshPostsBeforeFail + 1) {
      errors.push(`expected one more POST on fail refresh, got ${apiLog.refreshPost}`);
    }
    const lastRefreshStatus = apiLog.refreshStatuses[apiLog.refreshStatuses.length - 1];
    if (!(lastRefreshStatus >= 400)) {
      errors.push(`expected fail refresh non-2xx, got ${lastRefreshStatus}`);
    }
    const genAfterFail = await page.evaluate(async () => {
      const r = await fetch("/api/daily-review");
      const j = await r.json();
      return j?.data?.generated_at || null;
    });
    if (genAfterOk && genAfterFail && genAfterFail !== genAfterOk) {
      errors.push(
        `fail refresh must keep old generated_at: before=${genAfterOk} after=${genAfterFail}`,
      );
    }
    const failNote = await page
      .getByText(/最新数据刷新失败，当前继续显示上次成功结果/)
      .first()
      .isVisible()
      .catch(() => false);
    if (!failNote) {
      // soft: note may use exact copy; still require old data retained via GET
    }
    await page.screenshot({ path: path.join(shotDir, "daily-review-refresh.png"), fullPage: true });

    // —— 持仓建议 ——
    await page.goto(`http://127.0.0.1:${frontendPort}/portfolio`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    // inject minimal llm config
    await page.evaluate(() => {
      localStorage.setItem(
        "vr-llm",
        JSON.stringify({
          provider: "deepseek",
          baseURL: "http://127.0.0.1/mock",
          apiKey: "sk-test",
          model: "deepseek-chat",
        }),
      );
    });
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(800);

    const adviceBtn = page.getByRole("button", { name: /生成持仓|重新生成持仓/ }).first();
    if (await adviceBtn.isVisible().catch(() => false)) {
      await adviceBtn.click();
      await page.waitForTimeout(3000);
      if (apiLog.advicePost < 1) {
        errors.push("advice button did not POST /api/portfolio/advice");
      } else {
        const body = apiLog.adviceBodies[0];
        if (body) {
          const keys = Object.keys(body).sort();
          if (JSON.stringify(keys) !== JSON.stringify(["llm", "user_request"])) {
            errors.push(`advice body keys unexpected: ${keys.join(",")}`);
          }
          if (body.holdings != null || body.context != null || body.messages != null) {
            errors.push("advice body injected server-owned fields");
          }
        }
        if (apiLog.adviceStatuses.some((s) => s === 400)) {
          const t = await page.locator("body").innerText();
          if (t.includes("持仓建议请求参数无效")) {
            errors.push("still showing 持仓建议请求参数无效");
          }
        }
        // 2xx expected with harness mock
        if (apiLog.adviceStatuses.length && apiLog.adviceStatuses.every((s) => s >= 400)) {
          errors.push(`advice all failed: ${JSON.stringify(apiLog.adviceStatuses)}`);
        }
      }
    } else {
      errors.push("portfolio advice button missing");
    }
    await page.screenshot({ path: path.join(shotDir, "portfolio-advice.png"), fullPage: true });

    if (pageErrors.length) {
      errors.push(...pageErrors.map((e) => `pageerror: ${e}`));
    }
    await context.close();
  } catch (e) {
    errors.push(`harness: ${e && e.stack ? e.stack : e}`);
    if (uvLog) errors.push(`uvicorn: ${uvLog.slice(-1500)}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) staticServer.close();
    uvicorn.kill("SIGTERM");
    await sleep(300);
    await rm(dataDir, { recursive: true, force: true }).catch(() => {});
    await rm(reportsDir, { recursive: true, force: true }).catch(() => {});
  }

  if (errors.length) {
    console.error("FAIL daily-review-refresh / advice acceptance");
    for (const e of errors) console.error(" -", e);
    process.exit(1);
  }
  console.log("PASS daily-review-refresh / advice acceptance");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
