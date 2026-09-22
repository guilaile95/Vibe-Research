/**
 * 核心工作流导航 smoke（纯前端，无后端依赖）。TASK = IA-CONVERGENCE-V1
 *
 * 验证已批准的信息架构：
 * - 侧栏恰为 10 个常驻一级入口，分组标题是静态文字而不是折叠层；
 * - 一级入口内部的二级页面由 SectionNav 呈现，且不再有重复的「研究链路」横条；
 * - 旧版分析工具（含 Cockpit）保留在研究资料的「旧版分析工具」目录里并带（旧版）标识；
 * - 决策链主入口 → 交易 → 决策复盘 全程直达，campaign 提案页归属「决策待办」高亮。
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

/** 10 个常驻一级入口，按分组与顺序。 */
const PERMANENT_ENTRIES = [
  { group: "工作", label: "今天", href: "/daily-review" },
  { group: "工作", label: "决策待办", href: "/decision-inbox" },
  { group: "研究", label: "自选股", href: "/watchlist" },
  { group: "研究", label: "投资研究", href: "/screener" },
  { group: "研究", label: "研究资料", href: "/thesis" },
  { group: "账户与复盘", label: "我的持仓", href: "/portfolio" },
  { group: "账户与复盘", label: "交易记录", href: "/trades" },
  { group: "账户与复盘", label: "决策复盘", href: "/decision-performance" },
  { group: "系统", label: "数据健康", href: "/data-health" },
  { group: "系统", label: "设置", href: "/settings" },
];

/** 一级入口内部的二级入口（含旧版目录），含统一名称。 */
const SECTION_EXPECTATIONS = [
  {
    owner: "research",
    visit: "/stock-data",
    primary: [
      { href: "/screener", label: "市场发现" },
      { href: "/sectors", label: "板块研究" },
      { href: "/stock-data", label: "个股数据" },
      { href: "/intel", label: "资讯中心" },
      { href: "/signals", label: "产业信号" },
    ],
    tools: [{ href: "/debate", label: "多空辩论" }],
  },
  {
    owner: "library",
    visit: "/thesis",
    primary: [
      { href: "/thesis", label: "投资逻辑" },
      { href: "/evidence", label: "证据库" },
      { href: "/my-reports", label: "我的研报" },
      { href: "/notes", label: "研究笔记" },
    ],
    tools: [
      { href: "/decision-evidence", label: "建议依据追踪（旧版）" },
      { href: "/decision-feedback", label: "建议采纳反馈（旧版）" },
      { href: "/signal-ledger", label: "建议信号账本（旧版）" },
      { href: "/cockpit", label: "决策驾驶舱（旧版）" },
    ],
  },
  {
    owner: "trades",
    visit: "/trades",
    primary: [
      { href: "/trades", label: "交易记录" },
      { href: "/performance-attribution", label: "收益归因" },
    ],
    tools: [],
  },
  {
    owner: "settings",
    visit: "/settings",
    primary: [
      { href: "/settings", label: "设置" },
      { href: "/account-policy", label: "执行参数" },
    ],
    tools: [],
  },
];

let server;
let browser;

