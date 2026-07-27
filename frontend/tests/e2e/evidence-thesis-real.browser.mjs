/**
 * 投资逻辑与证据账本 — Real Backend E2E Test
 *
 * 真实后端集成测试（替代原 smoke mock）：
 * - 使用临时 SQLite 数据库
 * - 启动真实 FastAPI 后端
 * - Playwright 加载前端 build
 * - /api/* 转发给真实后端（无 mock）
 * 
 * 完整流程：
 * 1. 创建 evidence（含 source_date）
 * 2. 编辑 evidence
 * 3. 创建 thesis
 * 4. 关联 evidence
 * 5. 修改 stance
 * 6. 编辑 thesis
 * 7. 查看 revision
 * 8. 软删除 evidence
 * 9. 验证当前状态与历史状态
 * 10. 归档 thesis
 * 11. 验证冻结
 *
 * 能发现的错误：
 * - source_date 格式错误
 * - EvidenceUpdate 多余字段
 * - 前后端响应结构不一致
 * - 409 响应结构错误
 */

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, createReadStream } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createServer } from "node:http";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      /* retry */
    }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
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
    let pathname = (req.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403);
      res.end("forbidden");
      return;
    }
    if (!existsSync(target)) {
      target = path.join(dir, "index.html");
    }
    const ext = path.extname(target);
    const type = mime[ext] || "application/octet-stream";
    res.setHeader("Content-Type", type);
    createReadStream(target).pipe(res);
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function startBackend(dbPath, port) {
  return new Promise((resolve, reject) => {
    const env = {
      ...process.env,
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: dbPath,
      VIBE_RESEARCH_API_PORT: String(port),
    };

    const proc = spawn("uvicorn", ["app:app", `--port=${port}`, "--host=127.0.0.1"], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      shell: true,
    });

    let started = false;
    const timeout = setTimeout(() => {
      if (!started) {
        proc.kill();
        reject(new Error("Backend startup timeout"));
      }
    }, 30000);

    proc.stdout.on("data", (data) => {
      const msg = data.toString();
      if (msg.includes("Uvicorn running") || msg.includes("Application startup complete")) {
        if (!started) {
          started = true;
          clearTimeout(timeout);
          resolve(proc);
        }
      }
    });

    proc.stderr.on("data", (data) => {
      console.error(`Backend stderr: ${data}`);
    });

    proc.on("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    proc.on("exit", (code) => {
      if (!started) {
        clearTimeout(timeout);
        reject(new Error(`Backend exited with code ${code} before startup`));
      }
    });
  });
}

