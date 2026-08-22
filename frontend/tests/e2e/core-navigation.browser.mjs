/**
 * P1-NAV1 核心工作流导航 smoke（纯前端，无后端依赖）。
 *
 * 验证正式主链从主导航直达：
 * - 主导航「决策」指向 Decision Inbox（不再是 legacy Cockpit）；
 * - 「交易」「复盘」在主导航直接可达；
 * - legacy Cockpit 降级到「分析」折叠区且带 Legacy 标识；
 * - Inbox → Formal Decision 的 campaign 提案页归属「决策」高亮。
 */

import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = join(fileURLToPath(import.meta.url), "..");
const dist = join(here, "../../dist");

function chromiumPath() {
  const roots = [process.env.PLAYWRIGHT_CHROMIUM_PATH, join(process.env.LOCALAPPDATA || "", "ms-playwright"), join(process.env.HOME || "", ".cache", "ms-playwright")];
  const candidates = [];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    for (const item of readdirSync(base)) {
      if (!/^chromium(_headless_shell)?-\d+$/.test(item)) continue;
      candidates.push(
        join(base, item, "chrome-win64", "chrome.exe"),
        join(base, item, "chrome-win", "chrome.exe"),
        join(base, item, "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
      );
    }
  }
  // 取 revision 最高的可用可执行文件（目录名按字典序即版本序）。
  const found = candidates.filter((exe) => existsSync(exe)).sort();
  return found.at(-1);
}

function staticServer(directory, port) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = join(directory, pathname);
    if (!existsSync(target) || extname(target) === "") target = join(directory, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

async function freePort() {
  const server = createServer();
  const port = await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
  await new Promise((resolve) => server.close(resolve));
  return port;
}

const PRIMARY_LINKS = [
  { label: "决策", href: "/decision-inbox" },
  { label: "交易", href: "/trades" },
  { label: "复盘", href: "/decision-performance" },
];

let server;
let browser;

try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html 缺失：先运行 npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  const frontend = `http://127.0.0.1:${port}`;

  browser = await chromium.launch({ headless: true, executablePath: chromiumPath() });
  const page = await browser.newPage();

  await page.goto(frontend, { waitUntil: "networkidle" });
  const sidebar = page.getByTestId("app-sidebar");

  // 1) 主导航包含核心工作流直达入口，且「决策」指向 Decision Inbox。
  for (const { label, href } of PRIMARY_LINKS) {
    const link = sidebar.getByRole("link", { name: label, exact: true });
    assert.equal(await link.count(), 1, `主导航应恰好有一个「${label}」入口`);
    assert.equal(await link.getAttribute("href"), href, `「${label}」应指向 ${href}`);
  }

  // 2) legacy Cockpit 不再出现在主导航顶层。
  assert.equal(
    await sidebar.locator(`nav[aria-label="主导航"] > div:first-child a[href="/cockpit"]`).count(),
    0,
    "主导航第一分区不应再有 /cockpit 入口",
  );

  // 3) 点击主链：决策 → 交易 → 复盘，全程不需要打开任何折叠菜单。
  // aria-current 由 React 提交渲染；waitForURL 先于 commit 返回，直接读会偶发 null，
  // 因此轮询等待属性就位（断言仍是严格 "page"，只是允许渲染提交的时差）。
  const expectAriaCurrent = async (selector) => {
    await page.waitForFunction(
      (sel) => {
        const el = document.querySelector(sel);
        if (!el || !el.offsetParent) return false;
        return el.getAttribute("aria-current") === "page";
      },
      selector,
      { timeout: 15000 },
    );
    assert.equal(await sidebar.locator(selector).getAttribute("aria-current"), "page");
  };

  await sidebar.getByRole("link", { name: "决策", exact: true }).click();
  await page.waitForURL("**/decision-inbox");
  await expectAriaCurrent('a[href="/decision-inbox"]');

  await sidebar.getByRole("link", { name: "交易", exact: true }).click();
  await page.waitForURL("**/trades");

  await sidebar.getByRole("link", { name: "复盘", exact: true }).click();
  await page.waitForURL("**/decision-performance");

  // 4) campaign Formal Decision 提案页归属「决策」高亮。
  await page.goto(`${frontend}/campaigns/c-smoke/decision-proposal`, { waitUntil: "networkidle" });
  await expectAriaCurrent('a[href="/decision-inbox"]');

  // 5) legacy Cockpit 保留在「分析」折叠区并带 Legacy 标识。
  await sidebar.getByRole("button", { name: "分析" }).click();
  const legacyLink = sidebar.locator('a[href="/cockpit"]');
  assert.equal(await legacyLink.count(), 1, "分析菜单应保留 Cockpit 入口");
  assert.match(await legacyLink.innerText(), /Legacy/, "Cockpit 应带 Legacy 标识");

  console.log("core workflow navigation smoke: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
