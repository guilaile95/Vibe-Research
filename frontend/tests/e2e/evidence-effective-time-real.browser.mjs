/**
 * P0-ET1 real browser vertical.
 * Uses an isolated temporary Evidence ledger, the built frontend, real FastAPI,
 * and Chromium. No mocked API responses and no user database writes.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createReadStream, existsSync, readdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "../../..");
const dist = join(root, "frontend", "dist");
const backendDir = join(root, "backend");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitHttp(url) {
  for (let i = 0; i < 100; i += 1) {
    try { const response = await fetch(url); if (response.status < 500) return; } catch { /* retry */ }
    await sleep(300);
  }
  throw new Error(`timeout waiting for ${url}`);
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

function staticServer(directory, port) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    let pathName = (request.url || "/").split("?")[0];
    if (pathName === "/") pathName = "/index.html";
    let target = join(directory, pathName);
    if (!existsSync(target)) target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

function chromiumPath() {
  const roots = [process.env.PLAYWRIGHT_CHROMIUM_PATH, join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    for (const item of readdirSync(base)) {
      if (!item.startsWith("chromium-")) continue;
      const exe = join(base, item, "chrome-win64", "chrome.exe");
      if (existsSync(exe)) return exe;
    }
  }
  return undefined;
}

function backendProcess(dbPath, port) {
  const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
  const args = process.platform === "win32"
    ? ["-3", "-m", "uvicorn", "app:app", `--port=${port}`, "--host=127.0.0.1"]
    : ["-m", "uvicorn", "app:app", `--port=${port}`, "--host=127.0.0.1"];
  const child = spawn(python, args, { cwd: backendDir, env: { ...process.env, VIBE_RESEARCH_EVIDENCE_THESIS_DB: dbPath }, stdio: ["ignore", "pipe", "pipe"], shell: false });
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { child.kill(); reject(new Error("backend startup timeout")); }, 30000);
    const ready = (chunk) => {
      if (chunk.includes("Application startup complete") || chunk.includes("Uvicorn running")) {
        clearTimeout(timeout); resolve(child);
      }
    };
    child.stdout.on("data", (data) => ready(data.toString()));
    child.stderr.on("data", (data) => ready(data.toString()));
    child.on("error", reject);
  });
}

async function createEvidence(page, suffix) {
  await page.goto("/evidence/new");
  await page.locator('input[placeholder*="600519"]').fill("600519");
  await page.locator("textarea").fill(`ET1 ${suffix}`);
  await page.locator('input[placeholder*="XX公司"]').fill(`ET1 source ${suffix}`);
  await page.locator('input[type="date"]').fill("2025-01-01");
  await page.getByRole("button", { name: /保存/ }).click();
  await page.waitForURL(/\/evidence\/[a-f0-9]+$/);
}

async function main() {
  if (!existsSync(dist)) throw new Error(`frontend dist not found: ${dist}`);
  const temp = mkdtempSync(join(tmpdir(), "vr-et1-e2e-"));
  const dbPath = join(temp, "evidence_thesis.db");
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const apiUrl = `http://127.0.0.1:${backendPort}`;
  const frontendUrl = `http://127.0.0.1:${frontendPort}`;
  let backend;
  let frontend;
  let browser;
  try {
    backend = await backendProcess(dbPath, backendPort);
    await waitHttp(`${apiUrl}/api/health`);
    frontend = await staticServer(dist, frontendPort);
    browser = await chromium.launch({ headless: true, executablePath: chromiumPath() });
    const context = await browser.newContext({ baseURL: frontendUrl });
    const page = await context.newPage();
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const parsed = new URL(request.url());
      const upstream = await fetch(`${apiUrl}${parsed.pathname}${parsed.search}`, {
        method: request.method(),
        headers: { ...request.headers(), host: undefined },
        body: request.postDataBuffer() || undefined,
      });
      await route.fulfill({ status: upstream.status, headers: Object.fromEntries(upstream.headers.entries()), body: Buffer.from(await upstream.arrayBuffer()) });
    });

    await createEvidence(page, "proven");
    await page.getByLabel("Source identity").fill("wire:et1-proven");
    await page.getByLabel("Source published at").fill("2025-01-01T08:00");
    await page.getByRole("button", { name: /保存 factual temporal metadata/ }).click();
    await page.getByText("已证明").waitFor();
    if (!(await page.getByText("来源发布时间").count())) throw new Error("proven basis not visible");
    await page.reload();
    await page.getByText("已证明").waitFor();
    if (!(await page.getByText("Observed time is not effective time.").count())) throw new Error("temporal distinction not visible after refresh");

    await createEvidence(page, "observed-only");
    await page.getByLabel("Observed at").fill("2025-01-02T08:00");
    await page.getByRole("button", { name: /保存 factual temporal metadata/ }).click();
    await page.getByText("未证明").waitFor();
    if (!(await page.getByText("无权威时间").count())) throw new Error("observed-only basis not visible");
    console.log("ET1 real browser vertical passed");
  } finally {
    if (browser) await browser.close();
    if (frontend) frontend.close();
    if (backend) backend.kill();
  }
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
