/**
 * BK-11 短线市场历史 — 真实后端 E2E。
 * 禁止 mock /api/market/bk11-history 与 /api/data-health；
 * 仅拦截与本次测试无关的 /api/market/northbound（避免真实外部请求）。
 * 所有 fixture 位于临时目录；零外部请求。
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
  createReadStream,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer, request as httpRequest } from "node:http";
import path from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitHttp(url, attempts = 100) {
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(url);
      if (r.ok || r.status < 500) return r;
    } catch {
      /* retry */
    }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
}

function getPythonConfig() {
  const envPy = process.env.PYTHON;
  if (envPy) return { cmd: envPy, extraArgs: ["-m", "uvicorn"] };
  const isWin = process.platform === "win32";
  return isWin
    ? { cmd: "py", extraArgs: ["-3", "-m", "uvicorn"] }
    : { cmd: "python3", extraArgs: ["-m", "uvicorn"] };
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
          if (existsSync(exe)) return exe;
          const linux = join(base, d, "chrome-linux", "chrome");
          if (existsSync(linux)) return linux;
        }
      }
    } catch {
      /* next */
    }
  }
  return undefined;
}

function startStaticServer(dir, port, apiBackendPort) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };
  const server = createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || "/").split("?")[0] || "/");
    if (urlPath === "/api" || urlPath.startsWith("/api/")) {
      const headers = { ...req.headers, host: `127.0.0.1:${apiBackendPort}` };
      // 浏览器 Origin 是 harness 页面临时端口产物；本地客户端代理不转发它
      delete headers.origin;
      const r = httpRequest(
        {
          host: "127.0.0.1",
          port: apiBackendPort,
          path: req.url,
          method: req.method,
          headers,
        },
        (up) => {
          res.writeHead(up.statusCode || 502, up.headers);
          up.pipe(res);
        },
      );
      r.on("error", () => {
        res.writeHead(502, { "content-type": "text/plain" });
        res.end("proxy error");
      });
      req.pipe(r);
      return;
    }
    let pn = urlPath;
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
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

function startBackend(env, port) {
  return new Promise((resolve, reject) => {
    const { cmd, extraArgs } = getPythonConfig();
    const args = [...extraArgs, "app:app", `--port=${port}`, "--host=127.0.0.1"];
    const proc = spawn(cmd, args, {
      cwd: backendDir,
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    });
    let started = false;
    const timeout = setTimeout(() => {
      if (!started) {
        proc.kill();
        reject(new Error("Backend startup timeout"));
      }
    }, 60000);
    const onData = (msg) => {
      if (started) return;
      if (
        msg.includes("Uvicorn running") ||
        msg.includes("Application startup complete")
      ) {
        started = true;
        clearTimeout(timeout);
        resolve(proc);
      }
    };
    proc.stdout.on("data", (d) => onData(d.toString()));
    proc.stderr.on("data", (d) => {
      const t = d.toString();
      if (t.trim()) onData(t);
    });
    proc.on("error", (e) => {
      clearTimeout(timeout);
      reject(e);
    });
    proc.on("exit", (code) => {
      if (!started) {
        clearTimeout(timeout);
        reject(new Error(`Backend exited with code ${code}`));
      }
    });
  });
}

async function waitProcessExit(proc, ms = 15000) {
  if (!proc || proc.killed || proc.exitCode != null) return;
  return new Promise((resolve) => {
    const t = setTimeout(() => {
      try {
        proc.kill("SIGKILL");
      } catch {
        /* */
      }
      resolve();
    }, ms);
    proc.once("exit", () => {
      clearTimeout(t);
      resolve();
    });
    try {
      proc.kill();
    } catch {
      clearTimeout(t);
      resolve();
    }
  });
}

function pythonScript(script, env, cwd = backendDir) {
  const { cmd, extraArgs } = getPythonConfig();
  const args = extraArgs.filter((a) => a !== "-m" && a !== "uvicorn");
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, [...args, "-c", script], {
      cwd,
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => {
      out += d.toString();
    });
    proc.stderr.on("data", (d) => {
      err += d.toString();
    });
    proc.on("exit", (code) => {
      if (code !== 0) reject(new Error(`python failed: ${err || code}`));
      else resolve(out.trim());
    });
  });
}

