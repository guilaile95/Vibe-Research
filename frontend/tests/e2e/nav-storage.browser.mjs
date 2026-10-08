// NAV-01: production UI, isolated synthetic browser state, no backend/provider.
// Native cookie-policy denial is probed separately from injected exceptions.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const frontend = fileURLToPath(new URL("../../", import.meta.url));
const dist = join(frontend, "dist");
export const scenarios = ["native-policy", "injected-getter", "injected-read", "injected-write-security", "injected-write-quota", "invalid", "normal", "default"];
export function injectStorageFailure(scenario) {
  const fail = name => { throw new DOMException("Synthetic storage failure", name); };
  if (scenario === "injected-getter") Object.defineProperty(window, "localStorage", { configurable: true, get: () => fail("SecurityError") });
  if (scenario === "injected-read") Storage.prototype.getItem = () => fail("SecurityError");
  if (scenario.startsWith("injected-write")) Storage.prototype.setItem = () => fail(scenario.endsWith("quota") ? "QuotaExceededError" : "SecurityError");
}
export function nativeStorageProbe() {
  try { localStorage.getItem("vr-sidebar"); return "available"; }
  catch (error) { return error.name; }
}
async function staticServer() {
  const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
  const server = createServer((request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/__storage_probe") {
      response.setHeader("Content-Type", "text/html");
      response.end("<!doctype html><title>Isolated storage probe</title>");
      return;
    }
    let target = resolve(dist, `.${decodeURIComponent(pathname)}`);
    if (!target.startsWith(dist + sep)) target = join(dist, "index.html");
    if (!existsSync(target) || !extname(target)) target = join(dist, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  await new Promise((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  return server;
}


async function runScenario(browser, baseURL, width, scenario, evidenceDir) {
  let context, page;
  const errors = [], requests = [], external = [], unexpected = [];
  try {
  if (scenario === "native-policy") {
    // A fresh disposable profile restricts storage. Never touches a user profile.
    const profile = mkdtempSync(join(tmpdir(), "vr-nav-policy-"));
    mkdirSync(join(profile, "Default"));
    writeFileSync(join(profile, "Default", "Preferences"), JSON.stringify({
      profile: { default_content_setting_values: { cookies: 2 } },
    }));
    // Profile content settings require full Chromium, not the default headless shell.
    // https://playwright.dev/docs/browsers#chromium-new-headless-mode
    context = await chromium.launchPersistentContext(profile, { ...launchOptions(), channel: "chromium", baseURL,
      viewport: { width, height: 960 }, serviceWorkers: "block" });
  } else context = await browser.newContext({ baseURL, viewport: { width, height: 960 }, serviceWorkers: "block" });
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  await context.routeWebSocket("**/*", socket => { external.push(`WebSocket ${socket.url()}`); socket.close(); });
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin === "https://fonts.googleapis.com") return route.fulfill({ contentType: "text/css", body: "" });
    if (url.origin !== baseURL) { external.push(url.origin); return route.abort(); }
    if (url.pathname.startsWith("/api/")) {
      requests.push(`${request.method()} ${url.pathname}`);
      if (request.method() === "GET" && url.pathname === "/api/thesis") {
        return route.fulfill({ json: { items: [], total: 0 } });
      }
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.fulfill({ status: 503, json: { detail: "UNEXPECTED_SYNTHETIC_REQUEST" } });
    }
    return route.continue();
  });
  const sidebar = page.getByTestId("app-sidebar");
  const readDenied = ["native-policy", "injected-getter", "injected-read"].includes(scenario);
  const writeDenied = scenario.startsWith("injected-write");
  const initialCollapsed = scenario === "normal" || writeDenied;
  const control = collapsed => page.getByRole("button", { name: collapsed ? "展开侧栏" : "收起侧栏", exact: true });
  const desktopState = async collapsed => {
    await control(collapsed).waitFor();
    await page.waitForFunction(expected => {
      const width = document.querySelector('[data-testid="app-sidebar"]').getBoundingClientRect().width;
      return Math.abs(width - expected) < 2;
    }, collapsed ? 56 : 200);
  };
  const mobileOpen = async () => {
    await page.getByTestId("nav-drawer-trigger").click();
    await page.waitForFunction(() => document.querySelector('[data-testid="app-sidebar"]').dataset.mobileOpen === "true");
    assert.equal(await page.getByTestId("nav-drawer-trigger").getAttribute("aria-expanded"), "true");
  };
  const navigate = async path => {
    if (width === 390) await mobileOpen();
    const primary = path === "/stock-data" ? "/screener" : "/thesis";
    await sidebar.locator(`a[href="${primary}"]`).click();
    await page.waitForURL(`**${primary}`);
    if (width === 390) {
      await page.waitForFunction(() => document.querySelector('[data-testid="app-sidebar"]').dataset.mobileOpen === "false");
      assert.equal(await page.locator("main").getAttribute("inert"), null);
    }
    if (primary === "/thesis") await page.getByText("还没有投资逻辑", { exact: false }).waitFor();
    await page.getByTestId("section-nav").locator(`a[href="${path}"]`).click();
    await page.waitForURL(`**${path}`);
  };
    await page.goto("/__storage_probe");
    const nativeProbe = await page.evaluate(nativeStorageProbe);
    assert.equal(nativeProbe, scenario === "native-policy" ? "SecurityError" : "available", "native-policy evidence must come from unmodified browser storage");
    if (scenario !== "native-policy") {
      await page.evaluate(({ initialCollapsed, scenario }) => {
        localStorage.clear();
        if (initialCollapsed) localStorage.setItem("vr-sidebar", "collapsed");
        if (scenario === "invalid") localStorage.setItem("vr-sidebar", "{broken");
      }, { initialCollapsed, scenario });
      await context.addInitScript(injectStorageFailure, scenario);
    }
    await page.goto("/notes");
    await page.getByRole("heading", { name: "研究记录", exact: true }).waitFor();
    if (readDenied) await page.getByRole("alert").filter({ hasText: "读取" }).waitFor();
    const observedProbe = await page.evaluate(nativeStorageProbe);
    assert.equal(observedProbe, readDenied ? "SecurityError" : "available");
    // Mobile drawer actions stay mobile; sidebar persistence controls are desktop-only.
    if (width === 390) {
      await mobileOpen();
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelector('[data-testid="app-sidebar"]').dataset.mobileOpen === "false");
      assert.equal(await page.getByTestId("nav-drawer-trigger").evaluate(el => el === document.activeElement), true);
      await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-notes.png`), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 960 });
    }
    await desktopState(initialCollapsed);
    await control(initialCollapsed).click();
    await desktopState(!initialCollapsed);
    await control(!initialCollapsed).click();
    await desktopState(initialCollapsed);
    await control(initialCollapsed).click();
    await desktopState(!initialCollapsed);
    if (!readDenied) {
      await page.waitForFunction(expected => localStorage.getItem("vr-sidebar") === expected,
        writeDenied ? "collapsed" : initialCollapsed ? "expanded" : "collapsed");
    }
    if (width === 390) await page.setViewportSize({ width, height: 960 });
    await navigate("/stock-data");
    const input = page.getByPlaceholder("A 股 6 位代码", { exact: false });
    await input.waitFor();
    await input.fill("SYNTHETIC");
    assert.equal(await input.inputValue(), "SYNTHETIC");
    // No submit: no market API is permitted in this navigation/storage slice.
    await page.screenshot({ path: join(evidenceDir, `${scenario}-${width}-stock.png`), fullPage: true });
    await navigate("/notes");
    await page.getByRole("heading", { name: "研究记录", exact: true }).waitFor();
    if (width === 390) await page.setViewportSize({ width: 1440, height: 960 });
    await desktopState(!initialCollapsed); // SPA navigation preserves session toggle.
    await page.reload();
    await page.getByRole("heading", { name: "研究记录", exact: true }).waitFor();
    await desktopState(readDenied ? false : writeDenied ? true : !initialCollapsed);
    assert.deepEqual(unexpected, [], "only the synthetic thesis-list read is allowed");
    assert.deepEqual(requests, ["GET /api/thesis"], "one sidebar library navigation read; no stock/provider request");
    assert.deepEqual(external, [], "no external network or WebSocket attempts");
    assert.deepEqual(errors, [], "no uncaught page or console errors");
    return { scenario, width, status: "PASS", nativeProbe, observedProbe, requests,
      persistence: readDenied ? "default restored" : writeDenied ? "prior value retained" : "new preference retained" };
  } catch (error) {
    await page?.screenshot({ path: join(evidenceDir, `${scenario}-${width}-failure.png`), fullPage: true }).catch(() => {});
    throw new Error(`${scenario} ${width}px: ${error.message}; ${JSON.stringify({ errors, requests, external })}`, { cause: error });
  } finally { await context?.close(); }
}
function launchOptions() {
  return { headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) };
}
async function main() {
  const evidenceDir = process.env.NAV_EVIDENCE_DIR || mkdtempSync(join(tmpdir(), "vr-nav-evidence-"));
  mkdirSync(evidenceDir, { recursive: true });
  const git = arg => execFileSync("git", ["rev-parse", arg], { cwd: frontend, encoding: "utf8" }).trim();
  const result = { checkoutHead: git("HEAD"), checkoutTree: git("HEAD^{tree}"),
    frontendSourceTree: git("HEAD:frontend/src"), pullRequestHead: process.env.NAV_PR_HEAD || null,
    boundary: "Native temporary-profile cookie policy separately probed; injected exceptions labelled; production UI, only synthetic thesis-list read, no backend/model/market requests; mobile drawer and desktop persistence controls", results: [] };
  let browser, server;
  try {
    assert.ok(existsSync(join(dist, "index.html")), "Run npm run build first");
    browser = await chromium.launch(launchOptions());
    result.browser = browser.version();
    server = await staticServer();
    const baseURL = `http://127.0.0.1:${server.address().port}`;
    for (const width of [1440, 390]) for (const scenario of scenarios) {
      try {
        result.results.push(await runScenario(browser, baseURL, width, scenario, evidenceDir));
        console.log(`[NAV] ${scenario} ${width}px PASS`);
      } catch (error) {
        result.results.push({ scenario, width, status: "FAIL", error: error.message });
        console.error(`[NAV] ${scenario} ${width}px FAIL: ${error.message}`);
      }
    }
    assert.equal(result.results.length, 16);
    assert.equal(result.results.filter(row => row.status !== "PASS").length, 0, "every storage scenario must pass");
    console.log("[NAV] 16/16 PASS");
  } catch (error) { result.error = error.message; throw error; }
  finally {
    try { writeFileSync(join(evidenceDir, "results.json"), JSON.stringify(result, null, 2)); }
    finally { try { await browser?.close(); } finally {
      server?.closeAllConnections();
      if (server) await new Promise(done => server.close(done));
    } }
  }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
