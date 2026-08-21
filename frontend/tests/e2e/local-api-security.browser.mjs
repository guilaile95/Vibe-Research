/**
 * Browser-level local API boundary smoke.
 *
 * It uses the product's exact supported frontend Origins without touching user
 * data: localhost:5899 and 127.0.0.1:5899 can read the local API response,
 * while a random attacker Origin cannot read or execute a private API request.
 */

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";


const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../../..");
const backendDir = path.join(repoRoot, "backend");


function resolvePython() {
  const configured = process.env.VR_TEST_PYTHON;
  const candidates = configured
    ? [[configured, []]]
    : process.platform === "win32"
      ? [["py", ["-3.12"]], ["py", ["-3"]], ["python", []]]
      : [["python3", []], ["python", []]];
  for (const [command, prefix] of candidates) {
    const check = spawnSync(command, [...prefix, "-c", "import fastapi,uvicorn"], {
      cwd: backendDir,
      stdio: "ignore",
      windowsHide: true,
    });
    if (check.status === 0) return { command, prefix };
  }
  throw new Error("No Python runtime with FastAPI and Uvicorn is available");
}


function listen(server, port) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", reject);
      resolve(server.address().port);
    });
  });
}


function closeServer(server) {
  if (!server.listening) return Promise.resolve();
  return new Promise((resolve) => server.close(resolve));
}


async function reservePort() {
  const server = createServer();
  const port = await listen(server, 0);
  await closeServer(server);
  return port;
}


async function waitForHealth(url, backend) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (backend.exitCode !== null) {
      throw new Error(`Backend exited early with code ${backend.exitCode}`);
    }
    try {
      const response = await fetch(`${url}/api/health`);
      if (response.ok) return;
    } catch {
      // Startup race; retry until the bounded deadline.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for the local API health endpoint");
}


async function stopProcess(processHandle) {
  if (!processHandle || processHandle.exitCode !== null) return;
  processHandle.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => processHandle.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 3_000)),
  ]);
  if (processHandle.exitCode === null) {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(processHandle.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      });
    } else {
      processHandle.kill("SIGKILL");
    }
  }
}


const pageHtml = Buffer.from("<!doctype html><meta charset=utf-8><title>Origin fixture</title>");
const trustedServer = createServer((_request, response) => {
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(pageHtml);
});
const attackerServer = createServer((_request, response) => {
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(pageHtml);
});

let backend;
let browser;
let tempData;

try {
  await listen(trustedServer, 5899);
  const attackerPort = await listen(attackerServer, 0);
  const backendPort = await reservePort();
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const attackerOrigin = `http://127.0.0.1:${attackerPort}`;
  tempData = await mkdtemp(path.join(os.tmpdir(), "vibe-research-security-e2e-"));

  const python = resolvePython();
  const env = {
    ...process.env,
    VR_DATA_DIR: tempData,
    VR_REPORTS_DIR: path.join(tempData, "reports"),
    VIBE_RESEARCH_DATA_DIR: tempData,
    VIBE_RESEARCH_REVIEW_DB: path.join(tempData, "review.db"),
    VIBE_RESEARCH_EVIDENCE_THESIS_DB: path.join(tempData, "evidence-thesis.db"),
  };
  delete env.VR_ALLOW_ORIGINS;
  delete env.VR_TRUSTED_HOSTS;
  delete env.VR_API_KEY;
  backend = spawn(
    python.command,
    [...python.prefix, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
    { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
  );
  await waitForHealth(backendUrl, backend);

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  for (const frontendUrl of ["http://localhost:5899", "http://127.0.0.1:5899"]) {
    await page.goto(frontendUrl);
    const result = await page.evaluate(async (url) => {
      const response = await fetch(`${url}/api/quote?codes=abc`);
      return { status: response.status, text: await response.text() };
    }, backendUrl);
    assert.equal(result.status, 400, frontendUrl);
    assert.match(result.text, /6/);
  }

  await page.goto(attackerOrigin);
  const attackerResult = await page.evaluate(async (url) => {
    try {
      const response = await fetch(`${url}/api/portfolio`);
      return { rejected: false, status: response.status, text: await response.text() };
    } catch (error) {
      return { rejected: true, name: error?.name ?? "Error" };
    }
  }, backendUrl);
  assert.deepEqual(attackerResult, { rejected: true, name: "TypeError" });

  const hostileResponse = await fetch(`${backendUrl}/api/portfolio`, {
    headers: { Origin: attackerOrigin },
  });
  assert.equal(hostileResponse.status, 403);
  assert.equal(hostileResponse.headers.get("access-control-allow-origin"), null);
  assert.deepEqual(await hostileResponse.json(), { detail: "Origin not allowed" });

  console.log("local API browser security smoke: PASS");
} finally {
  if (browser) await browser.close();
  await stopProcess(backend);
  await Promise.all([closeServer(trustedServer), closeServer(attackerServer)]);
  if (tempData) await rm(tempData, { recursive: true, force: true });
}