function seedFactStore(dataDir, dates, statusByDate = {}) {
  const script = `
import sys, json
sys.path.insert(0, r'''${backendDir.replace(/\\/g, "\\\\")}''')
import short_term_fact_store as store
dates = ${JSON.stringify(dates)}
status_by_date = ${JSON.stringify(statusByDate)}
for d in dates:
    status = status_by_date.get(d, "normal")
    envelope = {
        "schema_version": "short-term-daily-facts-v0.1",
        "trade_date": d,
        "session": "final",
        "is_final": True,
        "source_ids": ["eastmoney_getTopicZTPool"],
        "fetched_at": d + "T15:05:00.000000Z",
        "snapshot_at": d + "T15:10:00.000000Z",
        "status": status,
        "reason_codes": [],
        "warnings": [],
        "limitations": ["e2e fixture"],
        "source_schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "source_status": "normal",
        "source_reason_codes": [],
        "sections": {
            "facts": {
                "schema_version": "short-term-market-facts-v0.1",
                "status": "normal",
                "facts": {
                    "advance_count": 100,
                    "decline_count": 50,
                    "flat_count": 20,
                    "suspended_count": 3,
                    "eligible_count": 173,
                    "valid_count": 170,
                    "up_ratio": 0.6,
                    "limit_up_count": {"2026-07-28": 10, "2026-07-29": 12, "2026-07-30": 14}.get(d, 10),
                    "limit_down_count": 1,
                    "failed_limit_up_count": 2,
                    "touched_limit_up_count": 12,
                    "sealed_limit_up_count": {"2026-07-28": 10, "2026-07-29": 12, "2026-07-30": 14}.get(d, 10),
                    "seal_rate": 0.8,
                    "failed_board_rate": 0.2,
                },
            },
            "ladder": {
                "schema_version": "short-term-limit-up-ladder-v0.1",
                "status": "normal",
                "metrics": {
                    "max_boards": 6,
                    "lianban_count": 3,
                    "ladder": [
                        {"boards": 2, "count": 8},
                        {"boards": 3, "count": 4},
                        {"boards": 6, "count": 1},
                    ],
                },
            },
            "gap": {
                "schema_version": "short-term-ladder-gap-v0.1",
                "status": "normal",
                "metrics": {
                    "gap_level_count": 1,
                    "gap_segment_count": 1,
                    "largest_gap_width": 2,
                    "first_gap_board": 4,
                    "is_continuous": False,
                },
            },
        },
    }
    store.save_daily_facts(envelope, db_path=r'''${dataDir.replace(/\\/g, "\\\\")}''' + "/short_term_facts.sqlite3")
print("ok")
`;
  return pythonScript(script, { VR_DATA_DIR: dataDir });
}

function corruptStore(dataDir) {
  const dbPath = join(dataDir, "short_term_facts.sqlite3");
  mkdirSync(dataDir, { recursive: true });
  writeFileSync(dbPath, "this is not a sqlite database at all", "utf8");
}

function seedDailyReviewCache(dataDir, savedAt = "2026-07-20T08:00:00+00:00") {
  mkdirSync(dataDir, { recursive: true });
  writeFileSync(
    join(dataDir, "daily_review_latest.json"),
    JSON.stringify({
      schema_version: "daily-review-cache-v0.1",
      saved_at: savedAt,
      review: {
        schema_version: "daily-review-v0.1",
        status: "normal",
        trade_date: "2026-07-20",
        generated_at: "2026-07-20 16:00",
        data_cutoff: null,
        warnings: [],
        data_health: { components: {} },
        market_environment: {},
        sector_rotation: {},
        short_term_emotion: { data: null },
        capital_activity: {},
      },
    }, null, 2),
    "utf8",
  );
}

function assertNoSensitive(text, tempDir) {
  for (const bad of ["Traceback", "sqlite3", "Authorization"]) {
    if (text.includes(bad)) throw new Error(`sensitive leak: ${bad}`);
  }
  if (text.includes(path.basename(tempDir))) {
    throw new Error("response leaks temp directory name");
  }
}

async function openDailyReview(page, apiUrl, baseUrl) {
  await page.route("**/api/market/northbound*", (route) => route.abort());
  const bk11Requests = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/market/bk11-history")) {
      bk11Requests.push(req.url());
    }
  });
  await page.goto(`${baseUrl}/daily-review`, { waitUntil: "load" });
  await page.waitForSelector("text=短线市场历史", { timeout: 20000 });
  return bk11Requests;
}

