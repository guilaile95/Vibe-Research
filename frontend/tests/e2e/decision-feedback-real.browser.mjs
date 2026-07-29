/**
 * 决策反馈 — Real FastAPI Backend Playwright E2E Test
 *
 * 开启真实 FastAPI 后端与前端服务，使用独立临时数据目录（VR_DATA_DIR）。
 * 覆盖全链路：
 * 1. 种子插入对应交易日的持仓建议 (portfolio_advice)。
 * 2. 打开 /decision-feedback 页面并确认初始空状态。
 * 3. 填写表单新建决策反馈，验证列表同步更新。
 * 4. 打开详情 Modal 查看记录详情。
 * 5. 执行作废操作并确认作废状态与作废原因展示。
 */
import { chromium } from "playwright";
import { spawn, execSync } from "node:child_process";
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

async function waitHttp(url, attempts = 100) {
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await fetch(url);
      if (r.ok || r.status < 500) return r;
    } catch {
      /* retry */
    }
    await sleep(300);
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
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-feedback-e2e-"));
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
      VR_REPORTS_DIR: tempDataDir,
      VIBE_RESEARCH_REVIEW_DB: path.join(tempDataDir, "review_history.db"),
      PYTHONUNBUFFERED: "1",
    };

    // 预填种子数据：在 review_history.db 中存入 2026-07-29 的 portfolio_advice 建议
    console.log(`[E2E] Seeding portfolio_advice in isolated environment...`);
    const seedScript = `
import json, sqlite3, os
from pathlib import Path

db_path = Path(os.environ["VR_DATA_DIR"]) / "review_history.db"
conn = sqlite3.connect(db_path)
conn.execute("""
CREATE TABLE IF NOT EXISTS ai_generated_results (
    result_type TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_fingerprint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (result_type, trade_date)
)
""")
payload = {
    "schema_version": "portfolio-advice-v0.1",
    "generated_at": "2026-07-29T08:00:00Z",
    "holdings": [{"code": "600519", "name": "贵州茅台", "action": "hold"}]
}
conn.execute("""
INSERT INTO ai_generated_results
(result_type, trade_date, schema_version, payload_json, generated_at, model_provider, model_name, created_at, updated_at)
VALUES ('portfolio_advice', '2026-07-29', 'v0.1', ?, '2026-07-29T08:00:00Z', 'mock', 'mock-model', '2026-07-29T08:00:00Z', '2026-07-29T08:00:00Z')
""", (json.dumps(payload),))
conn.commit()
conn.close()
`;
    const pyCmd = py.cmd === "py" ? "py -3" : py.cmd;
    execSync(pyCmd, { input: seedScript, env });
    console.log(`[E2E] Seeding completed.`);

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

    // 拦截前端对 /api/ 的请求，代理到真实 backendPort
    await page.route("**/api/**", (route) => {
      const u = new URL(route.request().url());
      const targetUrl = `http://127.0.0.1:${backendPort}${u.pathname}${u.search}`;
      route.continue({ url: targetUrl });
    });

    // 1. 打开 /decision-feedback
    console.log("[E2E] 1. Opening /decision-feedback page...");
    await page.goto(`http://127.0.0.1:${frontendPort}/decision-feedback`, {
      waitUntil: "networkidle",
    });

    // 确认页面载入与初始空状态
    await page.waitForSelector("text=决策反馈");
    const emptyText = await page.locator("text=未查找到决策反馈记录").isVisible();
    assert.ok(emptyText, "Initial feedback list should be empty");

    // 2. 点击新建决策反馈
    console.log("[E2E] 2. Opening Create Feedback modal...");
    await page.click("button:has-text('新建决策反馈')");
    await page.waitForSelector("text=提交创建");

    // 填表
    await page.fill("input[placeholder='6位数字']", "600519");
    await page.fill("input[type='date']", "2026-07-29");
    await page.fill("input[placeholder='如 2026-07-29T08:00:00Z']", "2026-07-29T08:00:00Z");
    await page.fill("textarea[placeholder*='决策复盘']", "E2E 自动测试决策反馈备注");

    console.log("[E2E] 3. Submitting new feedback...");
    await page.click("button:has-text('提交创建')");

    // 确认新建成功与列表出现对应代码
    await page.waitForSelector("td:has-text('600519')");
    await page.waitForSelector("td:has-text('按照建议执行')");
    await page.waitForSelector("td:has-text('符合预期')");

    // 3. 打开详情 Modal
    console.log("[E2E] 4. Opening detail modal...");
    await page.click("button:has-text('详情')");
    await page.waitForSelector("text=决策反馈详情");
    await page.waitForSelector("text=E2E 自动测试决策反馈备注");
    await page.click("button:has-text('关闭')").catch(() => {});
    await page.locator("div.fixed button").first().click();

    // 4. 执行作废
    console.log("[E2E] 5. Voiding feedback...");
    await page.click("button:has-text('作废')");
    await page.waitForSelector("text=作废决策反馈");
    await page.fill("textarea[placeholder='请输入作废原因...']", "E2E 作废测试");
    await page.click("button:has-text('确认作废')");

    // 作废后默认列表（不含作废）恢复为空状态
    await page.waitForSelector("text=未查找到决策反馈记录");

    // 勾选包含作废筛选，确认作废记录展示
    console.log("[E2E] 6. Checking include_voided filter...");
    await page.check("input[type='checkbox']");
    await page.click("button:has-text('筛选')");
    await page.waitForSelector("text=已作废");

    console.log("[E2E] Decision feedback E2E test passed successfully!");
  } finally {
    if (browser) await browser.close();
    if (staticServer) staticServer.close();
    if (backendProc) {
      backendProc.kill();
      console.log("[E2E] Terminated FastAPI backend process.");
      await sleep(500);
    }
    if (existsSync(tempDataDir)) {
      try {
        rmSync(tempDataDir, { recursive: true, force: true });
        console.log(`[E2E] Cleaned up temp data dir: ${tempDataDir}`);
      } catch {
        /* ignore Windows file lock on temp cleanup */
      }
    }
  }
}

runE2E().catch((err) => {
  console.error("[E2E] Test failed with error:", err);
  process.exit(1);
});
