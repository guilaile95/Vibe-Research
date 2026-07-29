/**
 * 决策依据与可解释性 — 真实后端 E2E 测试
 * 包含 Playwright 浏览器对拉起的真实 FastAPI 和 Vite 静态构建前端全流程验证
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  existsSync,
  readdirSync,
  createReadStream,
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
            "Chromium"
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

async function seedDecisionTraceData(dbPath, env) {
  const pyCmd = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
  const pyArgs = process.platform === "win32" && pyCmd === "py" ? ["-3", "-c"] : ["-c"];
  const script = `
import sys
sys.path.insert(0, r'''${backendDir.replace(/\\/g, "\\\\")}''')
import decision_trace_store as store
import decision_evidence_service as svc

db_file = r'''${dbPath.replace(/\\/g, "\\\\")}'''
store.init_db(db_file)

run_id = svc.generate_decision_run_id("2026-07-29", "2026-07-29T10:00:00.000000Z")

run_rec = {
    "decision_run_id": run_id,
    "trade_date": "2026-07-29",
    "generated_at": "2026-07-29T10:00:00.000000Z",
    "trace_status": "complete",
    "quality_status": "valid",
    "code": "600519",
    "symbol": "600519",
    "action": "hold",
    "decision_type": "portfolio_advice",
    "summary": "E2E 测试持仓建议：贵州茅台建议继续持有",
    "evidence_count": 2,
    "missing_count": 0,
    "created_at": "2026-07-29T10:00:05.000000Z",
}

evidence_items = [
    {
        "evidence_id": "ev_600519_financials",
        "decision_run_id": run_id,
        "code": "600519",
        "scope": "stock",
        "category": "财务指标",
        "evidence_key": "financials_q3",
        "title": "贵州茅台季度净利润稳定增长",
        "value_json": {"net_profit_yoy": "+15.2%", "gross_margin": "91.8%"},
        "source": "mootdx_finance",
        "source_module": "mootdx_finance",
        "quality_status": "valid",
        "observed_at": "2026-07-29T09:30:00Z",
        "observation_time": "2026-07-29T09:30:00Z",
        "created_at": "2026-07-29T10:00:05.000000Z",
    },
    {
        "evidence_id": "ev_market_sentiment",
        "decision_run_id": run_id,
        "code": "600519",
        "scope": "market",
        "category": "大盘情绪",
        "evidence_key": "market_flow",
        "title": "白酒板块资金小幅净流入",
        "value_json": {"main_net_inflow_yi": 3.45},
        "source": "market_flow",
        "source_module": "market_flow",
        "quality_status": "valid",
        "observed_at": "2026-07-29T09:45:00Z",
        "observation_time": "2026-07-29T09:45:00Z",
        "created_at": "2026-07-29T10:00:05.000000Z",
    }
]

explanation_items = [
    {
        "explanation_id": "exp_600519_thesis",
        "decision_run_id": run_id,
        "code": "600519",
        "claim": "贵州茅台高端白酒竞争优势稳固",
        "conclusion": "维持持有评级",
        "conclusion_type": "holding_action",
        "conclusion_value": "hold",
        "explanation_text": "维持持有评级：公司三季报毛利率维持 90% 以上，品牌壁垒高，市场资金面充沛。",
        "supporting_evidence_ids": ["ev_600519_financials", "ev_market_sentiment"],
        "limiting_evidence_ids": [],
        "reasoning": "公司三季报毛利率维持 90% 以上，品牌壁垒高，市场资金面充沛。",
        "confidence_score": 0.92,
        "created_at": "2026-07-29T10:00:05.000000Z",
    }
]

store.save_decision_run_bundle(run_rec, evidence_items, explanation_items, db_path=db_file)
print("seeded successfully with run_id:", run_id)
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
      if (code !== 0) reject(new Error(`seed decision trace db failed: ${err || code}`));
      else resolve();
    });
  });
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error(
      `Frontend dist not found: ${frontendDist}. Run 'npm run build' first.`
    );
  }

  const tempDir = mkdtempSync(join(tmpdir(), "vr-decision-evidence-e2e-"));
  const decisionDb = join(tempDir, "decision_trace.sqlite3");

  const env = {
    VR_DATA_DIR: tempDir,
    VIBE_RESEARCH_DECISION_TRACE_DB: decisionDb,
  };

  await seedDecisionTraceData(decisionDb, env);

  const backendPort = await getFreePort();
  const frontendPort = await getFreePort();
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const apiUrl = `http://127.0.0.1:${backendPort}`;

  let backend;
  let browser;
  let frontendServer;

  try {
    console.log("[E2E] Starting FastAPI backend...");
    backend = await startBackend(env, backendPort);
    await waitHttp(`${apiUrl}/api/health`);

    console.log("[E2E] Direct API test GET /api/decision-evidence");
    const listRes = await fetch(`${apiUrl}/api/decision-evidence?code=600519`);
    if (!listRes.ok) throw new Error(`GET /api/decision-evidence HTTP ${listRes.status}`);
    const listJson = await listRes.json();
    console.log("[E2E] API list items count:", listJson.data?.items?.length);

    console.log("[E2E] Starting static frontend server...");
    frontendServer = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(baseUrl);

    console.log("[E2E] Launching Chromium browser...");
    browser = await chromium.launch({
      headless: true,
      executablePath: findChromium(),
    });
    const context = await browser.newContext({ baseURL: baseUrl });
    const page = await context.newPage();

    // Proxy API calls from browser to real backend port
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

    console.log("[E2E] Navigate to /decision-evidence");
    await page.goto("/decision-evidence", { waitUntil: "networkidle" });

    await page.waitForSelector("h1:has-text('决策依据')", { timeout: 15000 });
    console.log("[E2E] Page Header verified");

    await page.waitForSelector("td:has-text('600519')", { timeout: 15000 });
    console.log("[E2E] Table item 600519 displayed");

    // Click "查看详情"
    await page.click("button:has-text('查看详情')");
    await page.waitForSelector("h3:has-text('决策依据与链条详情')", { timeout: 10000 });
    console.log("[E2E] Detail modal opened");

    await page.waitForSelector("text=financials_q3", { timeout: 10000 });
    await page.waitForSelector("text=维持持有评级", { timeout: 10000 });
    console.log("[E2E] Evidence card & Explanation claim verified in modal");

    // Close modal
    await page.click("button >> svg.lucide-x");
    await sleep(300);

    // Test direct advice URL query parameter auto-modal open
    console.log("[E2E] Navigate via advice query parameters...");
    await page.goto("/decision-evidence?trade_date=2026-07-29&generated_at=2026-07-29T10:00:00.000000Z", {
      waitUntil: "networkidle",
    });

    await page.waitForSelector("h3:has-text('决策依据与链条详情')", { timeout: 15000 });
    await page.waitForSelector("text=维持持有评级", { timeout: 10000 });
    console.log("[E2E] Auto-opened detail modal via advice parameters PASSED");

    console.log("==========================================");
    console.log("  ALL DECISION EVIDENCE REAL E2E TESTS PASSED!");
    console.log("==========================================");
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
      /* */
    }
  }
}

main().catch((e) => {
  console.error("[E2E] FAILED", e);
  process.exit(1);
});