async function checkApi(apiUrl, path) {
  const r = await fetch(`${apiUrl}${path}`);
  if (!r.ok) throw new Error(`${path} HTTP ${r.status}`);
  return r.json();
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error(`Frontend dist not found: ${frontendDist}. Run 'npm run build' first.`);
  }

  const errors = [];
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      executablePath: findChromium(),
    });

    // ------------------------------------------------------------------
    // A. 多日快照：最新事实 / 比较 / 摘要 / digest / 请求唯一 / 刷新不重复
    // ------------------------------------------------------------------
    {
      const tempDir = mkdtempSync(join(tmpdir(), "vr-bk11-e2e-multi-"));
      const env = {
        VR_DATA_DIR: tempDir,
        VIBE_RESEARCH_REVIEW_DB: join(tempDir, "daily_reviews.sqlite3"),
      };
      seedDailyReviewCache(tempDir);
      await seedFactStore(
        tempDir,
        ["2026-07-28", "2026-07-29", "2026-07-30"],
        {},
      );
      const backendPort = await getFreePort();
      const frontendPort = await getFreePort();
      const apiUrl = `http://127.0.0.1:${backendPort}`;
      const baseUrl = `http://127.0.0.1:${frontendPort}`;
      const backend = await startBackend(env, backendPort);
      let frontendServer;
      try {
        await waitHttp(`${apiUrl}/api/health`);
        const data = (await checkApi(apiUrl, "/api/market/bk11-history?days=5")).data;
        if (data.status !== "normal") throw new Error("multi-day status != normal");
        if (data.trade_date !== "2026-07-30") throw new Error("multi-day trade_date wrong");
        if (data.delta?.deltas?.facts?.limit_up_count !== 2) {
          throw new Error(`multi-day delta wrong: ${JSON.stringify(data.delta?.deltas?.facts)}`);
        }
        if (data.summary?.window?.count !== 3) throw new Error("multi-day summary window != 3");
        if (!String(data.digest?.digest_text || "").includes("短线市场事实摘要")) {
          throw new Error("multi-day digest text missing");
        }
        const health = (await checkApi(apiUrl, "/api/data-health")).data;
        const bk11 = health.items.find((it) => it.source_id === "bk11_history");
        if (!bk11 || bk11.status !== "normal" || bk11.data_trade_date !== "2026-07-30") {
          throw new Error(`data-health bk11_history wrong: ${JSON.stringify(bk11)}`);
        }

        frontendServer = await startStaticServer(frontendDist, frontendPort, backendPort);
        await waitHttp(baseUrl);
        const context = await browser.newContext({ baseURL: baseUrl, viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        const bk11Requests = await openDailyReview(page, apiUrl, baseUrl);
        if (bk11Requests.length !== 1) {
          throw new Error(`expected exactly 1 bk11-history request, got ${bk11Requests.length}`);
        }
        const block = page.locator("section.order-\\[11\\]");
        await block.getByText("核心市场事实").waitFor({ timeout: 10000 });
        await block.getByText("与前序快照变化").waitFor({ timeout: 10000 });
        await block.getByText("+2").first().waitFor({ timeout: 10000 });
        await block.getByText(/短线市场事实摘要/).first().waitFor({ timeout: 10000 });
        await block.getByText("2026-07-30").first().waitFor({ timeout: 10000 });
        // 真实渲染的业务数值（不得只断言区块标题）
        await block.getByText("100", { exact: true }).first().waitFor({ timeout: 10000 }); // 上涨家数
        await block.getByText("50", { exact: true }).first().waitFor({ timeout: 10000 }); // 下跌家数
        await block.getByText("14", { exact: true }).first().waitFor({ timeout: 10000 }); // 涨停家数（07-30）
        await block.getByText(/最高板:\s*6/).first().waitFor({ timeout: 10000 });
        await block.getByText(/连板家数:\s*3/).first().waitFor({ timeout: 10000 });
        // 连板梯队数组：板数升序 2/3/6，对应数量 8/4/1
        const ladderCells = await block
          .locator("table")
          .first()
          .locator("td")
          .allTextContents();
        const ladderTexts = ladderCells.map((t) => t.trim());
        const expectedLadder = ["2", "8", "3", "4", "6", "1"];
        if (JSON.stringify(ladderTexts) !== JSON.stringify(expectedLadder)) {
          throw new Error(`ladder cells mismatch: ${JSON.stringify(ladderTexts)}`);
        }
        // 断层字段（正式合同字段名）
        await block.getByText(/缺口层级:\s*1/).first().waitFor({ timeout: 10000 });
        await block.getByText(/缺口段数:\s*1/).first().waitFor({ timeout: 10000 });
        await block.getByText(/最大宽度:\s*2/).first().waitFor({ timeout: 10000 });

        // stale 缓存触发后台轮询刷新：刷新周期不得重复请求历史接口
        await sleep(7000);
        if (bk11Requests.length !== 1) {
          throw new Error(`bk11-history requests during refresh polling: ${bk11Requests.length}`);
        }

        // 快速导航离开再回来：不崩溃、不卡 loading、最终仍加载完成
        await page.goto(`${baseUrl}/data-health`, { waitUntil: "networkidle" });
        await page.getByText("BK-11 短线历史").first().waitFor({ timeout: 10000 });
        await page.goto(`${baseUrl}/daily-review`, { waitUntil: "load" });
        await page.waitForSelector("text=短线市场历史", { timeout: 20000 });
        const block2 = page.locator("section.order-\\[11\\]");
        await block2.getByText("核心市场事实").waitFor({ timeout: 10000 });
        if (bk11Requests.length !== 2) {
          throw new Error(`bk11-history requests after re-navigation: ${bk11Requests.length}`);
        }
        await context.close();

        // 移动端：无横向溢出
        const mobileContext = await browser.newContext({
          baseURL: baseUrl,
          viewport: { width: 375, height: 667 },
          isMobile: true,
        });
        const mobilePage = await mobileContext.newPage();
        await mobilePage.route("**/api/market/northbound*", (route) => route.abort());
        await mobilePage.goto(`${baseUrl}/daily-review`, { waitUntil: "load" });
        await mobilePage.waitForSelector("text=短线市场历史", { timeout: 20000 });
        const overflow = await mobilePage.evaluate(() => {
          const doc = document.documentElement;
          return { sw: doc.scrollWidth, iw: doc.clientWidth };
        });
        if (overflow.sw > overflow.iw + 2) {
          throw new Error(`mobile horizontal overflow: ${JSON.stringify(overflow)}`);
        }
        await mobileContext.close();
        console.log("[E2E] scenario A multi-day OK");
      } finally {
        frontendServer?.close();
        await waitProcessExit(backend);
        rmSync(tempDir, { recursive: true, force: true });
      }
    }

    // ------------------------------------------------------------------
    // B. 单日快照：不伪造比较
    // ------------------------------------------------------------------
    {
      const tempDir = mkdtempSync(join(tmpdir(), "vr-bk11-e2e-single-"));
      const env = {
        VR_DATA_DIR: tempDir,
        VIBE_RESEARCH_REVIEW_DB: join(tempDir, "daily_reviews.sqlite3"),
      };
      await seedFactStore(tempDir, ["2026-07-30"]);
      const backendPort = await getFreePort();
      const frontendPort = await getFreePort();
      const apiUrl = `http://127.0.0.1:${backendPort}`;
      const baseUrl = `http://127.0.0.1:${frontendPort}`;
      const backend = await startBackend(env, backendPort);
      let frontendServer;
      try {
        await waitHttp(`${apiUrl}/api/health`);
        const data = (await checkApi(apiUrl, "/api/market/bk11-history")).data;
        if (data.delta !== null) throw new Error("single-day delta must be null");
        frontendServer = await startStaticServer(frontendDist, frontendPort, backendPort);
        await waitHttp(baseUrl);
        const context = await browser.newContext({ baseURL: baseUrl, viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        await openDailyReview(page, apiUrl, baseUrl);
        const block = page.locator("section.order-\\[11\\]");
        await block.getByText("核心市场事实").waitFor({ timeout: 10000 });
        await block.getByText("暂无前序快照，不生成比较").waitFor({ timeout: 10000 });
        await block.getByText("100", { exact: true }).first().waitFor({ timeout: 10000 });
        await block.getByText("14", { exact: true }).first().waitFor({ timeout: 10000 });
        await context.close();
        console.log("[E2E] scenario B single-day OK");
      } finally {
        frontendServer?.close();
        await waitProcessExit(backend);
        rmSync(tempDir, { recursive: true, force: true });
      }
    }

    // ------------------------------------------------------------------
    // C. 空库：空状态 + GET 不创建数据库 + Data Health not_initialized
    // ------------------------------------------------------------------
    {
      const tempDir = mkdtempSync(join(tmpdir(), "vr-bk11-e2e-empty-"));
      const env = {
        VR_DATA_DIR: tempDir,
        VIBE_RESEARCH_REVIEW_DB: join(tempDir, "daily_reviews.sqlite3"),
      };
      const backendPort = await getFreePort();
      const frontendPort = await getFreePort();
      const apiUrl = `http://127.0.0.1:${backendPort}`;
      const baseUrl = `http://127.0.0.1:${frontendPort}`;
      const backend = await startBackend(env, backendPort);
      let frontendServer;
      try {
        await waitHttp(`${apiUrl}/api/health`);
        const data = (await checkApi(apiUrl, "/api/market/bk11-history")).data;
        if (data.status !== "empty") throw new Error("empty status wrong");
        if (existsSync(join(tempDir, "short_term_facts.sqlite3"))) {
          throw new Error("GET created a database file");
        }
        const health = (await checkApi(apiUrl, "/api/data-health")).data;
        const bk11 = health.items.find((it) => it.source_id === "bk11_history");
        if (!bk11 || bk11.last_error_code !== "SOURCE_NOT_INITIALIZED") {
          throw new Error(`empty data-health wrong: ${JSON.stringify(bk11)}`);
        }
        frontendServer = await startStaticServer(frontendDist, frontendPort, backendPort);
        await waitHttp(baseUrl);
        const context = await browser.newContext({ baseURL: baseUrl, viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        await openDailyReview(page, apiUrl, baseUrl);
        const block = page.locator("section.order-\\[11\\]");
        await block.getByText("暂无已保存的 BK-11 短线历史快照").first().waitFor({ timeout: 10000 });
        if (existsSync(join(tempDir, "short_term_facts.sqlite3"))) {
          throw new Error("page load created a database file");
        }
        await context.close();
        console.log("[E2E] scenario C empty OK");
      } finally {
        frontendServer?.close();
        await waitProcessExit(backend);
        rmSync(tempDir, { recursive: true, force: true });
      }
    }

    // ------------------------------------------------------------------
    // D. partial 快照：明确显示 partial
    // ------------------------------------------------------------------
    {
      const tempDir = mkdtempSync(join(tmpdir(), "vr-bk11-e2e-partial-"));
      const env = {
        VR_DATA_DIR: tempDir,
        VIBE_RESEARCH_REVIEW_DB: join(tempDir, "daily_reviews.sqlite3"),
      };
      await seedFactStore(
        tempDir,
        ["2026-07-28", "2026-07-29", "2026-07-30"],
        { "2026-07-30": "partial" },
      );
      const backendPort = await getFreePort();
      const frontendPort = await getFreePort();
      const apiUrl = `http://127.0.0.1:${backendPort}`;
      const baseUrl = `http://127.0.0.1:${frontendPort}`;
      const backend = await startBackend(env, backendPort);
      let frontendServer;
      try {
        await waitHttp(`${apiUrl}/api/health`);
        const data = (await checkApi(apiUrl, "/api/market/bk11-history")).data;
        if (data.status !== "partial") throw new Error("partial status wrong");
        frontendServer = await startStaticServer(frontendDist, frontendPort, backendPort);
        await waitHttp(baseUrl);
        const context = await browser.newContext({ baseURL: baseUrl, viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        await openDailyReview(page, apiUrl, baseUrl);
        const block = page.locator("section.order-\\[11\\]");
        await block.getByText("部分缺失").first().waitFor({ timeout: 10000 });
        await block.getByText("最新快照仅部分可用").first().waitFor({ timeout: 10000 });
        await block.getByText("核心市场事实").waitFor({ timeout: 10000 });
        await context.close();
        console.log("[E2E] scenario D partial OK");
      } finally {
        frontendServer?.close();
        await waitProcessExit(backend);
        rmSync(tempDir, { recursive: true, force: true });
      }
    }

    // ------------------------------------------------------------------
    // E. unavailable 快照：不展示伪造指标
    // ------------------------------------------------------------------
    {
      const tempDir = mkdtempSync(join(tmpdir(), "vr-bk11-e2e-unavail-"));
      const env = {
        VR_DATA_DIR: tempDir,
        VIBE_RESEARCH_REVIEW_DB: join(tempDir, "daily_reviews.sqlite3"),
      };
      await seedFactStore(tempDir, ["2026-07-30"], { "2026-07-30": "unavailable" });
      const backendPort = await getFreePort();
      const frontendPort = await getFreePort();
      const apiUrl = `http://127.0.0.1:${backendPort}`;
      const baseUrl = `http://127.0.0.1:${frontendPort}`;
      const backend = await startBackend(env, backendPort);
      let frontendServer;
      try {
        await waitHttp(`${apiUrl}/api/health`);
        const data = (await checkApi(apiUrl, "/api/market/bk11-history")).data;
        if (data.status !== "unavailable") throw new Error("unavailable status wrong");
        frontendServer = await startStaticServer(frontendDist, frontendPort, backendPort);
        await waitHttp(baseUrl);
        const context = await browser.newContext({ baseURL: baseUrl, viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        await openDailyReview(page, apiUrl, baseUrl);
        const block = page.locator("section.order-\\[11\\]");
        await block.getByText("最新快照当前不可用").first().waitFor({ timeout: 10000 });
        const fakeVisible = await block.getByText("核心市场事实").count();
        if (fakeVisible > 0) throw new Error("unavailable must not render facts");
        await context.close();
        console.log("[E2E] scenario E unavailable OK");
      } finally {
        frontendServer?.close();
        await waitProcessExit(backend);
        rmSync(tempDir, { recursive: true, force: true });
      }
    }

    // ------------------------------------------------------------------
    // F. 损坏存储：区块失败但页面其他区域正常 + 无泄漏
    // ------------------------------------------------------------------
    {
      const tempDir = mkdtempSync(join(tmpdir(), "vr-bk11-e2e-corrupt-"));
      const env = {
        VR_DATA_DIR: tempDir,
        VIBE_RESEARCH_REVIEW_DB: join(tempDir, "daily_reviews.sqlite3"),
      };
      corruptStore(tempDir);
      const backendPort = await getFreePort();
      const frontendPort = await getFreePort();
      const apiUrl = `http://127.0.0.1:${backendPort}`;
      const baseUrl = `http://127.0.0.1:${frontendPort}`;
      const backend = await startBackend(env, backendPort);
      let frontendServer;
      try {
        await waitHttp(`${apiUrl}/api/health`);
        const resp = await fetch(`${apiUrl}/api/market/bk11-history`);
        if (resp.status !== 200) throw new Error(`corrupted HTTP ${resp.status}`);
        const body = await resp.json();
        if (body.data.status !== "error") throw new Error("corrupted status != error");
        assertNoSensitive(JSON.stringify(body), tempDir);
        const health = (await checkApi(apiUrl, "/api/data-health")).data;
        const bk11 = health.items.find((it) => it.source_id === "bk11_history");
        if (!bk11 || bk11.last_error_code !== "SOURCE_CORRUPTED") {
          throw new Error(`corrupted data-health wrong: ${JSON.stringify(bk11)}`);
        }
        frontendServer = await startStaticServer(frontendDist, frontendPort, backendPort);
        await waitHttp(baseUrl);
        const context = await browser.newContext({ baseURL: baseUrl, viewport: { width: 1440, height: 900 } });
        const page = await context.newPage();
        await openDailyReview(page, apiUrl, baseUrl);
        const block = page.locator("section.order-\\[11\\]");
        await block.getByText("短线市场历史存储当前无法安全读取").first().waitFor({ timeout: 10000 });
        // 页面其他区域仍正常
        await page.getByText("历史复盘").first().waitFor({ timeout: 10000 });
        await context.close();
        console.log("[E2E] scenario F corrupted OK");
      } finally {
        frontendServer?.close();
        await waitProcessExit(backend);
        rmSync(tempDir, { recursive: true, force: true });
      }
    }
  } catch (e) {
    errors.push(e && e.stack ? e.stack : String(e));
  } finally {
    await browser?.close();
  }

  if (errors.length > 0) {
    console.error(errors.join("\n\n"));
    process.exit(1);
  }
  console.log("[E2E] BK-11 history scenarios all passed");
}

main().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
