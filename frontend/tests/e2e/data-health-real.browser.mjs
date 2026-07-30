/**
 * 数据健康中心 — 真实后端 E2E（禁止 mock /api/data-health）
 * 所有 fixture 位于临时目录；不写仓库内 backend/.cache。
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  existsSync,
  readdirSync,
  createReadStream,
  writeFileSync,
  mkdirSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import path from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitHttp(url, attempts = 80) {
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
          const mac = join(
            base,
            d,
            "chrome-mac",
            "Chromium.app",
            "Contents",
            "MacOS",
            "Chromium",
          );
          if (existsSync(mac)) return mac;
        }
      }
    } catch {
      /* next */
    }
  }
  return undefined;
}

function snapshotFs(rootDir) {
  const files = {};
  const dirs = new Set();
  const walk = (dir) => {
    if (!existsSync(dir)) return;
    dirs.add(path.relative(rootDir, dir) || ".");
    for (const name of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, name.name);
      if (name.isDirectory()) {
        walk(p);
      } else {
        const st = statSync(p);
        files[path.relative(rootDir, p)] = {
          size: st.size,
          mtimeNs: st.mtimeMs,
        };
      }
    }
  };
  walk(rootDir);
  return { dirs, files };
}

function assertFsUnchanged(before, after, label) {
  // directory set must be strictly equal
  const beforeDirs = [...before.dirs].sort();
  const afterDirs = [...after.dirs].sort();
  if (JSON.stringify(beforeDirs) !== JSON.stringify(afterDirs)) {
    throw new Error(
      `${label}: directory set changed: ${JSON.stringify(beforeDirs)} vs ${JSON.stringify(afterDirs)}`,
    );
  }
  // file set must be strictly equal
  const beforeKeys = Object.keys(before.files).sort();
  const afterKeys = Object.keys(after.files).sort();
  if (JSON.stringify(beforeKeys) !== JSON.stringify(afterKeys)) {
    throw new Error(
      `${label}: filesystem file set changed: ${JSON.stringify(beforeKeys)} vs ${JSON.stringify(afterKeys)}`,
    );
  }
  for (const k of beforeKeys) {
    if (before.files[k].size !== after.files[k].size) {
      throw new Error(`${label}: file size changed: ${k}`);
    }
    if (before.files[k].mtimeNs !== after.files[k].mtimeNs) {
      throw new Error(`${label}: file mtime changed: ${k}`);
    }
  }
}

// snapshot db / -wal / -shm existence + size + mtimeMs
function snapshotDbArtifacts(dbPath) {
  const out = {};
  const base = dbPath.replace(/\.db$/i, "");
  for (const suffix of ["", "-wal", "-shm"]) {
    const p = suffix === "" ? dbPath : base + suffix;
    if (existsSync(p)) {
      const st = statSync(p);
      out[suffix || "db"] = { exists: true, size: st.size, mtimeMs: st.mtimeMs };
    } else {
      out[suffix || "db"] = { exists: false, size: 0, mtimeMs: 0 };
    }
  }
  return out;
}

function assertDbArtifactsUnchanged(before, after, label) {
  for (const k of ["db", "-wal", "-shm"]) {
    const b = before[k];
    const a = after[k];
    if (b.exists !== a.exists) {
      throw new Error(`${label}: ${k} existence changed: ${b.exists} -> ${a.exists}`);
    }
    if (b.exists) {
      if (b.size !== a.size) {
        throw new Error(`${label}: ${k} size changed: ${b.size} -> ${a.size}`);
      }
      if (b.mtimeMs !== a.mtimeMs) {
        throw new Error(`${label}: ${k} mtime changed: ${b.mtimeMs} -> ${a.mtimeMs}`);
      }
    }
  }
}

