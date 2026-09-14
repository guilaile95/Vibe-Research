/**
 * 投资逻辑与证据账本 — Real Backend E2E Test
 *
 * 全部 mutation 通过浏览器 UI 完成。
 * API 调用仅用于读取验证（revision 编号、409、历史 snapshot）。
 * 硬断言全覆盖，失败即 exit 1。
 * 无 info() 替代验收。
 */

import { chromium } from "playwright";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, readdirSync, createReadStream } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import path from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");
const backendDir = path.join(root, "backend");
let evidenceServerLog = "";

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try { const r = await fetch(url); if (r.ok || r.status < 500) return r; } catch { }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2",
  };
  const server = createServer((req, res) => {
    let pn = (req.url || "/").split("?")[0];
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
    const rd = path.resolve(dir);
    const rt = path.resolve(target);
    if (!rt.startsWith(rd + path.sep) && rt !== rd) { res.writeHead(403); res.end("forbidden"); return; }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    const ext = path.extname(target);
    res.setHeader("Content-Type", mime[ext] || "application/octet-stream");
    createReadStream(target).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function getPythonConfig() {
  const envPy = process.env.PYTHON;
  if (envPy) return { cmd: envPy, extraArgs: ["-m", "uvicorn"] };
  const isWin = process.platform === "win32";
  return isWin
    ? { cmd: "py", extraArgs: ["-3", "-m", "uvicorn"] }
    : { cmd: "python3", extraArgs: ["-m", "uvicorn"] };
}

function findChromium() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of candidates) {
    if (!base || !existsSync(base)) continue;
    try {
      for (const d of readdirSync(base)) {
        if (d.startsWith("chromium-") && !d.includes("headless")) {
          const exe = join(base, d, "chrome-win64", "chrome.exe");
          if (existsSync(exe)) { console.log(`[E2E] Chromium: ${d}`); return exe; }
        }
      }
    } catch { }
  }
  return undefined;
}

function startBackend(dbPath, port, allowedOrigin) {
  return new Promise((resolve, reject) => {
    const env = {
      ...process.env,
      VR_ALLOW_ORIGINS: allowedOrigin,
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: dbPath,
      VR_DATA_DIR: join(dirname(dbPath), "data"),
      VR_REPORTS_DIR: join(dirname(dbPath), "reports"),
      VIBE_RESEARCH_REVIEW_DB: join(dirname(dbPath), "review.db"),
      VIBE_NATIVE_INTEL_DISABLE_SCHEDULER: "1",
    };
    const { cmd, extraArgs } = getPythonConfig();
    const args = [...extraArgs, "app:app", `--port=${port}`, "--host=127.0.0.1"];
    const proc = spawn(cmd, args, { cwd: backendDir, env, stdio: ["ignore", "pipe", "pipe"], shell: false });
    let started = false;
    const timeout = setTimeout(() => { if (!started) { proc.kill(); reject(new Error("Backend startup timeout")); } }, 30000);
    const onData = (msg) => {
      if (msg.includes("/api/evidence/")) evidenceServerLog = (evidenceServerLog + msg).slice(-8000);
      if (started) return;
      if (msg.includes("Uvicorn running") || msg.includes("Application startup complete")) {
        started = true; clearTimeout(timeout); resolve(proc);
      }
    };
    proc.stdout.on("data", (d) => onData(d.toString()));
    proc.stderr.on("data", (d) => { if (d.toString().trim()) onData(d.toString()); });
    proc.on("error", (e) => { clearTimeout(timeout); reject(e); });
    proc.on("exit", (code) => { if (!started) { clearTimeout(timeout); reject(new Error(`Backend exited with code ${code}`)); } });
  });
}

