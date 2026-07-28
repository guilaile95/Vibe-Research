/**
 * 数据健康中心 — 真实后端 E2E（禁止 mock /api/data-health）
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import {
  mkdtempSync, rmSync, existsSync, readdirSync, createReadStream,
  writeFileSync, mkdirSync, statSync, readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(url);
      if (r.ok || r.status < 500) return r;
    } catch { /* retry */ }
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

function startStaticServer(dir, port) {
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
    let pn = (req.url || "/").split("?")[0];
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
    const rd = path.resolve(dir);
    const rt = path.resolve(target);
    if (!rt.startsWith(rd + path.sep) && rt !== rd) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
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
          const mac = join(base, d, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium");
          if (existsSync(mac)) return mac;
        }
      }
    } catch { /* next */ }
  }
  return undefined;
}

function snapshotFs(rootDir) {
  const files = {};
  const walk = (dir) => {
    if (!existsSync(dir)) return;
    for (const name of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, name.name);
      if (name.isDirectory()) walk(p);
      else {
        const st = statSync(p);
        files[path.relative(rootDir, p)] = { size: st.size, mtime: st.mtimeMs };
      }
    }
  };
  walk(rootDir);
  return files;
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
    }, 45000);
    const onData = (msg) => {
      if (started) return;
      if (msg.includes("Uvicorn running") || msg.includes("Application startup complete")) {
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

function seedFixtures(dataDir) {
  // daily review normal cache
  const review = {
    schema_version: "daily-review-cache-v0.1",
    saved_at: "2026-07-25T08:00:00+00:00",
    review: {
      schema_version: "daily-review-v0.1",
      status: "normal",
      trade_date: "2026-07-25",
      generated_at: "2026-07-25 16:00",
      data_cutoff: null,
      warnings: [],
      data_health: {
        components: {
          indices: "normal",
          global_indices: "normal",
          breadth: "normal",
          emotion: "normal",
          turnover: "normal",
          industry_boards: "normal",
          concept_boards: "normal",
          region_boards: "normal",
        },
      },
      market_environment: { indices: { data: [] }, global_indices: { data: [] }, breadth: { data: null } },
      sector_rotation: { industry: { data: null }, concept: { data: null }, region: { data: null }, highlights: {} },
      short_term_emotion: { data: null },
      capital_activity: { turnover_top: { data: null }, total_amount: null, amount_valid_count: null, amount_top: [], high_turnover: [] },
    },
  };
  writeFileSync(join(dataDir, "daily_review_latest.json"), JSON.stringify(review, null, 2), "utf8");

  // events: quotes partial, gate blocked; announcements left uninitialized
  const obsPartial = "2026-07-28T01:00:00.000000Z";
  const obsGate = "2026-07-28T01:05:00.000000Z";
  const events = {
    schema_version: "data-health-events.v1",
    events: {
      quotes: {
        source_id: "quotes",
        last_success_at: obsPartial,
        last_error_at: obsPartial,
        last_error_code: "SOURCE_PARTIAL",
      },
      portfolio_advice_gate: {
        source_id: "portfolio_advice_gate",
        last_success_at: obsGate,
        last_error_at: obsGate,
        last_error_code: "HOLDING_QUOTES_UNAVAILABLE",
      },
    },
  };
  writeFileSync(join(dataDir, "data_health_events.json"), JSON.stringify(events, null, 2), "utf8");

  // stale news radar — write into backend/.cache via env is hard; write under dataDir
  // and rely on monkeypatch... For real E2E we put radar where newsradar expects:
  // backend/.cache/radar.json — avoid polluting; instead inject via Python after start
  // We'll use a companion seed script run with PYTHONPATH.
  return { eventsPath: join(dataDir, "data_health_events.json") };
}

async function seedNewsRadar(dataDir) {
  // Create radar cache under a path we control by writing to backend/.cache only if empty?
  // Prefer: run python to write via newsradar.CACHE_FILE temporarily — but that pollutes.
  // Write to VR-relative path won't work. Use process that patches:
  // For E2E, write backend/.cache/radar.json with stale data and restore after.
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error(`Frontend dist not found: ${frontendDist}. Run 'npm run build' first.`);
  }

  const tempDir = mkdtempSync(join(tmpdir(), "vr-data-health-e2e-"));
  const reportsDir = join(tempDir, "myreports");
  mkdirSync(reportsDir, { recursive: true });
  const evidenceDb = join(tempDir, "evidence_thesis.db");
  const reviewDb = join(tempDir, "daily_reviews.sqlite3");

  seedFixtures(tempDir);

  // Stale news radar: place file and set NEWS_RADAR override via symlink — newsradar uses fixed CACHE_FILE.
  // Write stale cache into backend/.cache with backup restore.
  const radarCacheDir = path.join(backendDir, ".cache");
  const radarFile = path.join(radarCacheDir, "radar.json");
  let radarBackup = null;
  let radarExisted = false;
  mkdirSync(radarCacheDir, { recursive: true });
  if (existsSync(radarFile)) {
    radarExisted = true;
    radarBackup = readFileSync(radarFile);
  }
  const oldGen = "2026-06-01 10:00";
  writeFileSync(
    radarFile,
    JSON.stringify({
      generated_at: oldGen,
      recent_days: 7,
      industries: [{ key: "ai", name: "AI", items: [{ title: "t" }] }],
      stats: { industries: 1, total_sources: 10, failed_sources: 0 },
    }),
    "utf8",
  );

  const backendPort = await getFreePort();
  const frontendPort = await getFreePort();
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const apiUrl = `http://127.0.0.1:${backendPort}`;

  let backend;
  let browser;
  let frontendServer;

  const env = {
    VR_DATA_DIR: tempDir,
    VR_REPORTS_DIR: reportsDir,
    VIBE_RESEARCH_REVIEW_DB: reviewDb,
    VIBE_RESEARCH_EVIDENCE_THESIS_DB: evidenceDb,
  };

  try {
    console.log("[E2E] Starting real FastAPI...");
    backend = await startBackend(env, backendPort);
    await waitHttp(`${apiUrl}/api/health`);

    // API-level seed check (no mock)
    const healthRes = await fetch(`${apiUrl}/api/data-health`);
    if (!healthRes.ok) throw new Error(`data-health HTTP ${healthRes.status}`);
    const healthJson = await healthRes.json();
    const data = healthJson.data;
    if (!data || !Array.isArray(data.items) || data.items.length !== 11) {
      throw new Error(`expected 11 items, got ${data?.items?.length}`);
    }
    if (data.blocks_advice !== true) throw new Error("expected gate blocks_advice");
    const byId = Object.fromEntries(data.items.map((i) => [i.source_id, i]));
    if (byId.quotes?.status !== "partial") throw new Error("quotes should be partial");
    if (byId.announcements?.last_error_code !== "SOURCE_NOT_INITIALIZED") {
      throw new Error("announcements should be not initialized");
    }
    if (byId.news_radar && byId.news_radar.is_stale !== true) {
      console.warn("[E2E] news_radar is_stale expected true, got", byId.news_radar.is_stale, byId.news_radar);
    }
    if (byId.daily_review?.status !== "normal") {
      throw new Error(`daily_review expected normal, got ${byId.daily_review?.status}`);
    }
    if (data.overall_status !== "partial") {
      throw new Error(`overall expected partial, got ${data.overall_status}`);
    }

    // Sensitive leak check on API body
    const bodyText = JSON.stringify(healthJson);
    for (const bad of ["Traceback", "sqlite3", tempDir, "TEST_SECRET", "Authorization"]) {
      if (bodyText.includes(bad)) throw new Error(`sensitive leak: ${bad}`);
    }

    // Readonly snapshot before browser GETs
    const beforeFs = snapshotFs(tempDir);

    console.log("[E2E] Starting frontend static server...");
    frontendServer = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(baseUrl);

    browser = await chromium.launch({
      headless: true,
      executablePath: findChromium(),
    });
    const context = await browser.newContext({ baseURL: baseUrl });
    const page = await context.newPage();

    // Proxy ALL /api/* to real backend — NO mock of data-health
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = request.url();
      const parsed = new URL(url);
      const p = parsed.pathname + parsed.search;
      const headers = { ...request.headers() };
      delete headers["host"];
      const init = {
        method: request.method(),
        headers,
      };
      if (request.method() !== "GET" && request.method() !== "HEAD") {
        init.body = request.postDataBuffer();
      }
      const resp = await fetch(`${apiUrl}${p}`, init);
      const buf = Buffer.from(await resp.arrayBuffer());
      const rh = {};
      resp.headers.forEach((v, k) => {
        if (k.toLowerCase() !== "content-encoding") rh[k] = v;
      });
      await route.fulfill({ status: resp.status, headers: rh, body: buf });
    });

    console.log("[E2E] Open /data-health");
    await page.goto("/data-health", { waitUntil: "networkidle" });
    await page.waitForSelector("text=数据健康", { timeout: 15000 });

    // 11 sources visible by display names / cards
    const sourceNames = [
      "每日复盘",
      "持仓建议 Gate",
      "持仓行情覆盖",
      "个股行情",
      "个股公告",
      "财务数据",
      "资讯雷达",
      "板块动态数据",
      "我的研报",
      "自选股与持仓存储",
      "投资逻辑与证据账本",
    ];
    for (const name of sourceNames) {
      const loc = page.getByText(name, { exact: false }).first();
      await loc.waitFor({ timeout: 10000 });
    }

    // overall partial + gate blocked text
    await page.getByText("部分可用", { exact: false }).first().waitFor();
    await page.getByText("当前阻止", { exact: false }).first().waitFor();
    await page.getByText("部分持仓缺少有效行情", { exact: false }).first().waitFor();

    // open quotes detail for disclaimer
    await page.getByText("个股行情", { exact: true }).first().click();
    await page.getByText("不代表全部股票或板块均已验证", { exact: false }).first().waitFor({ timeout: 10000 });

    // page should not show sensitive strings
    const pageText = await page.locator("body").innerText();
    for (const bad of ["Traceback", "sqlite3", "TEST_SECRET"]) {
      if (pageText.includes(bad)) throw new Error(`page leak: ${bad}`);
    }
    if (pageText.includes(tempDir.replace(/\\/g, "\\"))) {
      // path leak
      throw new Error("page leaks temp path");
    }

    // GET readonly: compare fs after
    const afterFs = snapshotFs(tempDir);
    const beforeKeys = Object.keys(beforeFs).sort();
    const afterKeys = Object.keys(afterFs).sort();
    if (JSON.stringify(beforeKeys) !== JSON.stringify(afterKeys)) {
      throw new Error(`filesystem file set changed after GET: ${beforeKeys} vs ${afterKeys}`);
    }
    for (const k of beforeKeys) {
      if (beforeFs[k].size !== afterFs[k].size) {
        throw new Error(`file size changed: ${k}`);
      }
      if (beforeFs[k].mtime !== afterFs[k].mtime) {
        throw new Error(`file mtime changed: ${k}`);
      }
    }

    // evidence db should not appear (never initialized)
    if (existsSync(evidenceDb)) {
      throw new Error("evidence db was created by health GET");
    }

    console.log("[E2E] data-health real E2E PASSED");
  } finally {
    try { if (browser) await browser.close(); } catch { /* */ }
    try { if (frontendServer) frontendServer.close(); } catch { /* */ }
    try { if (backend) backend.kill(); } catch { /* */ }
    // restore radar cache
    try {
      if (radarExisted && radarBackup) writeFileSync(radarFile, radarBackup);
      else if (existsSync(radarFile) && !radarExisted) {
        // only remove if we created it and no prior file — leave if was empty write over our content
        try {
          const { unlinkSync } = await import("node:fs");
          unlinkSync(radarFile);
        } catch { /* */ }
      }
    } catch { /* */ }
    try { rmSync(tempDir, { recursive: true, force: true }); } catch { /* */ }
  }
}

main().catch((e) => {
  console.error("[E2E] FAILED", e);
  process.exit(1);
});
