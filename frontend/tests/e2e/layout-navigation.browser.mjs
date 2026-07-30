/**
 * Layout mobile navigation drawer E2E — pure frontend + Playwright page.route mocks.
 *
 * Run directly (package.json intentionally not modified):
 *   cd frontend && npm run build && node tests/e2e/layout-navigation.browser.mjs
 *
 * Architecture (mirrors stock-data-panel.smoke.browser.mjs):
 * - Playwright loads the Vite build from a Node static server (frontend/dist only)
 * - ALL /api/* traffic is intercepted via page.route (NO real backend)
 * - Covers drawer open/close, aria-expanded, Escape, focus return, focus containment,
 *   overlay click, route change close, and md-breakpoint state cleanup
 */
import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

const MOBILE = { width: 390, height: 780 };
const DESKTOP = { width: 1024, height: 780 };

let frontendPort = 0;
let browserLabel = "unknown";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ detail: "use page.route mocks" }));
      return;
    }

    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || (existsSync(target) && path.extname(target) === "")) {
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

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const launchOpts = {
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  };
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const b = await chromium.launch(launchOpts);
      browserLabel = `local chromium-${b.version()}`;
      return b;
    } catch (error) {
      lastError = error;
      if (attempt === 0) {
        launchOpts.channel = "chrome";
      }
    }
  }
  throw lastError || new Error("failed to launch any Chromium");
}

/** Every /api/* call returns an inert success payload — no backend, no data assertions here. */
async function handleApi(route) {
  const url = route.request().url();
  if (!url.includes("/api/")) {
    await route.continue();
    return;
  }
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data: [] }),
  });
}

const trigger = (page) => page.locator('[data-testid="nav-drawer-trigger"]');
const sidebar = (page) => page.locator('[data-testid="app-sidebar"]');

async function drawerOpen(page) {
  return await sidebar(page).getAttribute("data-mobile-open") === "true";
}

async function ariaExpanded(page) {
  return await trigger(page).getAttribute("aria-expanded");
}

async function activeInDrawer(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    const drawer = document.querySelector('[data-testid="app-sidebar"]');
    return !!(el && drawer && drawer.contains(el));
  });
}

async function activeIsTrigger(page) {
  return page.evaluate(
    () => document.activeElement === document.querySelector('[data-testid="nav-drawer-trigger"]'),
  );
}

async function openPage(browser, { collapsed = false, viewport = MOBILE } = {}) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.route("**/api/**", handleApi);
  await page.addInitScript((value) => {
    localStorage.setItem("vr-sidebar", value);
  }, collapsed ? "collapsed" : "expanded");
  return { context, page };
}

async function gotoApp(page, route = "/daily-review") {
  await page.goto(`http://127.0.0.1:${frontendPort}${route}`, { waitUntil: "domcontentloaded" });
  await sidebar(page).waitFor({ state: "attached", timeout: 15000 });
  await trigger(page).waitFor({ timeout: 15000 });
}

async function openDrawer(page) {
  await trigger(page).click();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="app-sidebar"]')?.dataset.mobileOpen === "true",
    null,
    { timeout: 5000 },
  );
}

/** Cases 1-4, 9: open, aria-expanded, focus containment, Escape, focus return. */
async function caseOpenKeyboard(browser, errors) {
  const label = "open+keyboard";
  const { context, page } = await openPage(browser);
  try {
    await gotoApp(page);

    if ((await ariaExpanded(page)) !== "false") {
      errors.push(`${label}: aria-expanded should start as false, got ${await ariaExpanded(page)}`);
    }
    if (await drawerOpen(page)) errors.push(`${label}: drawer should start closed`);

    // 1) hamburger opens drawer
    await openDrawer(page);
    if (!(await drawerOpen(page))) errors.push(`${label}: drawer did not open on trigger click`);
    // 2) aria-expanded flips to true
    if ((await ariaExpanded(page)) !== "true") {
      errors.push(`${label}: aria-expanded should be true when open, got ${await ariaExpanded(page)}`);
    }
    // mobile drawer keeps full labels (never icon-only)
    if (!(await sidebar(page).getByRole("link", { name: "每日复盘" }).isVisible().catch(() => false))) {
      errors.push(`${label}: mobile drawer should show full nav labels`);
    }
    // focus moved into drawer
    if (!(await activeInDrawer(page))) errors.push(`${label}: focus did not move into drawer on open`);
    // body scroll locked
    const overflow = await page.evaluate(() => document.body.style.overflow);
    if (overflow !== "hidden") errors.push(`${label}: body scroll not locked (overflow=${overflow})`);
    // background inert
    const inert = await page.evaluate(() => document.querySelector("main")?.hasAttribute("inert"));
    if (!inert) errors.push(`${label}: main background should be inert while drawer is open`);

    // 9) Tab cannot escape the drawer
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
    }
    if (!(await activeInDrawer(page))) {
      errors.push(`${label}: Tab escaped the drawer into background content`);
    }
    await page.keyboard.press("Shift+Tab");
    if (!(await activeInDrawer(page))) errors.push(`${label}: Shift+Tab escaped the drawer`);

    // 3) Escape closes
    await page.keyboard.press("Escape");
    await sleep(300);
    if (await drawerOpen(page)) errors.push(`${label}: Escape did not close the drawer`);
    if ((await ariaExpanded(page)) !== "false") {
      errors.push(`${label}: aria-expanded should return to false after Escape`);
    }
    // 4) focus returns to the hamburger button
    if (!(await activeIsTrigger(page))) {
      errors.push(`${label}: focus did not return to the hamburger trigger after close`);
    }
    // background restored
    const restored = await page.evaluate(() => ({
      overflow: document.body.style.overflow,
      inert: document.querySelector("main")?.hasAttribute("inert") ?? true,
    }));
    if (restored.overflow === "hidden") errors.push(`${label}: body scroll lock not released`);
    if (restored.inert) errors.push(`${label}: main inert not released after close`);
  } catch (e) {
    errors.push(`${label}: fatal ${e.message}`);
  } finally {
    await context.close();
  }
}