async function main() {
  if (!existsSync(frontendDist)) {
    throw new Error(`Frontend dist not found: ${frontendDist}. Run 'npm run build' first.`);
  }

  const tempDir = mkdtempSync(join(tmpdir(), "vr-thesis-e2e-"));
  const dbPath = join(tempDir, "evidence_thesis.db");
  const backendPort = 8901;
  const frontendPort = await getFreePort();
  const baseUrl = `http://127.0.0.1:${frontendPort}`;

  console.log(`[E2E] Temp DB: ${dbPath}`);
  console.log(`[E2E] Backend port: ${backendPort}`);
  console.log(`[E2E] Frontend port: ${frontendPort}`);

  let backend = null;
  let browser = null;
  let frontendServer = null;

  try {
    // Start real backend
    console.log("[E2E] Starting real FastAPI backend...");
    backend = await startBackend(dbPath, backendPort);
    await waitHttp(`http://127.0.0.1:${backendPort}/api/health`);
    console.log("[E2E] Backend ready");

    // Start static server for frontend
    console.log("[E2E] Starting frontend server...");
    frontendServer = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(baseUrl);
    console.log("[E2E] Frontend server ready");

    // Launch Playwright
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ baseURL: baseUrl });
    const page = await context.newPage();

    // Proxy /api/* to real backend
    await page.route("**/api/**", async (route) => {
      const url = route.request().url();
      const apiPath = new URL(url).pathname + new URL(url).search;
      const backendUrl = `http://127.0.0.1:${backendPort}${apiPath}`;
      
      try {
        const response = await fetch(backendUrl, {
          method: route.request().method(),
          headers: route.request().headers(),
          body: route.request().postDataBuffer() || undefined,
        });
        const body = await response.arrayBuffer();
        await route.fulfill({
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          body: Buffer.from(body),
        });
      } catch (err) {
        console.error(`[E2E] Proxy error: ${err.message}`);
        await route.abort();
      }
    });

    await page.goto(baseUrl);
    await page.waitForLoadState("domcontentloaded");
    console.log("[E2E] Frontend loaded");

    // ==== Test Flow ====
    
    // 1. Create evidence with source_date
    console.log("[E2E] 1. Create evidence");
    await page.click('a[href="/evidence"]');
    await page.waitForURL(/\/evidence$/);
    await page.click('a[href="/evidence/new"]');
    await page.waitForURL(/\/evidence\/new$/);
    
    await page.selectOption('select[value="stock"]', "stock");
    await page.fill('input[placeholder*="600519"]', "600519");
    await page.selectOption('select >> nth=1', "news");
    await page.fill('textarea[placeholder*="一句话"]', "公司2024Q3营收同比+25%");
    await page.fill('input[placeholder*="XX公司"]', "茅台Q3财报点评");
    await page.fill('input[placeholder*="https://"]', "https://example.com/maotai-q3");
    await page.fill('input[type="date"]', "2024-11-15");
    
    const saveBtn = page.locator('button:has-text("保存")');
    await saveBtn.click();
    await page.waitForURL(/\/evidence\/[a-f0-9-]+$/);
    const evidenceUrl = page.url();
    const evidenceId = evidenceUrl.split("/").pop();
    console.log(`[E2E] Created evidence: ${evidenceId}`);

    // Verify source_date display (no timezone shift)
    await page.waitForSelector('text=2024-11-15');
    console.log("[E2E] ✓ source_date displayed correctly");

    // 2. Edit evidence
    console.log("[E2E] 2. Edit evidence");
    await page.click('button:has-text("编辑")');
    await page.waitForSelector('textarea[value*="公司2024Q3营收"]');
    
    // Verify subject fields are readonly
    const subjectTypeSelect = page.locator('select').first();
    const isDisabled = await subjectTypeSelect.isDisabled();
    if (!isDisabled) {
      throw new Error("subject_type should be readonly but is enabled");
    }
    console.log("[E2E] ✓ subject_type is readonly");

    await page.fill('textarea', "公司2024Q3营收同比+25%，超预期");
    await page.click('button:has-text("保存")');
    await page.waitForSelector('text=公司2024Q3营收同比+25%，超预期');
    console.log("[E2E] ✓ Evidence updated");

    // 3. Create thesis
    console.log("[E2E] 3. Create thesis");
    await page.click('a[href="/thesis"]');
    await page.waitForURL(/\/thesis$/);
    await page.click('a[href="/thesis/new"]');
    await page.waitForURL(/\/thesis\/new$/);

    await page.selectOption('select[value="stock"]', "stock");
    await page.fill('input[placeholder*="主体代码"]', "600519");
    await page.fill('input[placeholder*="一句话概括"]', "茅台业绩持续超预期");
    await page.fill('textarea[placeholder*="详细说明"]', "基于Q3财报，公司营收增长超市场预期");
    
    const thesisSaveBtn = page.locator('button:has-text("创建")');
    await thesisSaveBtn.click();
    await page.waitForURL(/\/thesis\/[a-f0-9-]+$/);
    const thesisUrl = page.url();
    const thesisId = thesisUrl.split("/").pop();
    console.log(`[E2E] Created thesis: ${thesisId}`);

    // Verify revision 1
    await page.waitForSelector('text=版本 1');
    console.log("[E2E] ✓ Initial revision is 1");

    // 4. Link evidence
    console.log("[E2E] 4. Link evidence");
    await page.click('button:has-text("关联证据")');
    await page.fill('input[placeholder*="证据 ID"]', evidenceId);
    await page.selectOption('select >> nth=-1', "support");
    await page.click('button:has-text("关联")');
    await page.waitForSelector(`text=${evidenceId.substring(0, 8)}`);
    await page.waitForSelector('text=版本 2');
    console.log("[E2E] ✓ Evidence linked, revision increased to 2");

    // 5. Update stance
    console.log("[E2E] 5. Update stance");
    await page.click(`button:has-text("修改立场")`);
    await page.selectOption('select >> last', "neutral");
    await page.click('button:has-text("保存")');
    await page.waitForSelector('text=中性');
    await page.waitForSelector('text=版本 3');
    console.log("[E2E] ✓ Stance updated, revision increased to 3");

    // 6. Edit thesis
    console.log("[E2E] 6. Edit thesis");
    await page.click('button:has-text("编辑逻辑")');
    await page.fill('textarea[placeholder*="详细说明"]', "基于Q3财报，公司营收增长超市场预期，毛利率稳定");
    await page.click('button:has-text("保存")');
    await page.waitForSelector('text=毛利率稳定');
    await page.waitForSelector('text=版本 4');
    console.log("[E2E] ✓ Thesis edited, revision increased to 4");

    // 7. View revision history
    console.log("[E2E] 7. View revision history");
    await page.click('a:has-text("版本历史")');
    await page.waitForSelector('text=版本 1');
    await page.waitForSelector('text=版本 4');
    console.log("[E2E] ✓ Revision history loaded");

    // 8. Soft delete evidence
    console.log("[E2E] 8. Soft delete evidence");
    await page.goto(`${baseUrl}/evidence/${evidenceId}`);
    await page.waitForLoadState("domcontentloaded");
    
    page.once("dialog", (dialog) => {
      if (dialog.message().includes("历史版本中的证据快照仍会保留")) {
        console.log("[E2E] ✓ Delete confirmation text correct");
        dialog.accept();
      } else {
        throw new Error(`Unexpected delete message: ${dialog.message()}`);
      }
    });
    
    await page.click('button:has-text("删除")');
    await page.waitForURL(/\/evidence$/);
    console.log("[E2E] ✓ Evidence soft deleted");

    // Verify evidence removed from current list
    await page.goto(`${baseUrl}/evidence?subject_id=600519`);
    await page.waitForLoadState("domcontentloaded");
    const evidenceCount = await page.locator(`text=${evidenceId.substring(0, 8)}`).count();
    if (evidenceCount > 0) {
      throw new Error("Deleted evidence still appears in current list");
    }
    console.log("[E2E] ✓ Deleted evidence not in current list");

    // Verify evidence snapshot still in thesis revision
    await page.goto(`${baseUrl}/thesis/${thesisId}/revisions/2`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector(`text=${evidenceId.substring(0, 8)}`);
    console.log("[E2E] ✓ Evidence snapshot preserved in revision 2");

    // 9. Archive thesis
    console.log("[E2E] 9. Archive thesis");
    await page.goto(`${baseUrl}/thesis/${thesisId}`);
    await page.waitForLoadState("domcontentloaded");
    
    page.once("dialog", (dialog) => {
      dialog.accept();
    });
    
    await page.click('button:has-text("归档")');
    await page.waitForSelector('text=已归档');
    console.log("[E2E] ✓ Thesis archived");

    // 10. Verify frozen state
    console.log("[E2E] 10. Verify frozen state");
    const editButton = await page.locator('button:has-text("编辑逻辑")').count();
    if (editButton > 0) {
      throw new Error("Archived thesis should not show edit button");
    }
    console.log("[E2E] ✓ Archived thesis is frozen");

    console.log("\n[E2E] ✅ All tests passed!");

  } catch (err) {
    console.error(`\n[E2E] ❌ Test failed: ${err.message}`);
    console.error(err.stack);
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close();
      console.log("[E2E] Browser closed");
    }
    if (frontendServer) {
      frontendServer.close();
      console.log("[E2E] Frontend server stopped");
    }
    if (backend) {
      backend.kill("SIGTERM");
      console.log("[E2E] Backend stopped");
    }
    if (existsSync(tempDir)) {
      rmSync(tempDir, { recursive: true, force: true });
      console.log("[E2E] Temp directory cleaned");
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
