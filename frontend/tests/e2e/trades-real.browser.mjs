/**
 * 交易流水 — Real FastAPI Backend Playwright E2E Test
 *
 * 开启真实 FastAPI 后端与前端服务，使用独立临时数据目录（VR_DATA_DIR）。
 * 绝不污染真实 SQLite、portfolio.json 或工作区。
 * 覆盖主链路（创建 not_executed -> 查看详情 -> 作废 -> 筛选包含作废）与错误链路（409 重复作废）。
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
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-trades-e2e-"));
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

    // 1. 打开 /trades
    console.log("[E2E] 1. Opening /trades page...");
    await page.goto(`http://127.0.0.1:${frontendPort}/trades`, { waitUntil: "networkidle" });

    // 确认页面载入与空状态
    await page.waitForSelector("text=交易流水");
    const emptyText = await page.locator("text=暂无交易流水").isVisible();
    assert.ok(emptyText, "Initial list should be empty");

    // 2. 创建一条 not_executed 交易
    console.log("[E2E] 2. Creating a not_executed trade...");
    await page.click("button:has-text('新建交易')");
    await page.waitForSelector("text=新建交易流水");

    const modalForm = page.locator("div.fixed form");
    await modalForm.locator("input[placeholder*='6位数字']").fill("600519");
    await modalForm.locator("input[placeholder*='贵州茅台']").fill("贵州茅台");

    // 操作类型: buy
    const modalOpSelect = modalForm.locator("label:has-text('操作类型') + select");
    await modalOpSelect.selectOption("buy");

    // 执行状态: not_executed
    const modalStatusSelect = modalForm.locator("label:has-text('执行状态') + select");
    await modalStatusSelect.selectOption("not_executed");

    // 确认实际成交字段已被隐藏（not_executed 状态防护）
    await page.waitForSelector("label:has-text('实际价格')", { state: "detached" });
    const actualPriceVisible = await page.locator("label:has-text('实际价格')").isVisible();
    assert.equal(actualPriceVisible, false, "actual_price label should be detached for not_executed");

    await modalForm.locator("textarea[placeholder*='未执行或部分执行的原因']").fill("等待回调至 1600 买入");
    await modalForm.locator("textarea[placeholder*='交易备注']").fill("E2E 自动化测试交易点位");

    await modalForm.locator("button:has-text('提交创建')").click();

    // 3. 确认交易出现在列表中
    console.log("[E2E] 3. Verifying trade appears in the list...");
    await page.waitForSelector("text=交易流水创建成功");
    await page.waitForSelector("td:has-text('贵州茅台')");
    await page.waitForSelector("td:has-text('未执行')");

    // 4. 打开交易详情并核对关键字段
    console.log("[E2E] 4. Opening trade detail modal...");
    await page.click("td button:has-text('详情')");
    await page.waitForSelector("text=交易流水详情");
    await page.waitForSelector("text=等待回调至 1600 买入");

    // 获取 trade_id
    const idText = await page.locator("text=/ID: [a-f0-9-]+/").innerText();
    const tradeId = idText.replace("ID: ", "").trim();
    console.log(`[E2E] Created trade_id = ${tradeId}`);

    // 关闭详情
    await page.click("button:has-text('关闭')");

    // 5. 作废交易
    console.log("[E2E] 5. Voiding trade...");
    await page.click("td button:has-text('作废')");
    await page.waitForSelector("text=作废交易确认");
    await page.fill("textarea[placeholder*='请输入作废原因']", "因大盘趋势变化取消挂单");
    await page.click("button:has-text('确认作废')");

    await page.waitForSelector("text=交易已成功作废");

    // 默认列表不包含作废记录，列表重归为空
    await page.waitForSelector("text=暂无交易流水");

    // 6. 启用“包含作废记录”并确认记录显示为已作废
    console.log("[E2E] 6. Enabling 'include_voided' filter...");
    await page.check("label:has-text('包含作废记录') input");
    await page.click("button:has-text('筛选')");

    await page.waitForSelector("td:has-text('贵州茅台')");
    await page.waitForSelector("td:has-text('已作废')");

    // 7. 错误链路测试：对已作废记录二次作废，确认 API / UI 返回 409
    console.log("[E2E] 7. Testing 409 conflict error path...");
    const res = await fetch(`http://127.0.0.1:${backendPort}/api/trades/${encodeURIComponent(tradeId)}/void`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "重复作废测试" }),
    });

    assert.equal(res.status, 409, "Duplicate void should return HTTP 409");
    const json = await res.json();
    assert.equal(json.detail, "交易记录已作废");

    console.log("[E2E] SUCCESS: All trade ledger E2E requirements passed!");
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
      /* ignore cleanup error */
    }
  }
}

runE2E().catch((err) => {
  console.error("[E2E] FAILED:", err);
  process.exit(1);
});