try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html 缺失：先运行 npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  const frontend = `http://127.0.0.1:${port}`;

  try {
    browser = await chromium.launch({ headless: true, executablePath: chromiumPath() });
  } catch {
    browser = await chromium.launch({ headless: true, channel: "chrome" });
  }
  const page = await browser.newPage();

  await page.goto(frontend, { waitUntil: "networkidle" });
  const sidebar = page.getByTestId("app-sidebar");
  const mainNav = sidebar.getByRole("navigation", { name: "主导航" });

  // 1) 侧栏恰为 10 个常驻入口，名称与落点唯一。
  // 断言限定在「主导航」容器内：品牌 logo 也指向 /daily-review，不属于入口。
  for (const { label, href } of PERMANENT_ENTRIES) {
    const link = mainNav.locator(`a[href="${href}"]`);
    assert.equal(await link.count(), 1, `主导航应恰好有一个 ${href} 入口`);
    assert.equal((await link.innerText()).trim(), label, `${href} 应显示为「${label}」`);
  }
  assert.equal(await mainNav.locator("a").count(), 10, "主导航链接总数应为 10");

  // 2) 分组是静态标题，不是需要先点开的折叠层。
  for (const group of ["工作", "研究", "账户与复盘", "系统"]) {
    assert.equal(
      await mainNav.getByText(group, { exact: true }).count(),
      1,
      `分组标题「${group}」应静态可见`,
    );
  }
  assert.equal(await sidebar.getByRole("button", { name: "资料" }).count(), 0, "不应再有「资料」折叠按钮");
  assert.equal(await sidebar.getByRole("button", { name: "分析" }).count(), 0, "不应再有「分析」折叠按钮");

  // 3) 每个入口图标不重复（图标是入口身份的一部分）。
  const iconClasses = [];
  for (const { href } of PERMANENT_ENTRIES) {
    const cls = await mainNav.locator(`a[href="${href}"] svg`).getAttribute("class");
    assert.ok(cls, `${href} 应带图标`);
    iconClasses.push(cls);
  }
  assert.equal(new Set(iconClasses).size, iconClasses.length, "一级入口不得重复使用同一图标");

  // 4) 旧的分析工具不再占用一级入口，但仍在二级目录里可达（下面第 6 项验证）。
  assert.equal(
    await mainNav.locator('a[href="/cockpit"]').count(),
    0,
    "一级导航不应再有 /cockpit 入口",
  );
  assert.equal(
    await page.getByRole("navigation", { name: "研究链路" }).count(),
    0,
    "重复的研究链路横条应已撤下",
  );

  // 5) 二级入口按一级归属呈现，名称与落点唯一。
  for (const expectation of SECTION_EXPECTATIONS) {
    await page.goto(`${frontend}${expectation.visit}`, { waitUntil: "networkidle" });
    const section = page.getByTestId("section-nav");
    assert.equal(await section.count(), 1, `${expectation.visit} 应显示二级导航`);
    assert.equal(
      await section.getAttribute("data-section-owner"),
      expectation.owner,
      `${expectation.visit} 的二级导航应属于 ${expectation.owner}`,
    );
    for (const item of [...expectation.primary, ...expectation.tools]) {
      const link = section.locator(`a[href="${item.href}"]`);
      assert.equal(await link.count(), 1, `二级导航应恰好有一个 ${item.href} 入口`);
      assert.equal((await link.innerText()).trim(), item.label, `${item.href} 应显示为「${item.label}」`);
    }
  }

  // 6) 旧版分析工具带（旧版）标识，且直接访问旧链接仍能定位。
  await page.goto(`${frontend}/cockpit`, { waitUntil: "networkidle" });
  const legacySection = page.getByTestId("section-nav");
  const legacyLink = legacySection.locator('a[href="/cockpit"]');
  assert.equal(await legacyLink.count(), 1, "旧版目录应保留 Cockpit 入口");
  assert.match(await legacyLink.innerText(), /（旧版）/, "Cockpit 应带（旧版）标识");
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="section-nav"] a[href="/cockpit"]');
    return !!el && el.getAttribute("aria-current") === "page";
  });
  assert.equal(
    await sidebar.locator('a[href="/thesis"]').getAttribute("aria-current"),
    "page",
    "旧版工具页仍归属「研究资料」",
  );

  // 7) 点击主链：决策待办 → 交易记录 → 决策复盘，全程不需要展开任何折叠层。
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

  await sidebar.getByRole("link", { name: "决策待办", exact: true }).click();
  await page.waitForURL("**/decision-inbox");
  await expectAriaCurrent('a[href="/decision-inbox"]');

  await sidebar.getByRole("link", { name: "交易记录", exact: true }).click();
  await page.waitForURL("**/trades");

  await sidebar.getByRole("link", { name: "决策复盘", exact: true }).click();
  await page.waitForURL("**/decision-performance");

  // 8) campaign Formal Decision 提案页归属「决策待办」高亮。
  await page.goto(`${frontend}/campaigns/c-smoke/decision-proposal`, { waitUntil: "networkidle" });
  await expectAriaCurrent('a[href="/decision-inbox"]');

  // 9) 二级选中态与真实路由一致，动态详情不会点亮错误项。
  await page.goto(`${frontend}/sectors`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="section-nav"] a[href="/sectors"]');
    return !!el && el.getAttribute("aria-current") === "page";
  });
  assert.equal(
    await sidebar.locator('a[href="/screener"]').getAttribute("aria-current"),
    "page",
    "板块研究仍归属「投资研究」",
  );

  console.log("core workflow navigation smoke: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolve) => server.close(resolve));
}
