/**
 * 研究记录备份真实浏览器路径：
 * localStorage 记录 → 下载 JSON → 清空浏览器记录 → 导入恢复。
 * 不启动后端，不接触 Owner 数据，也不导出密钥或 AI 对话。
 */

import assert from "node:assert/strict";
import { createReadStream, existsSync, readFileSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = join(fileURLToPath(import.meta.url), "..");
const dist = resolve(here, "../../dist");

function findChromium() {
  const roots = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  const candidates = [];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    for (const item of readdirSync(base)) {
      if (!/^chromium(_headless_shell)?-\d+$/.test(item)) continue;
      candidates.push(
        join(base, item, "chrome-win64", "chrome.exe"),
        join(base, item, "chrome-win", "chrome.exe"),
        join(base, item, "chrome-linux", "chrome"),
        join(base, item, "chrome-headless-shell-linux64", "chrome-headless-shell"),
        join(base, item, "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
        join(base, item, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      );
    }
  }
  return candidates.filter((candidate) => existsSync(candidate)).sort().at(-1);
}

function staticServer(directory, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const root = resolve(directory);
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = resolve(root, `.${pathname}`);
    if (target !== root && !target.startsWith(`${root}${sep}`)) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target) || extname(target) === "") target = join(root, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolveServer, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolveServer(server));
  });
}

async function freePort() {
  const server = createServer();
  const port = await new Promise((resolvePort, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolvePort(server.address().port));
  });
  await new Promise((resolveClose) => server.close(resolveClose));
  return port;
}

let server;
let browser;

try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html 缺失：先运行 npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  const frontend = `http://127.0.0.1:${port}`;

  browser = await chromium.launch({ headless: true, executablePath: findChromium() });
  const page = await browser.newPage();
  await page.goto(`${frontend}/notes`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    localStorage.setItem("vr-notes", JSON.stringify([{
      id: "note-backup-e2e",
      kind: "今日要点",
      title: "备份恢复验证",
      content: "这条研究记录必须可以恢复。",
      ts: 1788426000000,
    }]));
    localStorage.setItem("vr-llm", "SECRET_LLM_CONFIG");
    localStorage.setItem("vr-access-key", "SECRET_ACCESS_KEY");
    localStorage.setItem("vr-askai-chat:test", "SECRET_CHAT_HISTORY");
  });
  await page.reload({ waitUntil: "networkidle" });

  await page.getByText("研究记录只保存在当前浏览器中。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "导出备份", exact: true }).click(),
  ]);
  assert.match(download.suggestedFilename(), /^vibe-research-notes-.*\.json$/);
  const downloadPath = await download.path();
  assert.ok(downloadPath, "浏览器没有产生可读取的研究记录备份");
  const raw = readFileSync(downloadPath, "utf8");
  const payload = JSON.parse(raw);
  assert.equal(payload.schema_version, "vibe-notes.backup.v1");
  assert.equal(payload.notes.length, 1);
  assert.equal(payload.notes[0].title, "备份恢复验证");
  assert.doesNotMatch(raw, /SECRET_LLM_CONFIG|SECRET_ACCESS_KEY|SECRET_CHAT_HISTORY/);

  await page.evaluate(() => localStorage.removeItem("vr-notes"));
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText(/还没有记录/).waitFor();

  const input = page.getByTestId("notes-backup-input");
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已导入 1 条研究记录。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();

  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("没有新增记录；1 条记录已存在或超出上限。", { exact: true }).waitFor();
  assert.equal(await page.getByText("备份恢复验证", { exact: true }).count(), 1);

  console.log("notes backup browser E2E: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolveClose) => server.close(resolveClose));
}
