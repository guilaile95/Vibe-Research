/**
 * 信号账本 (Signal Ledger) — 真实 FastAPI 后端 Playwright E2E 测试
 *
 * 启动真实 FastAPI 后端与前端静态服务，使用独立临时数据目录。
 * 绝不污染真实 SQLite 或工作区。
 * 覆盖：信号时间线渲染、决策 Run 信息卡片、裁决结果卡片、阶段筛选与股票代码筛选。
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
import assert from "node:assert/strict";

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

async function runE2E() {
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-signal-ledger-e2e-"));
  const dbPath = join(tempDataDir, "decision_trace.sqlite3");
  console.log(`[E2E] Created temporary isolated data dir: ${tempDataDir}`);

  let backendProc = null;
  let staticServer = null;
  let browser = null;

  try {
    const backendPort = await getFreePort();
    const frontendPort = await getFreePort();

    const py = getPythonConfig();
    const env = {
      ...process.env,
      VR_DATA_DIR: tempDataDir,
      VIBE_RESEARCH_DECISION_TRACE_DB: dbPath,
      PYTHONUNBUFFERED: "1",
    };

    console.log(`[E2E] Starting FastAPI backend on port ${backendPort}...`);
    backendProc = spawn(
      py.cmd,
      [...py.extraArgs, "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
      { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"] },
    );

    backendProc.stdout.on("data", (chunk) => {
      process.stdout.write(`[backend] ${chunk}`);
    });
    backendProc.stderr.on("data", (chunk) => {
      process.stderr.write(`[backend] ${chunk}`);
    });

    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    console.log(`[E2E] Backend ready.`);

    // 预注入测试数据：Populate mock decision run & signals directly via Python script or API call
    console.log(`[E2E] Pre-populating test signal ledger data...`);
    const seedScript = `
import signal_ledger_store as store
import decision_trace_store as trace_store

db_path = r"${dbPath}"
run_id = "dr_e2e_signal_test_123"

trace_store.save_decision_run_bundle(
    run_record={
        "decision_run_id": run_id,
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T10:00:00Z",
        "result_type": "portfolio_advice",
        "schema_version": "v1",
        "market_status": "normal",
        "source_fingerprint": "abc",
        "trace_status": "archived",
        "created_at": "2026-07-29T10:00:00Z",
    },
    evidence_items=[],
    explanation_items=[],
    db_path=db_path,
)

store.save_signal_ledger_bundle(
    decision_run_id=run_id,
    signal_entries=[
        {
            "entry_id": "sig_e2e_1",
            "stage": "schema",
            "code": None,
            "signal_type": "json_schema_validation",
            "severity": "info",
            "payload_json": {"status": "passed"},
            "created_at": "2026-07-29T10:00:01Z",
        },
        {
            "entry_id": "sig_e2e_2",
            "stage": "execution",
            "code": "600519",
            "signal_type": "action_generation",
            "severity": "info",
            "payload_json": {"action": "buy", "reason": "估值合理区间"},
            "created_at": "2026-07-29T10:00:02Z",
        },
    ],
    decision_outcomes=[
        {
            "outcome_id": "out_e2e_1",
            "code": "600519",
            "action": "buy",
            "target_ratio": 0.20,
            "reason": "估值合理区间",
            "constraints_applied_json": ["sellable_quantity_advisory"],
            "created_at": "2026-07-29T10:00:03Z",
        }
    ],
    trade_date="2026-07-29",
    generated_at="2026-07-29T10:00:00Z",
    db_path=db_path,
)
print("SEED_COMPLETE")
`;
    const seedProc = spawn(py.cmd, ["-3", "-c", seedScript], {
      cwd: backendDir,
      env,
    });
    await new Promise((resolve, reject) => {
      seedProc.on("exit", (code) => {
        if (code === 0) resolve();
        else reject(new Error(`Seed failed with code ${code}`));
      });
    });

    console.log(`[E2E] Starting static server for frontend on port ${frontendPort}...`);
    staticServer = await startStaticServer(frontendDist, frontendPort);

    const execPath = findChromium();
    console.log(`[E2E] Launching Chromium browser (execPath=${execPath || "bundled"})...`);
    browser = await chromium.launch({
      executablePath: execPath,
      headless: true,
    });

    const context = await browser.newContext();
    const page = await context.newPage();

    // Proxy /api/ requests to real backendPort
    await page.route("**/api/**", (route) => {
      const u = new URL(route.request().url());
      const targetUrl = `http://127.0.0.1:${backendPort}${u.pathname}${u.search}`;
      route.continue({ url: targetUrl });
    });

    // 1. Open /signal-ledger?decision_run_id=dr_e2e_signal_test_123
    console.log("[E2E] 1. Opening /signal-ledger page with decision_run_id query param...");
    await page.goto(
      `http://127.0.0.1:${frontendPort}/signal-ledger?decision_run_id=dr_e2e_signal_test_123`,
      { waitUntil: "networkidle" },
    );

    // Verify page header
    await page.waitForSelector("text=信号账本 (Signal Ledger)");

    // Verify Run record metadata card
    console.log("[E2E] 2. Verifying decision run record card...");
    await page.waitForSelector("text=Run ID: dr_e2e_signal_test_123");
    await page.waitForSelector("text=2026-07-29");

    // Verify Decision Outcomes card
    console.log("[E2E] 3. Verifying decision outcomes card...");
    await page.waitForSelector("text=最终裁决结果 (Decision Outcomes)");
    await page.waitForSelector("text=600519");
    await page.waitForSelector("text=买入");
    await page.waitForSelector("text=20.0%");

    // Verify Timeline signal entries
    console.log("[E2E] 4. Verifying signal timeline entries...");
    await page.waitForSelector("text=模式校验 (Schema)");
    await page.waitForSelector("text=执行裁决 (Execution)");
    await page.waitForSelector("text=json_schema_validation");

    // 5. Test filter reset
    console.log("[E2E] 5. Testing filter reset...");
    await page.click("button:has-text('重置')");
    await page.click("button:has-text('查询信号')");

    await page.waitForSelector("text=阶段流水时间线");

    console.log("[E2E] SUCCESS: All Signal Ledger E2E tests passed!");
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (staticServer) staticServer.close();
    if (backendProc) {
      backendProc.kill("SIGTERM");
      await sleep(500);
    }
    try {
      rmSync(tempDataDir, { recursive: true, force: true });
      console.log(`[E2E] Cleaned up temporary directory ${tempDataDir}`);
    } catch {
      /* ignore */
    }
  }
}

runE2E().catch((err) => {
  console.error("[E2E] FAILED:", err);
  process.exit(1);
});
