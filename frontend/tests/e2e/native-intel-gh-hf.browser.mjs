/** One browser scenario: GitHub Trending rank+metric and HF papers no fake rank + metric. */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const backendDir = join(root, "backend");
const frontendDist = join(root, "frontend", "dist");
const tempDir = mkdtempSync(join(tmpdir(), "vr-native-intel-gh-hf-"));

const freePort = () =>
  new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const pythonArgs = process.env.PYTHON
  ? ["-m", "uvicorn"]
  : process.platform === "win32"
    ? ["-3", "-m", "uvicorn"]
    : ["-m", "uvicorn"];

function chromiumPath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_PATH)) {
    return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  }
  for (const base of [
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ]) {
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base)) {
      for (const candidate of [
        join(base, entry, "chrome-win64", "chrome.exe"),
        join(base, entry, "chrome-linux", "chrome"),
      ]) {
        if (existsSync(candidate)) return candidate;
      }
    }
  }
  return undefined;
}

async function launchBrowser() {
  const executablePath = chromiumPath();
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

async function waitHttp(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* starting */
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function staticServer(directory, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let target = join(
      directory,
      (request.url || "/").split("?")[0] === "/" ? "index.html" : (request.url || "/").split("?")[0],
    );
    if (!existsSync(target)) target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    import("node:fs").then(({ createReadStream }) => createReadStream(target).pipe(response));
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

let backend;
let frontend;
let browser;
try {
  assert.ok(existsSync(join(frontendDist, "index.html")), "frontend must be built first");
  const backendPort = await freePort();
  const frontendPort = await freePort();
  backend = spawn(
    python,
    [
      ...pythonArgs,
      "--app-dir",
      join(root, "frontend", "tests", "e2e"),
      "native_intel_gh_hf_harness_app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
    ],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        PYTHONPATH: `${backendDir}${path.delimiter}${join(root, "frontend", "tests", "e2e")}`,
        VIBE_NATIVE_INTEL_DB: join(tempDir, "native-intel.sqlite3"),
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  await waitHttp(`http://127.0.0.1:${backendPort}/api/native-intel/status`);
  frontend = await staticServer(frontendDist, frontendPort);
  browser = await launchBrowser();
  const page = await browser.newPage();
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const response = await fetch(`http://127.0.0.1:${backendPort}${url.pathname}${url.search}`, {
      method: route.request().method(),
    });
    await route.fulfill({
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: Buffer.from(await response.arrayBuffer()),
    });
  });
  await page.goto(`http://127.0.0.1:${frontendPort}/intel`, { waitUntil: "domcontentloaded" });
  const intelTab = page.getByRole("button", { name: "实时热榜" });
  await intelTab.waitFor({ state: "visible", timeout: 15000 });
  await intelTab.click();
  await page.getByText("openai/whisper").waitFor({ timeout: 15000 });
  await page.getByTestId("intel-source-facts-github").waitFor({ state: "visible", timeout: 15000 });
  const ghFacts = await page.getByTestId("intel-source-facts-github").innerText();
  assert.match(ghFacts, /1234|80123|Python/);
  await page.getByText("Scaling Laws for Neural Language Models").waitFor({ timeout: 15000 });
  await page.getByTestId("intel-source-facts-hf").waitFor({ state: "visible", timeout: 15000 });
  const hfFacts = await page.getByTestId("intel-source-facts-hf").innerText();
  assert.match(hfFacts, /42/);
  await page.getByText("Show HN: Example").waitFor({ timeout: 15000 });
  await page.getByTestId("intel-source-facts-hn").waitFor({ state: "visible", timeout: 15000 });
  const hnFacts = await page.getByTestId("intel-source-facts-hn").innerText();
  assert.match(hnFacts, /321/);
  assert.match(hnFacts, /87/);
  console.log("Native Intel GitHub Trending + HF Daily Papers + HN: PASS");
} finally {
  if (browser) await browser.close();
  if (frontend) frontend.close();
  if (backend) backend.kill("SIGTERM");
}