async function listSqliteTablesViaPython(dbPath, env) {
  const { cmd, extraArgs } = getPythonConfig();
  // drop uvicorn from extraArgs — getPythonConfig returns uvicorn args; use pure python
  const pyCmd = env.PYTHON || (process.platform === "win32" ? "py" : "python3");
  const pyArgs =
    process.platform === "win32" && pyCmd === "py"
      ? ["-3", "-c"]
      : ["-c"];
  const script = `
import sqlite3, json, sys
from pathlib import Path
p = Path(r'''${dbPath.replace(/\\/g, "\\\\")}''')
uri = p.resolve().as_uri() + "?mode=ro&immutable=1"
conn = sqlite3.connect(uri, uri=True)
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
conn.close()
print(json.dumps([r[0] for r in rows]))
`;
  return new Promise((resolve, reject) => {
    const proc = spawn(pyCmd, [...pyArgs, script], {
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
      if (code !== 0) reject(new Error(`sqlite list failed: ${err || code}`));
      else {
        try {
          resolve(JSON.parse(out.trim()));
        } catch (e) {
          reject(e);
        }
      }
    });
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
    }, 45000);
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

function seedFixtures(dataDir, radarPath, evidenceDb) {
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
      market_environment: {
        indices: { data: [] },
        global_indices: { data: [] },
        breadth: { data: null },
      },
      sector_rotation: {
        industry: { data: null },
        concept: { data: null },
        region: { data: null },
        highlights: {},
      },
      short_term_emotion: { data: null },
      capital_activity: {
        turnover_top: { data: null },
        total_amount: null,
        amount_valid_count: null,
        amount_top: [],
        high_turnover: [],
      },
    },
  };
  writeFileSync(
    join(dataDir, "daily_review_latest.json"),
    JSON.stringify(review, null, 2),
    "utf8",
  );

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
  writeFileSync(
    join(dataDir, "data_health_events.json"),
    JSON.stringify(events, null, 2),
    "utf8",
  );

  // stale news radar in temp path only
  mkdirSync(dirname(radarPath), { recursive: true });
  writeFileSync(
    radarPath,
    JSON.stringify({
      generated_at: "2026-06-01 10:00",
      recent_days: 7,
      industries: [{ key: "ai", name: "AI", items: [{ title: "t" }] }],
      stats: { industries: 1, total_sources: 10, "failed_sources": 0 },
    }),
    "utf8",
  );
}

async function initEvidenceDb(evidenceDb, env) {
  const pyCmd =
    process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
  const pyArgs =
    process.platform === "win32" && pyCmd === "py" ? ["-3", "-c"] : ["-c"];
  const script = `
import sys
sys.path.insert(0, r'''${backendDir.replace(/\\/g, "\\\\")}''')
import evidence_thesis_store as s
s.initialize_store(r'''${evidenceDb.replace(/\\/g, "\\\\")}''')
print("ok")
`;
  await new Promise((resolve, reject) => {
    const proc = spawn(pyCmd, [...pyArgs, script], {
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
      cwd: backendDir,
    });
    let err = "";
    proc.stderr.on("data", (d) => {
      err += d.toString();
    });
    proc.on("exit", (code) => {
      if (code !== 0) reject(new Error(`init evidence db failed: ${err || code}`));
      else resolve();
    });
  });
}