/** Case 5: route change closes the drawer. Case 8: overlay click closes. */
async function caseRouteAndOverlay(browser, errors) {
  const label = "route+overlay";
  const { context, page } = await openPage(browser);
  try {
    await gotoApp(page);

    // 8) overlay click closes
    await openDrawer(page);
    await page.locator('[data-testid="nav-drawer-overlay"]').click({ position: { x: 350, y: 700 } });
    await sleep(300);
    if (await drawerOpen(page)) errors.push(`${label}: overlay click did not close the drawer`);

    // 5) clicking a nav item navigates and closes
    await openDrawer(page);
    await sidebar(page).getByRole("link", { name: "自选股" }).click();
    await page.waitForFunction(() => location.pathname === "/watchlist", null, { timeout: 8000 });
    await sleep(300);
    if (await drawerOpen(page)) errors.push(`${label}: drawer stayed open after route change`);
    if ((await ariaExpanded(page)) !== "false") {
      errors.push(`${label}: aria-expanded should be false after route change`);
    }
    const overflow = await page.evaluate(() => document.body.style.overflow);
    if (overflow === "hidden") errors.push(`${label}: body scroll still locked after route change`);
  } catch (e) {
    errors.push(`${label}: fatal ${e.message}`);
  } finally {
    await context.close();
  }
}

/** Cases 6-7: md breakpoint closes drawer and desktop width depends on `collapsed` only. */
async function caseBreakpoint(browser, errors) {
  // 6) expanded sidebar: 390 -> 1024 closes drawer, desktop width stays wide
  const expanded = await openPage(browser, { collapsed: false });
  try {
    await gotoApp(expanded.page);
    await openDrawer(expanded.page);
    await expanded.page.setViewportSize(DESKTOP);
    await sleep(600);
    if (await drawerOpen(expanded.page)) {
      errors.push("breakpoint(expanded): drawer stayed open after resize to 1024px");
    }
    if ((await ariaExpanded(expanded.page)) !== "false") {
      errors.push("breakpoint(expanded): aria-expanded should be false on desktop");
    }
    const width = await expanded.page.evaluate(
      () => document.querySelector('[data-testid="app-sidebar"]').getBoundingClientRect().width,
    );
    if (Math.abs(width - 240) > 4) {
      errors.push(`breakpoint(expanded): desktop sidebar width expected ~240, got ${width}`);
    }
    const overflow = await expanded.page.evaluate(() => document.body.style.overflow);
    if (overflow === "hidden") errors.push("breakpoint(expanded): body scroll lock leaked to desktop");
  } catch (e) {
    errors.push(`breakpoint(expanded): fatal ${e.message}`);
  } finally {
    await expanded.context.close();
  }

  // 7) collapsed sidebar: stale mobileOpen must not keep desktop sidebar expanded
  const collapsed = await openPage(browser, { collapsed: true });
  try {
    await gotoApp(collapsed.page);
    await openDrawer(collapsed.page);
    // mobile drawer still shows labels even though collapsed=true
    if (!(await sidebar(collapsed.page).getByRole("link", { name: "决策舱" }).isVisible().catch(() => false))) {
      errors.push("breakpoint(collapsed): mobile drawer must show labels while collapsed=true");
    }
    await collapsed.page.setViewportSize(DESKTOP);
    await sleep(700);
    if (await drawerOpen(collapsed.page)) {
      errors.push("breakpoint(collapsed): drawer stayed open after resize to 1024px");
    }
    const width = await collapsed.page.evaluate(
      () => document.querySelector('[data-testid="app-sidebar"]').getBoundingClientRect().width,
    );
    if (Math.abs(width - 56) > 4) {
      errors.push(`breakpoint(collapsed): desktop sidebar width expected ~56 (icon-only), got ${width}`);
    }
    // icon-only mode: label text no longer rendered on desktop (title tooltip only)
    if ((await sidebar(collapsed.page).getByText("决策舱", { exact: true }).count()) > 0) {
      errors.push("breakpoint(collapsed): desktop collapsed sidebar should hide nav labels");
    }
  } catch (e) {
    errors.push(`breakpoint(collapsed): fatal ${e.message}`);
  } finally {
    await collapsed.context.close();
  }
}

async function main() {
  const errors = [];
  let server = null;
  let browser = null;

  if (!existsSync(frontendDist) || !existsSync(path.join(frontendDist, "index.html"))) {
    console.error("frontend/dist missing — run: npm run build");
    process.exit(2);
  }

  try {
    frontendPort = await getFreePort();
    server = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    browser = await launchBrowser();
    await caseOpenKeyboard(browser, errors);
    await caseRouteAndOverlay(browser, errors);
    await caseBreakpoint(browser, errors);
  } catch (e) {
    errors.push(`fatal: ${e && e.stack ? e.stack : String(e)}`);
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {
        /* ignore */
      }
    }
    if (server) {
      await new Promise((resolve) => server.close(() => resolve()));
    }
  }

  if (errors.length) {
    console.error(`FAIL layout-navigation (${browserLabel})`);
    for (const e of errors) console.error(` - ${e}`);
    process.exit(1);
  }
  console.log(`PASS layout-navigation (${browserLabel}) port=${frontendPort} cases=9`);
}

main();
