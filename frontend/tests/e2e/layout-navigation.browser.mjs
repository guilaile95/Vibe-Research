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
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

const evidenceDir = path.resolve(process.env.LAYOUT_NAV_EVIDENCE_DIR || path.join(root, "frontend/layout-navigation-evidence"));

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
  if (new URL(url).origin !== `http://127.0.0.1:${frontendPort}`) {
    await route.abort("blockedbyclient");
    return;
  }
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
  await page.route("**/*", handleApi);
  await page.addInitScript((value) => {
    localStorage.setItem("vr-sidebar", value);
  }, collapsed ? "collapsed" : "expanded");
  return { context, page };
}

// Use an data-independent form; no edits/submission or campaign context.
async function gotoApp(page, route = "/thesis/new") {
  await page.goto(`http://127.0.0.1:${frontendPort}${route}`, { waitUntil: "domcontentloaded" });
  await sidebar(page).waitFor({ state: "attached", timeout: 15000 });
  await trigger(page).waitFor({ timeout: 15000 });
  await page.getByRole("heading", { name: "新建投资逻辑", exact: true }).waitFor();
  await page.locator('[role="status"][aria-busy="true"]').waitFor({ state: "hidden" });
}

async function openDrawer(page) {
  await trigger(page).click();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="app-sidebar"]')?.dataset.mobileOpen === "true",
    null,
    { timeout: 5000 },
  );
}