function assertNoSensitive(text, tempDir) {
  for (const bad of [
    "Traceback",
    "sqlite3",
    "TEST_SECRET",
    "Authorization",
  ]) {
    if (text.includes(bad)) throw new Error(`sensitive leak: ${bad}`);
  }
  // do not require tempDir absence if path separators vary — check basename markers
  if (text.includes("vr-data-health-e2e-")) {
    throw new Error("response leaks temp directory name");
  }
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error(
      `Frontend dist not found: ${frontendDist}. Run 'npm run build' first.`,
    );
  }

  const tempDir = mkdtempSync(join(tmpdir(), "vr-data-health-e2e-"));
  const reportsDir = join(tempDir, "myreports");
  mkdirSync(reportsDir, { recursive: true });
  const evidenceDb = join(tempDir, "evidence_thesis.db");
  const reviewDb = join(tempDir, "daily_reviews.sqlite3");
  const radarPath = join(tempDir, "radar", "radar.json");

  const env = {
    VR_DATA_DIR: tempDir,
    VR_REPORTS_DIR: reportsDir,
    VIBE_RESEARCH_REVIEW_DB: reviewDb,
    VIBE_RESEARCH_EVIDENCE_THESIS_DB: evidenceDb,
    VIBE_RESEARCH_NEWS_RADAR_CACHE: radarPath,
  };

  seedFixtures(tempDir, radarPath, evidenceDb);
  await initEvidenceDb(evidenceDb, env);

  const backendPort = await getFreePort();
  const frontendPort = await getFreePort();
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const apiUrl = `http://127.0.0.1:${backendPort}`;

  let backend;
  let browser;
  let frontendServer;

  // ensure repo radar untouched baseline
  const repoRadar = path.join(backendDir, ".cache", "radar.json");
  const repoRadarExisted = existsSync(repoRadar);
  const repoRadarBefore = repoRadarExisted
    ? { size: statSync(repoRadar).size, mtime: statSync(repoRadar).mtimeMs }
    : null;

  try {
    console.log("[E2E] Starting real FastAPI...");
    backend = await startBackend(env, backendPort);
    await waitHttp(`${apiUrl}/api/health`);

    // 预读表集合（immutable 只读，不改文件），再拍基线快照
    const beforeTables = await listSqliteTablesViaPython(evidenceDb, env);
    // Snapshot AFTER health probe + table probe, BEFORE any data-health GET
    const beforeFs = snapshotFs(tempDir);
    const beforeDbStat = statSync(evidenceDb);
    const beforeDbArtifacts = snapshotDbArtifacts(evidenceDb);

    console.log("[E2E] First GET /api/data-health");
    const healthRes = await fetch(`${apiUrl}/api/data-health`);
    if (!healthRes.ok) throw new Error(`data-health HTTP ${healthRes.status}`);
    const healthJson = await healthRes.json();
    const data = healthJson.data;

    const afterFirstFs = snapshotFs(tempDir);
    assertFsUnchanged(beforeFs, afterFirstFs, "after first list GET");
    const afterFirstTables = await listSqliteTablesViaPython(evidenceDb, env);
    if (JSON.stringify(beforeTables) !== JSON.stringify(afterFirstTables)) {
      throw new Error("sqlite tables changed after first GET");
    }
    const afterFirstDb = statSync(evidenceDb);
    if (
      afterFirstDb.size !== beforeDbStat.size ||
      afterFirstDb.mtimeMs !== beforeDbStat.mtimeMs
    ) {
      throw new Error("evidence db size/mtime changed after first GET");
    }
    const afterFirstDbArtifacts = snapshotDbArtifacts(evidenceDb);
    assertDbArtifactsUnchanged(beforeDbArtifacts, afterFirstDbArtifacts, "after first list GET");

    // Hard assertions
    if (!data || !Array.isArray(data.items) || data.items.length !== 12) {
      throw new Error(`expected 12 items, got ${data?.items?.length}`);
    }
    if (data.overall_status !== "partial") {
      throw new Error(`overall expected partial, got ${data.overall_status}`);
    }
    if (data.blocks_advice !== true) {
      throw new Error("expected gate blocks_advice=true");
    }
    const byId = Object.fromEntries(data.items.map((i) => [i.source_id, i]));
    if (byId.daily_review?.status !== "normal") {
      throw new Error(`daily_review expected normal, got ${byId.daily_review?.status}`);
    }
    if (byId.quotes?.status !== "partial") {
      throw new Error(`quotes expected partial, got ${byId.quotes?.status}`);
    }
    if (byId.announcements?.last_error_code !== "SOURCE_NOT_INITIALIZED") {
      throw new Error("announcements should be not initialized");
    }
    if (byId.news_radar?.is_stale !== true) {
      throw new Error(
        `news_radar is_stale expected true, got ${byId.news_radar?.is_stale}`,
      );
    }
    if (byId.portfolio_advice_gate?.blocks_advice !== true) {
      throw new Error("gate should block advice");
    }
    if (byId.portfolio_advice_gate?.last_error_code !== "HOLDING_QUOTES_UNAVAILABLE") {
      throw new Error("gate error code mismatch");
    }

    assertNoSensitive(JSON.stringify(healthJson), tempDir);

    console.log("[E2E] Detail GET");
    const detailRes = await fetch(`${apiUrl}/api/data-health/quotes`);
    if (!detailRes.ok) throw new Error(`detail HTTP ${detailRes.status}`);
    const detailJson = await detailRes.json();
    const disc =
      detailJson?.data?.calculation?.disclaimer ||
      JSON.stringify(detailJson);
    if (!String(disc).includes("不代表全部股票或板块均已验证")) {
      throw new Error("missing request-scope disclaimer in detail");
    }
    assertNoSensitive(JSON.stringify(detailJson), tempDir);

    const afterDetailFs = snapshotFs(tempDir);
    assertFsUnchanged(beforeFs, afterDetailFs, "after detail GET");
    const afterDetailTables = await listSqliteTablesViaPython(evidenceDb, env);
    if (JSON.stringify(beforeTables) !== JSON.stringify(afterDetailTables)) {
      throw new Error("sqlite tables changed after detail GET");
    }
    const afterDetailDb = statSync(evidenceDb);
    if (
      afterDetailDb.size !== beforeDbStat.size ||
      afterDetailDb.mtimeMs !== beforeDbStat.mtimeMs
    ) {
      throw new Error("evidence db changed after detail GET");
    }
    const afterDetailDbArtifacts = snapshotDbArtifacts(evidenceDb);
    assertDbArtifactsUnchanged(beforeDbArtifacts, afterDetailDbArtifacts, "after detail GET");

    console.log("[E2E] Starting frontend static server...");
    frontendServer = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(baseUrl);

    browser = await chromium.launch({
      headless: true,
      executablePath: findChromium(),
    });
    const context = await browser.newContext({ baseURL: baseUrl });
    const page = await context.newPage();

    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = request.url();
      const parsed = new URL(url);
      const p = parsed.pathname + parsed.search;
      const headers = { ...request.headers() };
      delete headers["host"];
      const init = { method: request.method(), headers };
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
      await page.getByText(name, { exact: false }).first().waitFor({ timeout: 10000 });
    }
    await page.getByText("部分可用", { exact: false }).first().waitFor();
    await page.getByText("当前阻止", { exact: false }).first().waitFor();
    await page.getByText("部分持仓缺少有效行情", { exact: false }).first().waitFor();
    await page.getByText("个股行情", { exact: true }).first().click();
    await page
      .getByText("不代表全部股票或板块均已验证", { exact: false })
      .first()
      .waitFor({ timeout: 10000 });

    const pageText = await page.locator("body").innerText();
    assertNoSensitive(pageText, tempDir);

    const afterBrowserFs = snapshotFs(tempDir);
    assertFsUnchanged(beforeFs, afterBrowserFs, "after browser");
    const afterBrowserTables = await listSqliteTablesViaPython(evidenceDb, env);
    if (JSON.stringify(beforeTables) !== JSON.stringify(afterBrowserTables)) {
      throw new Error("sqlite tables changed after browser");
    }
    const afterBrowserDb = statSync(evidenceDb);
    if (
      afterBrowserDb.size !== beforeDbStat.size ||
      afterBrowserDb.mtimeMs !== beforeDbStat.mtimeMs
    ) {
      throw new Error("evidence db changed after browser");
    }
    const afterBrowserDbArtifacts = snapshotDbArtifacts(evidenceDb);
    assertDbArtifactsUnchanged(beforeDbArtifacts, afterBrowserDbArtifacts, "after browser");

    // repo radar untouched
    if (repoRadarExisted) {
      const st = statSync(repoRadar);
      if (
        st.size !== repoRadarBefore.size ||
        st.mtimeMs !== repoRadarBefore.mtime
      ) {
        throw new Error("repository backend/.cache/radar.json was modified");
      }
    } else if (existsSync(repoRadar)) {
      throw new Error("repository radar.json was created during E2E");
    }

    console.log("[E2E] data-health real E2E PASSED");
  } finally {
    try {
      if (browser) await browser.close();
    } catch {
      /* */
    }
    try {
      if (frontendServer) frontendServer.close();
    } catch {
      /* */
    }
    await waitProcessExit(backend);
    try {
      rmSync(tempDir, { recursive: true, force: true });
    } catch {
      /* best-effort after process exit */
      await sleep(500);
      try {
        rmSync(tempDir, { recursive: true, force: true });
      } catch {
        /* */
      }
    }
  }
}

main().catch((e) => {
  console.error("[E2E] FAILED", e);
  process.exit(1);
});
