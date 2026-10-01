/**
 * 研究记录备份真实浏览器路径：
 * localStorage 记录 → 下载 JSON → 清空浏览器记录 → 导入恢复。
 * 损坏记录 → 原文下载 → 无效/取消/配额失败保留原文 → 确认替换 → 恢复普通合并。
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

async function launchBrowser() {
  const executablePath = findChromium();
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

let server;
let browser;

try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html 缺失：先运行 npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  browser = await launchBrowser();
  const page = await browser.newPage();
  const frontend = `http://127.0.0.1:${port}`;

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

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "清空", exact: true }).click();
  await page.getByText(/还没有记录/).waitFor();

  const input = page.getByTestId("notes-backup-input");
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已导入 1 条研究记录。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();

  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("没有新增记录；1 条记录已存在或超出上限。", { exact: true }).waitFor();
  assert.equal(await page.getByText("备份恢复验证", { exact: true }).count(), 1);

  const corruptedRaw = ' \n{"broken":"原始研究记录\n';
  await page.evaluate((value) => localStorage.setItem("vr-notes", value), corruptedRaw);
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("alert").getByText("本地研究记录格式无效，原始数据已保留", { exact: true }).waitFor();
  assert.equal(await page.getByText(/还没有记录/).count(), 0, "损坏数据不能伪装成空记录");
  assert.equal(await page.getByRole("button", { name: "导出备份", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "导入备份", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "从备份替换损坏记录", exact: true }).isEnabled(), true);

  const [rawDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "下载损坏原始数据", exact: true }).click(),
  ]);
  assert.match(rawDownload.suggestedFilename(), /^vibe-research-notes-corrupted-raw-.*\.txt$/);
  const rawDownloadPath = await rawDownload.path();
  assert.ok(rawDownloadPath);
  assert.deepEqual(readFileSync(rawDownloadPath), Buffer.from(corruptedRaw, "utf8"));
  assert.doesNotMatch(readFileSync(rawDownloadPath, "utf8"), /SECRET_LLM_CONFIG|SECRET_ACCESS_KEY|SECRET_CHAT_HISTORY/);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);

  let unexpectedDialog = false;
  const rejectUnexpectedDialog = (dialog) => { unexpectedDialog = true; void dialog.dismiss(); };
  page.on("dialog", rejectUnexpectedDialog);
  await input.setInputFiles({ name: "invalid.json", mimeType: "application/json", buffer: Buffer.from("not-json") });
  await page.getByRole("alert").getByText("备份文件不是有效的 JSON", { exact: true }).waitFor();
  assert.equal(unexpectedDialog, false, "必须先完成校验再询问替换");
  page.off("dialog", rejectUnexpectedDialog);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);
  await input.setInputFiles([]);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw, "取消文件选择不得写入");

  page.once("dialog", (dialog) => {
    assert.match(dialog.message(), /备份已校验，共 1 条研究记录/);
    assert.match(dialog.message(), /完全替换/);
    assert.match(dialog.message(), /仅替换研究记录/);
    void dialog.dismiss();
  });
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已取消替换，原始研究记录保持不变。", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);

  await page.evaluate(() => {
    window.__notesOriginalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "vr-notes") throw new DOMException("Synthetic quota failure", "QuotaExceededError");
      return window.__notesOriginalSetItem.call(this, key, value);
    };
  });
  page.once("dialog", (dialog) => dialog.accept());
  await input.setInputFiles(downloadPath);
  await page.getByRole("alert").getByText("浏览器无法保存数据，请检查存储权限或空间", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);
  assert.equal(await page.getByRole("button", { name: "从备份替换损坏记录", exact: true }).isEnabled(), true);
  await page.evaluate(() => {
    Storage.prototype.setItem = window.__notesOriginalSetItem;
    delete window.__notesOriginalSetItem;
  });

  page.once("dialog", (dialog) => dialog.accept());
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已从备份恢复 1 条研究记录，损坏数据已替换。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "从备份替换损坏记录", exact: true }).count(), 0);
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("备份恢复验证", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "导入备份", exact: true }).isEnabled(), true);

  const mergePayload = { ...payload, notes: [
    { ...payload.notes[0], content: "不得覆盖已恢复记录" },
    { ...payload.notes[0], id: "after-recovery", title: "恢复后普通导入", ts: 1788426000001 },
  ] };
  await input.setInputFiles({ name: "merge.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(mergePayload)) });
  await page.getByRole("status").getByText("已导入 1 条研究记录，另有 1 条重复或超出上限。", { exact: true }).waitFor();
  const finalStorage = await page.evaluate(() => ({
    notes: JSON.parse(localStorage.getItem("vr-notes")),
    llm: localStorage.getItem("vr-llm"),
    key: localStorage.getItem("vr-access-key"),
    chat: localStorage.getItem("vr-askai-chat:test"),
  }));
  assert.equal(finalStorage.notes.length, 2);
  assert.equal(finalStorage.notes.find((item) => item.id === "note-backup-e2e").content, payload.notes[0].content);
  assert.equal(finalStorage.llm, "SECRET_LLM_CONFIG");
  assert.equal(finalStorage.key, "SECRET_ACCESS_KEY");
  assert.equal(finalStorage.chat, "SECRET_CHAT_HISTORY");

  console.log("notes backup browser E2E: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolveClose) => server.close(resolveClose));
}