async function saveEvidence(page, label, errors) {
  await mkdir(evidenceDir, { recursive: true });
  await writeFile(path.join(evidenceDir, `${label}.json`), JSON.stringify({ errors, url: page.url(), viewport: page.viewportSize() }, null, 2));
  await writeFile(path.join(evidenceDir, `${label}.html`), await page.content());
  await page.screenshot({ path: path.join(evidenceDir, `${label}.png`) });
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
    if (!(await sidebar(page).getByRole("link", { name: "今天" }).isVisible().catch(() => false))) {
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
    await saveEvidence(page, label, errors);
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
    await saveEvidence(page, label, errors);
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
    if (Math.abs(width - 200) > 4) {
      errors.push(`breakpoint(expanded): desktop sidebar width expected ~200, got ${width}`);
    }
    const overflow = await expanded.page.evaluate(() => document.body.style.overflow);
    if (overflow === "hidden") errors.push("breakpoint(expanded): body scroll lock leaked to desktop");
  } catch (e) {
    errors.push(`breakpoint(expanded): fatal ${e.message}`);
  } finally {
    await saveEvidence(expanded.page, "breakpoint-expanded", errors);
    await expanded.context.close();
  }

  // 7) collapsed sidebar: stale mobileOpen must not keep desktop sidebar expanded
  const collapsed = await openPage(browser, { collapsed: true });
  try {
    await gotoApp(collapsed.page);
    await openDrawer(collapsed.page);
    // mobile drawer still shows labels even though collapsed=true
    if (!(await sidebar(collapsed.page).getByRole("link", { name: "决策待办" }).isVisible().catch(() => false))) {
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
    if ((await sidebar(collapsed.page).getByText("决策待办", { exact: true }).count()) > 0) {
      errors.push("breakpoint(collapsed): desktop collapsed sidebar should hide nav labels");
    }
  } catch (e) {
    errors.push(`breakpoint(collapsed): fatal ${e.message}`);
  } finally {
    await saveEvidence(collapsed.page, "breakpoint-collapsed", errors);
    await collapsed.context.close();
  }
}

/** Real Layout scrollport with bounded synthetic content; no backend/model calls. */
async function caseScrollClearance(browser, errors) {
  const geometry = [];
  const { context, page } = await openPage(browser);
  try {
    await gotoApp(page);
    for (const width of [390, 767]) {
      await page.setViewportSize({ width, height: MOBILE.height });
      await page.evaluate(() => { document.querySelector('main').scrollTop = 0; });
      // Loaded-layout geometry only; transient lazy fallback margins are not this contract.
      const initial = await page.evaluate(() => {
        const main = document.querySelector('main');
        const nav = document.querySelector('[data-testid="nav-drawer-trigger"]');
        return { top: main.getBoundingClientRect().top, bottom: main.getBoundingClientRect().bottom,
          contentTop: main.firstElementChild.getBoundingClientRect().top + parseFloat(getComputedStyle(main.firstElementChild).paddingTop),
          navBottom: nav.getBoundingClientRect().bottom, viewport: innerHeight };
      });
      geometry.push({ width, phase: "initial", ...initial });
      if (Math.abs(initial.top - 64) > 1 || Math.abs(initial.contentTop - 64) > 1 ||
          initial.top < initial.navBottom || Math.abs(initial.bottom - initial.viewport) > 1) {
        errors.push(`scroll-clearance(${width}): initial geometry ${JSON.stringify(initial)}`);
      }
      await page.evaluate(() => {
        document.getElementById('layout-scroll-probe')?.remove();
        const fixture = document.createElement('section');
        fixture.id = 'layout-scroll-probe';
        const start = document.createElement('button');
        start.id = 'layout-scroll-start'; start.textContent = 'Synthetic scroll target';
        const spacer = document.createElement('div'); spacer.style.height = `${innerHeight * 2}px`;
        const end = document.createElement('button');
        end.id = 'layout-scroll-end'; end.textContent = 'Synthetic bottom target';
        fixture.append(start, spacer, end);
        document.querySelector('main').firstElementChild.append(fixture);
      });
      await page.mouse.move(width / 2, MOBILE.height / 2);
      await page.mouse.wheel(0, 200);
      await page.waitForFunction(() => document.querySelector('main').scrollTop > 0);
      await page.locator('#layout-scroll-start').evaluate(el => el.scrollIntoView({ block: 'start' }));
      const scrolled = await page.evaluate(() => {
        const main = document.querySelector('main');
        const target = document.getElementById('layout-scroll-start');
        const box = target.getBoundingClientRect();
        const nav = document.querySelector('[data-testid="nav-drawer-trigger"]');
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return { top: main.getBoundingClientRect().top, targetTop: box.top,
          scrollTop: main.scrollTop, navBottom: nav.getBoundingClientRect().bottom,
          targetHit: target === hit || target.contains(hit) };
      });
      geometry.push({ width, phase: "scrolled", ...scrolled });
      if (Math.abs(scrolled.top - 64) > 1 || scrolled.targetTop < scrolled.navBottom ||
          Math.abs(scrolled.targetTop - scrolled.top) > 1 || !scrolled.targetHit || scrolled.scrollTop <= 0) {
        errors.push(`scroll-clearance(${width}): scrolled geometry ${JSON.stringify(scrolled)}`);
      }
      // Synthetic negative control: recreate the previous CSS, then restore it even on failure.
      const oldCssControl = await page.evaluate(() => {
        const main = document.querySelector('main');
        const wrapper = main.firstElementChild;
        const target = document.getElementById('layout-scroll-start');
        const nav = document.querySelector('[data-testid="nav-drawer-trigger"]');
        const mainStyle = main.getAttribute('style');
        const wrapperStyle = wrapper.getAttribute('style');
        try {
          main.style.marginTop = '0px';
          wrapper.style.paddingTop = '64px';
          target.scrollIntoView({ block: 'start' });
          const box = target.getBoundingClientRect();
          const navBox = nav.getBoundingClientRect();
          const left = Math.max(box.left, navBox.left), right = Math.min(box.right, navBox.right);
          const top = Math.max(box.top, navBox.top), bottom = Math.min(box.bottom, navBox.bottom);
          const overlaps = right > left && bottom > top;
          const hit = overlaps ? document.elementFromPoint((left + right) / 2, (top + bottom) / 2) : null;
          return { synthetic: true, mainTop: main.getBoundingClientRect().top,
            targetTop: box.top, overlaps, blockedByTrigger: hit === nav || nav.contains(hit) };
        } finally {
          if (mainStyle === null) main.removeAttribute('style'); else main.setAttribute('style', mainStyle);
          if (wrapperStyle === null) wrapper.removeAttribute('style'); else wrapper.setAttribute('style', wrapperStyle);
          target.scrollIntoView({ block: 'start' });
        }
      });
      geometry.push({ width, phase: 'synthetic-old-css-negative-control', ...oldCssControl });
      if (!oldCssControl.overlaps || !oldCssControl.blockedByTrigger || Math.abs(oldCssControl.mainTop) > 1) {
        errors.push(`scroll-clearance(${width}): old-CSS control did not reproduce overlap ${JSON.stringify(oldCssControl)}`);
      }
      await page.locator('#layout-scroll-end').evaluate(el => el.scrollIntoView({ block: 'end' }));
      const bottomReachable = await page.evaluate(() => {
        const main = document.querySelector('main').getBoundingClientRect();
        const target = document.getElementById('layout-scroll-end');
        const box = target.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return box.top >= main.top && box.bottom <= main.bottom + 1 &&
          (target === hit || target.contains(hit));
      });
      geometry.push({ width, phase: "bottom", bottomReachable });
      await saveEvidence(page, `scroll-bottom-${width}`, errors);
      if (!bottomReachable) errors.push(`scroll-clearance(${width}): bottom target not reachable`);
    }
    await openDrawer(page);
    await page.setViewportSize({ width: 768, height: MOBILE.height });
    await page.waitForFunction(() => document.querySelector('[data-testid="app-sidebar"]').dataset.mobileOpen === 'false');
    const desktop = await page.evaluate(() => {
      const main = document.querySelector('main'); main.scrollTop = 0;
      return { top: main.getBoundingClientRect().top,
        contentTop: main.firstElementChild.getBoundingClientRect().top + parseFloat(getComputedStyle(main.firstElementChild).paddingTop),
        inert: main.hasAttribute('inert'), hidden: main.hasAttribute('aria-hidden'),
        overflow: document.body.style.overflow };
    });
    geometry.push({ width: 768, phase: "desktop", ...desktop });
    if (Math.abs(desktop.top) > 1 || Math.abs(desktop.contentTop - 28) > 1 ||
        desktop.inert || desktop.hidden || desktop.overflow === 'hidden' || await trigger(page).isVisible()) {
      errors.push(`scroll-clearance(768): desktop reset ${JSON.stringify(desktop)}`);
    }
    await page.setViewportSize({ width: 767, height: MOBILE.height });
    await trigger(page).waitFor({ state: 'visible' });
    if (await drawerOpen(page)) errors.push('scroll-clearance(767): drawer reopened after desktop resize');
    const restoredTop = await page.locator('main').evaluate(el => el.getBoundingClientRect().top);
    if (Math.abs(restoredTop - 64) > 1) errors.push(`scroll-clearance(767): restored top ${restoredTop}`);
  } catch (e) {
    errors.push(`scroll-clearance: fatal ${e.message}`);
  } finally {
    await saveEvidence(page, "scroll-clearance", errors);
    await writeFile(path.join(evidenceDir, "scroll-geometry.json"), JSON.stringify(geometry, null, 2));
    await context.close();
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
    await caseScrollClearance(browser, errors);
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
  console.log(`PASS layout-navigation (${browserLabel}) port=${frontendPort} cases=10`);
}

main();