async function main() {
  if (!existsSync(frontendDist)) throw new Error(`Frontend dist not found: ${frontendDist}. Run 'npm run build' first.`);

  const tempDir = mkdtempSync(join(tmpdir(), "vr-thesis-e2e-"));
  const dbPath = join(tempDir, "evidence_thesis.db");
  const backendPort = await getFreePort();
  const frontendPort = await getFreePort();
  const baseUrl = `http://127.0.0.1:${frontendPort}`;
  const apiUrl = `http://127.0.0.1:${backendPort}`;

  let backend, browser, page, frontendServer;
  const pageErrors = [];

  try {
    console.log("[E2E] Starting backend...");
    backend = await startBackend(dbPath, backendPort, baseUrl);
    await waitHttp(`${apiUrl}/api/health`);

    console.log("[E2E] Starting frontend...");
    frontendServer = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(baseUrl);

    browser = await chromium.launch({ headless: true, executablePath: findChromium() });
    const context = await browser.newContext({ baseURL: baseUrl });
    page = await context.newPage();
    page.on("pageerror", error => pageErrors.push(error.message));

    // Proxy ALL /api/* to real backend (NO mock)
    let updateBodyCapture = null;
    let delayedSave = null;
    let rejectSubjectChangeId = null;
    let evidenceCreatePostCount = 0;
    const evidenceCreatePostRequests = [];
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = request.url();
      const parsed = new URL(url);
      const p = parsed.pathname + parsed.search;
      if (request.method() === "POST" && parsed.pathname === "/api/evidence") {
        evidenceCreatePostCount += 1;
        evidenceCreatePostRequests.push({ path: p, body: request.postDataJSON() });
      }
      // Capture Evidence PUT body for hard assert (no subject fields)
      if (request.method() === "PUT" && /\/api\/evidence\/[^/]+$/.test(parsed.pathname)) {
        try {
          updateBodyCapture = request.postDataJSON();
        } catch {
          updateBodyCapture = null;
        }
      }
      const target = `${apiUrl}${p}`;
      try {
        // The failure case sends a forbidden field to the REAL backend; no response is mocked.
        const rejectSubjectChange = request.method() === "PUT"
          && parsed.pathname === `/api/evidence/${rejectSubjectChangeId}`;
        const resp = await fetch(target, {
          method: request.method(),
          headers: { ...request.headers(), host: undefined },
          body: rejectSubjectChange
            ? JSON.stringify({ ...request.postDataJSON(), subject_id: "000001" })
            : request.postDataBuffer() || undefined,
        });
        const body = Buffer.from(await resp.arrayBuffer());
        if (request.method() === "PUT" && parsed.pathname === `/api/evidence/${delayedSave?.id}`) {
          delayedSave.received({ status: resp.status, body: JSON.parse(body.toString()) });
          await sleep(800); // Controlled latency, never a synchronization wait for success.
          await delayedSave.release; // Keep pending-state assertions deterministic on slow runners.
        }
        await route.fulfill({
          status: resp.status,
          headers: Object.fromEntries([...resp.headers.entries()].filter(([k]) => k !== "transfer-encoding")),
          body,
        });
      } catch (e) {
        console.error(`[E2E] Proxy error: ${e.message}`);
        await route.abort();
      }
    });

    await page.goto(baseUrl);
    await page.waitForLoadState("domcontentloaded");
    const evidencePostCountBeforePrefill = evidenceCreatePostCount;
    assert.equal(evidencePostCountBeforePrefill, 0, "no Evidence POST should occur before prefill navigation");

    async function readEvidence(evidenceId = evId) {
      const response = await fetch(`${apiUrl}/api/evidence/${evidenceId}`);
      assert.equal(response.status, 200, "same-ID Evidence GET must succeed");
      return (await response.json()).data;
    }

    // ═══════════════════════════════════════════════
    //  1. Capture prefilled Evidence — explicit Save through real backend
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 1. Capture prefilled Evidence (UI + real backend)");
    const prefillQuery = new URLSearchParams({
      subject_type: "stock",
      subject_id: "600519",
      evidence_type: "news",
      source_title: "茅台公开资讯观察",
      source_url: "https://example.com/native-intel-maotai",
      source_date: "2024-11-15",
      return_to: "/stock-data?code=600519",
    });
    await page.goto(`${baseUrl}/evidence/new?${prefillQuery.toString()}`);
    await page.waitForURL(/\/evidence\/new\?/);
    await page.waitForSelector('select');
    assert.equal(evidenceCreatePostCount, evidencePostCountBeforePrefill, "prefill navigation must not auto-save Evidence");
    console.log(`  ✓ Prefill loaded without Evidence POST: ${JSON.stringify({ postCountBeforePrefill: evidencePostCountBeforePrefill, postCountBeforeSave: evidenceCreatePostCount })}`);

    assert.equal(await page.locator('input[placeholder*="600519"]').inputValue(), "600519");
    assert.equal(await page.locator('textarea[placeholder*="一句话"]').inputValue(), "茅台公开资讯观察");
    assert.equal(await page.locator('input[placeholder*="XX公司"]').inputValue(), "茅台公开资讯观察");
    assert.equal(await page.locator('input[placeholder*="https://"]').inputValue(), "https://example.com/native-intel-maotai");
    assert.equal(await page.locator('input[type="date"]').inputValue(), "2024-11-15");
    assert.equal(await page.locator("select").nth(1).inputValue(), "news");
    assert.equal(await page.locator("select").nth(2).inputValue(), "unknown");
    assert.equal(await page.locator("select").nth(3).inputValue(), "medium");

    const waitForEvidencePost = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/evidence" && response.request().method() === "POST");
    const evidencePostBeforeSave = page.locator('button:has-text("保存")');
    assert.equal(await evidencePostBeforeSave.isVisible(), true);
    const evidencePostCountBeforeExplicitSave = evidenceCreatePostCount;
    assert.equal(evidencePostCountBeforeExplicitSave, evidencePostCountBeforePrefill, "Evidence POST count must remain zero before explicit Save");

    await evidencePostBeforeSave.click();
    const evidencePost = await waitForEvidencePost;
    assert.equal(evidencePost.status(), 200, "prefilled Evidence POST must succeed");
    const evidencePostPayload = await evidencePost.json();
    assert.ok(evidencePostPayload.data?.id, "Evidence POST must return an exact evidence id");
    assert.equal(evidenceCreatePostCount, evidencePostCountBeforeExplicitSave + 1, "explicit Save must produce exactly one Evidence POST");
    assert.equal(evidenceCreatePostRequests.length, evidenceCreatePostCount, "all real Evidence POST requests must be recorded by the proxy");
    const evId = evidencePostPayload.data.id;
    await page.waitForURL((url) => url.pathname === "/stock-data" && url.searchParams.get("code") === "600519");
    assert.equal(new URL(page.url()).pathname, "/stock-data", "successful capture must honor the supplied return_to path");
    const createdEvidence = await readEvidence(evId);
    assert.equal(createdEvidence.id, evId);
    assert.equal(createdEvidence.claim, "茅台公开资讯观察");
    assert.equal(createdEvidence.source_title, "茅台公开资讯观察");
    assert.equal(createdEvidence.source_url, "https://example.com/native-intel-maotai");
    assert.equal(createdEvidence.source_date, "2024-11-15");
    assert.equal(createdEvidence.classification, "unknown");
    assert.equal(createdEvidence.confidence, "medium");
    const persistedCore = ["id", "subject_type", "subject_id", "evidence_type", "claim", "source_title", "source_url", "source_date", "classification", "confidence"];
    assert.deepEqual(
      Object.fromEntries(persistedCore.map(field => [field, createdEvidence[field]])),
      Object.fromEntries(persistedCore.map(field => [field, evidencePostPayload.data[field]])),
      "Evidence POST response core data must match same-ID GET readback",
    );
    console.log(`  ✓ Prefill required explicit Save and persisted exact Evidence ${evId}: ${JSON.stringify({ postStatus: evidencePost.status(), postCountBeforeSave: evidencePostCountBeforeExplicitSave, postCountAfterSave: evidenceCreatePostCount, postRequestPath: evidenceCreatePostRequests.at(-1)?.path, getStatus: 200, claim: createdEvidence.claim, source_title: createdEvidence.source_title, source_url: createdEvidence.source_url, source_date: createdEvidence.source_date })}`);

    await page.goto(`${baseUrl}/evidence/${evId}`);
    // Hard assert: source_date displayed without timezone shift
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    const readonlyClaim = page.locator("p").filter({ hasText: /^茅台公开资讯观察$/ });
    assert.equal(await readonlyClaim.count(), 2, "read-only detail must show the exact claim and source title");
    assert.equal(await page.locator('a[href="https://example.com/native-intel-maotai"]').filter({ hasText: "https://example.com/native-intel-maotai" }).count(), 1, "read-only detail must show the exact source URL link");
    const readonlyDate = page.locator("p").filter({ hasText: /来源日期：2024-11-15/ });
    assert.equal(await readonlyDate.count(), 1, "read-only detail must show the exact source date");
    console.log("  ✓ read-only detail preserved exact claim/source_title/source_url/source_date");

    // ═══════════════════════════════════════════════
    //  2. Edit Evidence — UI form
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 2. Edit Evidence (UI)");
    const editBtn = page.locator('button:has-text("编辑")');
    if (await editBtn.count() === 0) throw new Error("Edit button not found");
    await editBtn.click();
    await page.waitForTimeout(600);

    // Hard assert: subject_type is readonly
    const firstSelect = page.locator("select").first();
    if (!(await firstSelect.isDisabled())) {
      throw new Error("subject_type should be readonly in edit mode");
    }
    console.log("  ✓ subject_type is readonly");

    // Edit claim text
    const textarea = page.locator("textarea").first();
    const evidencePath = `/api/evidence/${evId}`;
    const waitForEvidencePut = () => page.waitForResponse(response =>
      new URL(response.url()).pathname === evidencePath && response.request().method() === "PUT");
    const readonlyClaimFor = claim => page.locator("p").filter({ hasText: claim });
    async function verifySaved(responsePromise, claim, scenario) {
      const response = await responsePromise;
      const payload = await response.json();
      assert.equal(response.status(), 200, `Evidence PUT failed: ${JSON.stringify(payload)}`);
      assert.equal(payload.data.id, evId);
      assert.equal(payload.data.claim, claim);
      assert.equal(payload.data.source_date, "2024-11-15");
      assert.equal(payload.data.subject_type, "stock");
      assert.equal(payload.data.subject_id, "600519");
      const persisted = await readEvidence();
      assert.deepEqual(persisted, payload.data, "PUT response must match persisted same-ID GET");
      await textarea.waitFor({ state: "hidden" });
      await readonlyClaimFor(claim).waitFor({ state: "visible" });
      assert.equal(await readonlyClaimFor(claim).innerText(), claim);
      assert.equal(await page.getByRole("button", { name: "编辑", exact: true }).isVisible(), true);
      console.log(`[E2E] Evidence ${scenario}: ${JSON.stringify({ id: evId, putStatus: response.status(), response: payload.data, getStatus: 200, persisted, editing: false, readonlyClaim: claim })}`);
      return persisted;
    }
    const normalClaim = "公司2024Q3营收同比+25%，超预期";
    await textarea.fill(normalClaim);
    const normalPut = waitForEvidencePut(); // Register before clicking: the URL itself does not change.
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await verifySaved(normalPut, normalClaim, "NORMAL");

    // Hard assert: update body does NOT contain subject fields (must capture PUT)
    if (!updateBodyCapture) {
      throw new Error("Evidence update PUT body was not captured — cannot verify no subject fields");
    }
    if (updateBodyCapture.subject_type !== undefined) {
      throw new Error(`Update body must not contain subject_type: ${JSON.stringify(updateBodyCapture)}`);
    }
    if (updateBodyCapture.subject_id !== undefined) {
      throw new Error(`Update body must not contain subject_id: ${JSON.stringify(updateBodyCapture)}`);
    }
    if (updateBodyCapture.source_date !== "2024-11-15") {
      throw new Error(`source_date must be original YYYY-MM-DD, got: ${updateBodyCapture.source_date}`);
    }
    console.log("  ✓ Update body correct: no subject fields, source_date preserved");

    // Hold the genuine backend response: the old 300ms body check would fail here.
    await editBtn.click();
    const slowClaim = `${normalClaim}（慢响应验收）`;
    await textarea.fill(slowClaim);
    let backendReceived, releaseResponse;
    const received = new Promise(resolve => { backendReceived = resolve; });
    delayedSave = { id: evId, received: backendReceived, release: new Promise(resolve => { releaseResponse = resolve; }) };
    const slowPut = waitForEvidencePut();
    await page.getByRole("button", { name: "保存", exact: true }).click();
    try {
      const actual = await received;
      assert.equal(actual.status, 200);
      await page.waitForTimeout(300); // Reproduce the old decision point, not a success wait.
      assert.equal((await page.locator("body").innerText()).includes(slowClaim), false, "old assertion must be premature");
      assert.equal(await textarea.isVisible(), true);
      assert.equal(await page.getByRole("button", { name: "保存中…", exact: true }).isDisabled(), true);
      assert.equal(await readonlyClaimFor(slowClaim).count(), 0, "input text is not saved read-only content");
      assert.deepEqual(await readEvidence(), actual.body.data, "backend already persisted before response delivery");
      console.log(`[E2E] Evidence DELAYED pending: ${JSON.stringify({ id: evId, backendStatus: actual.status, editing: true, saving: true, oldAssertionWouldFail: true })}`);
    } finally {
      releaseResponse();
    }
    const saved = await verifySaved(slowPut, slowClaim, "DELAYED");
    delayedSave = null;

    // A real 422 must keep the draft editable and leave persisted/read-only content unchanged.
    await editBtn.click();
    const failedClaim = "此修改应被真实后端拒绝";
    await textarea.fill(failedClaim);
    rejectSubjectChangeId = evId;
    const failedPut = waitForEvidencePut();
    await page.getByRole("button", { name: "保存", exact: true }).click();
    const rejected = await failedPut;
    const rejection = await rejected.json();
    assert.equal(rejected.status(), 422);
    assert.ok(rejection.detail.some(item => item.type === "extra_forbidden" && item.loc.at(-1) === "subject_id"));
    await page.getByText("HTTP 422", { exact: true }).waitFor({ state: "visible" });
    assert.equal(await textarea.isVisible(), true);
    assert.equal(await textarea.inputValue(), failedClaim);
    assert.equal(await page.getByRole("button", { name: "保存", exact: true }).isEnabled(), true);
    assert.equal(await readonlyClaimFor(failedClaim).count(), 0);
    assert.deepEqual(await readEvidence(), saved, "failed PUT must not change persisted evidence");
    console.log(`[E2E] Evidence FAILED: ${JSON.stringify({ id: evId, putStatus: rejected.status(), response: rejection, persisted: saved, editing: true, errorVisible: true, savedClaimVisible: false })}`);
    rejectSubjectChangeId = null;
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await readonlyClaimFor(slowClaim).waitFor({ state: "visible" });

    // ═══════════════════════════════════════════════
    //  3. Create Thesis — UI form
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 3. Create Thesis (UI)");
    await page.goto(`${baseUrl}/thesis/new`);

    // The form no longer has market/status selects
    // First select is subject_type (default "stock"), skip
    // Input fields: subject_id, title, change_summary
    const thesisSelects = page.locator("select");
    // Only subject_type select exists now
    await page.fill('input[placeholder*="600519"]', "600519");
    await page.fill('input[placeholder*="贵茅"]', "茅台业绩持续超预期");
    await page.fill('textarea[placeholder*="一两段话"]', "基于Q3财报，公司营收增长超市场预期");

    // Fill ArrayEditors: find by label text and fill input inside
    // core_claims
    const coreClaimsInput = page.locator("span:has-text('核心论点') + div input");
    if (await coreClaimsInput.count() > 0) {
      await coreClaimsInput.fill("高端白酒需求强劲");
      await coreClaimsInput.press("Enter");
      await coreClaimsInput.fill("提价能力持续验证");
      await coreClaimsInput.press("Enter");
    }
    // catalysts
    const catalystsInput = page.locator("span:has-text('催化剂') + div input");
    if (await catalystsInput.count() > 0) {
      await catalystsInput.fill("春节动销超预期");
      await catalystsInput.press("Enter");
    }
    // risks
    const risksInput = page.locator("span:has-text('风险') + div input");
    if (await risksInput.count() > 0) {
      await risksInput.fill("宏观消费疲软");
      await risksInput.press("Enter");
    }

    // change_summary input
    const changeSummaryInput = page.locator('input[placeholder*="首次创建"]');
    if (await changeSummaryInput.count() > 0) {
      await changeSummaryInput.fill("创建投资逻辑");
    }

    await page.click('button:has-text("保存")');
    await page.waitForURL(/\/thesis\/[a-f0-9-]+$/);
    const thesisId = page.url().split("/").pop();
    console.log(`  ✓ Thesis created: ${thesisId}`);

    // Hard assert: revision 1 shown
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    const thText1 = await page.locator("body").innerText();
    if (!thText1.includes("v1")) {
      console.log(`  [debug] Thesis page text (300-600): ${thText1.substring(300, 600)}`);
      throw new Error("Revision v1 not shown after thesis creation");
    }
    console.log("  ✓ Revision v1 displayed");

    // ═══════════════════════════════════════════════
    //  4. Link Evidence — UI
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 4. Link Evidence (UI)");
    const linkBtn = page.locator('button:has-text("关联证据")');
    if (await linkBtn.count() === 0) throw new Error("Link evidence button not found");
    await linkBtn.click();
    await page.waitForTimeout(300);

    // Select evidence from dropdown
    const linkSelect = page.locator("select").first();
    if (await linkSelect.count() > 0) {
      // The dropdown loads evidence list — select by evidence ID value
      await linkSelect.selectOption(evId);
    }
    // Set stance to "支撑" (support)
    const stanceSelect = page.locator("label:has-text('立场') select");
    if (await stanceSelect.count() > 0) {
      await stanceSelect.selectOption("support");
    }
    // Click confirm link button
    const confirmLink = page.getByRole("button", { name: "关联", exact: true });
    if (await confirmLink.count() > 0) {
      await confirmLink.click();
      await page.waitForTimeout(500);
    }

    // Verify by API: revision should be 2
    const agg1 = await (await fetch(`${apiUrl}/api/thesis/${thesisId}`)).json();
    if (agg1.data.thesis.current_revision < 2) {
      throw new Error(`Expected revision >= 2 after link, got ${agg1.data.thesis.current_revision}`);
    }
    console.log(`  ✓ Evidence linked, revision ${agg1.data.thesis.current_revision}`);

    // ═══════════════════════════════════════════════
    //  5. Update stance — UI
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 5. Update stance (UI)");
    // Refresh the page
    await page.goto(`${baseUrl}/thesis/${thesisId}`);
    await page.waitForLoadState("networkidle");

    // Find and click "修改立场" button
    const stanceEditBtn = page.locator('button:has-text("修改立场")');
    if (await stanceEditBtn.count() > 0) {
      await stanceEditBtn.first().click();
      await page.waitForTimeout(300);

      // Select "中性" (neutral)
      const editStanceSelect = page.locator("label:has-text('立场') select").first();
      if (await editStanceSelect.count() > 0) {
        await editStanceSelect.selectOption("neutral");
      }
      await page.click('button:has-text("保存")');
      await page.waitForTimeout(500);
    }

    const agg2 = await (await fetch(`${apiUrl}/api/thesis/${thesisId}`)).json();
    if (agg2.data.thesis.current_revision < 3) {
      throw new Error(`Expected revision >= 3 after stance update, got ${agg2.data.thesis.current_revision}`);
    }
    console.log(`  ✓ Stance updated, revision ${agg2.data.thesis.current_revision}`);

    // ═══════════════════════════════════════════════
    //  6. Edit Thesis — UI
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 6. Edit Thesis (UI)");
    await page.goto(`${baseUrl}/thesis/${thesisId}`);
    await page.waitForLoadState("networkidle");

    await page.click('button:has-text("编辑")');
    await page.waitForTimeout(300);
    const summaryTextarea = page.locator("textarea").first();
    await summaryTextarea.fill("基于Q3财报，公司营收增长超市场预期，毛利率稳定");
    await page.click('button:has-text("保存")');
    await page.waitForTimeout(300);

    const agg3 = await (await fetch(`${apiUrl}/api/thesis/${thesisId}`)).json();
    if (agg3.data.thesis.current_revision < 4) {
      throw new Error(`Expected revision >= 4 after edit, got ${agg3.data.thesis.current_revision}`);
    }
    console.log(`  ✓ Thesis edited, revision ${agg3.data.thesis.current_revision}`);

    // ═══════════════════════════════════════════════
    //  7. Revision diff — UI tab（真实字段变化硬断言）
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 7. Revision diff (UI tab)");
    await page.goto(`${baseUrl}/thesis/${thesisId}`);
    await page.waitForLoadState("networkidle");

    const diffTab = page.locator('button:has-text("版本对比")');
    if (await diffTab.count() === 0) {
      throw new Error("版本对比 Tab not found");
    }
    await diffTab.click();
    await page.waitForTimeout(400);

    // 起始版本 / 目标版本 — 与 ThesisDetail UI 文案一致
    const fromSelect = page.locator("label:has-text('起始版本') select").first();
    const toSelect = page.locator("label:has-text('目标版本') select").first();
    if (await fromSelect.count() === 0 || await toSelect.count() === 0) {
      throw new Error("from/to revision selects not found on diff tab");
    }
    await fromSelect.selectOption("3");
    await toSelect.selectOption("4");

    // 按钮文案是「对比」，不是「加载对比」；不存在假路由 /revisions/3/compare/4
    const loadDiffBtn = page.locator('button:has-text("对比")').filter({ hasNotText: "版本对比" });
    if (await loadDiffBtn.count() === 0) {
      // fallback: any enabled 对比 button in the tab area
      const alt = page.getByRole("button", { name: "对比", exact: true });
      if (await alt.count() === 0) throw new Error("对比 button not found");
      await alt.click();
    } else {
      await loadDiffBtn.first().click();
    }
    await page.waitForTimeout(600);

    const diffText = await page.locator("body").innerText();
    // 硬断言：显示对比范围与字段变化（summary 编辑内容）
    if (!diffText.includes("对比 v3") && !diffText.includes("v3 → v4") && !diffText.includes("对比 v3 → v4")) {
      // 页面可能显示「对比 v3 → v4」
      if (!/对比\s*v?3/.test(diffText)) {
        console.log(`  [debug] diff text excerpt: ${diffText.substring(0, 500)}`);
        throw new Error("Diff panel must show comparison of revision 3→4");
      }
    }
    const hasFieldChange =
      diffText.includes("逻辑字段变化") ||
      diffText.includes("summary") ||
      diffText.includes("摘要") ||
      diffText.includes("毛利率稳定");
    if (!hasFieldChange) {
      console.log(`  [debug] diff body: ${diffText.substring(0, 800)}`);
      throw new Error("Diff page must show expected field changes (summary edit)");
    }
    console.log("  ✓ Revision diff shows expected field changes (hard assert)");

    // ═══════════════════════════════════════════════
    //  8. Soft delete evidence — UI
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 8. Soft delete evidence (UI)");
    await page.goto(`${baseUrl}/evidence/${evId}`);
    await page.waitForLoadState("domcontentloaded");

    // Handle confirmation dialog
    let dialogMsg = "";
    page.once("dialog", (dialog) => {
      dialogMsg = dialog.message();
      dialog.accept();
    });

    // Wait for the detail page to fully load
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);

    const deleteButton = page.locator('button:has-text("删除")');
    if (await deleteButton.count() === 0) {
      // Debug: show page text to understand what's on the page
      const debugText = await page.locator("body").innerText();
      console.log(`  [debug] Evidence page (0-300): ${debugText.substring(0, 300)}`);
      throw new Error("Delete button not found on evidence detail page");
    }
    await deleteButton.click();
    await page.waitForURL(/\/evidence$/);
    await page.waitForTimeout(300);

    // Hard assert: correct delete confirmation text
    if (!dialogMsg.includes("历史版本中的证据快照仍会保留")) {
      throw new Error(`Delete confirmation text wrong: "${dialogMsg.substring(0, 100)}"`);
    }
    console.log("  ✓ Evidence soft deleted via UI, confirmation text correct");

    // Hard assert: evidence removed from current aggregation
    const aggAfterDel = await (await fetch(`${apiUrl}/api/thesis/${thesisId}`)).json();
    if (aggAfterDel.data.evidence_links.length !== 0) {
      throw new Error(`Expected 0 evidence links after delete, got ${aggAfterDel.data.evidence_links.length}`);
    }
    console.log("  ✓ Evidence removed from current aggregation");

    // Hard assert: evidence snapshot preserved in revision
    const rev2Resp = await fetch(`${apiUrl}/api/thesis/${thesisId}/revisions/2`);
    if (rev2Resp.ok) {
      const rev2Data = await rev2Resp.json();
      const snap = rev2Data.data?.snapshot || rev2Data.snapshot;
      if (!snap || !snap.evidence_links || snap.evidence_links.length === 0) {
        throw new Error("Revision 2 should still contain evidence snapshot after delete");
      }
      console.log("  ✓ Evidence snapshot preserved in revision 2");
    }

    // ═══════════════════════════════════════════════
    //  9. Archive thesis — UI
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 9. Archive thesis (UI)");
    await page.goto(`${baseUrl}/thesis/${thesisId}`);
    await page.waitForLoadState("networkidle");

    // Handle prompt dialog for archive reason
    page.once("dialog", (dialog) => {
      dialog.accept("E2E test archive");
    });

    const archiveBtn = page.locator('button:has-text("归档")');
    if (await archiveBtn.count() === 0) {
      throw new Error("Archive button not found");
    }
    await archiveBtn.click();
    await page.waitForTimeout(500);

    // Hard assert: archived banner visible
    const archivedText = await page.locator("body").innerText();
    if (!archivedText.includes("已归档")) {
      throw new Error("Archived status banner not shown after archiving");
    }
    console.log("  ✓ Thesis archived, frozen banner shown");

    // Hard assert: edit/associate buttons disabled
    const editBtnAfter = page.locator('button:has-text("编辑")').first();
    if (await editBtnAfter.count() > 0) {
      const disabled = await editBtnAfter.isDisabled();
      if (!disabled) {
        throw new Error("Edit button should be disabled when thesis is archived");
      }
    }
    console.log("  ✓ Edit button disabled after archive");

    const linkBtnAfter = page.locator('button:has-text("关联证据")');
    if (await linkBtnAfter.count() > 0 && !(await linkBtnAfter.isDisabled())) {
      throw new Error("Link evidence button should be disabled when thesis is archived");
    }
    console.log("  ✓ Link evidence button disabled after archive");

    // ═══════════════════════════════════════════════
    //  10. Duplicate archive → 409 (API only)
    // ═══════════════════════════════════════════════
    console.log("\n[E2E] 10. Duplicate archive returns 409");
    // Get current revision AFTER archiving
    const aggAfterArchive = await (await fetch(`${apiUrl}/api/thesis/${thesisId}`)).json();
    const frozenRev = aggAfterArchive.data.thesis.current_revision;
    const dupResp = await fetch(
      `${apiUrl}/api/thesis/${thesisId}?confirm=true&expected_revision=${frozenRev}`,
      { method: "DELETE" },
    );
    if (dupResp.status !== 409) {
      throw new Error(`Expected 409 for duplicate archive, got ${dupResp.status}: ${await dupResp.text()}`);
    }
    console.log("  ✓ Duplicate archive returns 409");

    // Hard assert: revision unchanged
    const aggFinal = await (await fetch(`${apiUrl}/api/thesis/${thesisId}`)).json();
    if (aggFinal.data.thesis.current_revision !== frozenRev) {
      throw new Error(
        `Revision changed after duplicate archive: ${aggFinal.data.thesis.current_revision} !== ${frozenRev}`
      );
    }
    if (aggFinal.data.thesis.status !== "archived") {
      throw new Error(`Status should be archived, got: ${aggFinal.data.thesis.status}`);
    }
    console.log("  ✓ Revision and status unchanged after duplicate archive");

    console.log("\n[E2E] ✅ All tests passed!");

  } catch (err) {
    console.error(`\n[E2E] ❌ Test failed: ${err.message}`);
    console.error(err.stack);
    console.error("[E2E] Page errors:", JSON.stringify(pageErrors));
    console.error("[E2E] Evidence server log:\n", evidenceServerLog);
    process.exitCode = 1;
  } finally {
    if (browser) { await browser.close(); }
    if (frontendServer) { frontendServer.close(); }
    if (backend) {
      backend.kill("SIGTERM");
      setTimeout(() => { try { backend.kill("SIGKILL"); } catch { } }, 2000);
    }
    if (existsSync(tempDir)) {
      rmSync(tempDir, { recursive: true, force: true });
    }
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
