/**
 * P0-DC1 Decision Commit vertical — isolated real FastAPI + Chromium E2E.
 *
 * Campaign → frozen Current Thesis → same-as-of Preview → explicit checkbox
 * → existing Frozen Decision service/store → backend GET re-read → Decision
 * Inbox.  The only persistence location is a temporary VR_DATA_DIR.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { request as httpRequest } from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { seedActiveCampaign } from "./campaign-active-fixture.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const backendDir = path.join(root, "backend");
const frontendDist = path.join(root, "frontend", "dist");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** 每次新建 TCP 连接的代理请求（Connection: close，规避 stale keep-alive ECONNRESET）。 */
function proxyRequest(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const forwardHeaders = { ...headers, connection: "close" };
    delete forwardHeaders.host;
    const req = httpRequest(
      {
        hostname: target.hostname,
        port: target.port,
        path: `${target.pathname}${target.search}`,
        method,
        headers: forwardHeaders,
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () =>
          resolve({
            status: res.statusCode ?? 599,
            headers: Object.fromEntries(
              Object.entries(res.headers)
                .filter(([, value]) => value !== undefined)
                .map(([key, value]) => [key, Array.isArray(value) ? value.join(", ") : String(value)]),
            ),
            body: Buffer.concat(chunks),
          }),
        );
      },
    );
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitHttp(url, attempts = 120) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      // Backend is still starting.
    }
    await sleep(250);
  }
  throw new Error(`timeout waiting for ${url}`);
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
  };
  const server = createServer((request, response) => {
    let pathname = (request.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target)) target = path.join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function pythonConfig() {
  if (process.env.PYTHON) return { cmd: process.env.PYTHON, args: ["-m", "uvicorn"] };
  if (process.platform === "win32") return { cmd: "py", args: ["-3", "-m", "uvicorn"] };
  return { cmd: "python3", args: ["-m", "uvicorn"] };
}

function chromiumPath() {
  const bases = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of bases) {
    if (!base || !existsSync(base)) continue;
    if (base.endsWith(".exe") || base.endsWith("chrome") || base.endsWith("Chromium")) return base;
    let entries;
    try {
      entries = readdirSync(base);
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.startsWith("chromium-") || entry.includes("headless")) continue;
      const candidates = [
        join(base, entry, "chrome-win64", "chrome.exe"),
        join(base, entry, "chrome-linux", "chrome"),
        join(base, entry, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      ];
      const found = candidates.find((candidate) => existsSync(candidate));
      if (found) return found;
    }
  }
  return undefined;
}

async function jsonRequest(base, pathname, method = "GET", body, expected = 200) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expected, `${method} ${pathname}: ${JSON.stringify(payload)}`);
  return payload.data;
}

async function createFrozenCurrentThesis(base, env, { disprovenScenario = false } = {}) {
  const campaign = await jsonRequest(base, "/api/campaigns", "POST", {
    security_code: "600519",
    strategy: "SWING",
  }, 201);
  // 有来源、可核对的支持 / 反对依据（进入最初冻结快照）。
  const evSupport = await jsonRequest(base, "/api/evidence", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "news",
    claim: "终端动销保持稳定",
    source_title: "渠道调研周报",
    source_url: "https://example.com/channel-report",
    source_date: "2026-08-01",
    accessed_at: "2026-08-01T00:00:00.000Z",
    classification: "fact",
    confidence: "high",
  });
  const evOppose = await jsonRequest(base, "/api/evidence", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "news",
    claim: "竞品正在放量",
    source_title: "竞品跟踪简报",
    source_url: "https://example.com/competitor-note",
    source_date: "2026-08-02",
    accessed_at: "2026-08-02T00:00:00.000Z",
    classification: "inference",
    confidence: "medium",
  });
  // 与 evOppose 同一事实陈述但立场/来源不同 → 研究连续性产出 SOURCE_CONFLICT，
  // 用于验证冲突双方原文、立场与来源时间在摘要中可核对。
  const evConflict = await jsonRequest(base, "/api/evidence", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "news",
    claim: "竞品正在放量",
    source_title: "卖方晨会纪要",
    source_url: "https://example.com/morning-note",
    source_date: "2026-08-05",
    accessed_at: "2026-08-06T00:00:00.000Z",
    classification: "fact",
    confidence: "medium",
  });
  // 冻结后确认 delta 只能引用冻结前已关联的证据（backend 校验 link 必须存在）。
  const evDeltaOppose = await jsonRequest(base, "/api/evidence", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "news",
    claim: "7 月渠道复核显示动销略低于预期",
    source_title: "渠道复核纪要",
    source_url: "https://example.com/channel-recheck",
    source_date: "2026-08-25",
    accessed_at: "2026-08-25T00:00:00.000Z",
    classification: "fact",
    confidence: "medium",
  });
  const created = await jsonRequest(base, "/api/thesis", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    title: "DC1 Chromium Formal Thesis",
    summary: "isolated current thesis",
    core_claims: ["claim one", "claim two", "claim three"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    change_summary: "DC1 browser fixture",
  }, 200);
  const thesisId = created.thesis.id;
  const currentRevision = async () => (await jsonRequest(base, `/api/thesis/${thesisId}`)).thesis.current_revision;
  await jsonRequest(base, `/api/thesis/${thesisId}/evidence`, "POST", {
    evidence_id: evSupport.id,
    stance: "support",
    expected_revision: await currentRevision(),
  });
  await jsonRequest(base, `/api/thesis/${thesisId}/evidence`, "POST", {
    evidence_id: evOppose.id,
    stance: "oppose",
    expected_revision: await currentRevision(),
  });
  await jsonRequest(base, `/api/thesis/${thesisId}/evidence`, "POST", {
    evidence_id: evConflict.id,
    stance: "support",
    expected_revision: await currentRevision(),
  });
  await jsonRequest(base, `/api/thesis/${thesisId}/evidence`, "POST", {
    evidence_id: evDeltaOppose.id,
    stance: "oppose",
    expected_revision: await currentRevision(),
  });
  const begun = await jsonRequest(base, `/api/thesis/${thesisId}/begin-formalization`, "POST", {}, 200);
  const updated = await jsonRequest(base, `/api/thesis/${thesisId}`, "PUT", {
    title: begun.thesis.title,
    summary: begun.thesis.summary,
    status: "active",
    core_claims: begun.thesis.core_claims,
    catalysts: [],
    risks: [],
    invalidation_conditions: ["业绩发生重大反转"],
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
    free_notes: null,
    expected_revision: begun.thesis.current_revision,
    change_summary: "DC1 browser formal content",
  }, 200);
  const confirmed = await jsonRequest(base, `/api/thesis/${thesisId}/confirm`, "POST", {
    expected_revision: updated.thesis.current_revision,
  }, 200);
  const frozen = await jsonRequest(base, `/api/thesis/${thesisId}/freeze`, "POST", {
    expected_revision: confirmed.thesis.current_revision,
  }, 200);
  assert.equal(frozen.thesis.formal_state, "frozen");
  await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/thesis-binding`, "POST", {
    thesis_id: thesisId,
  }, 201);
  for (const [from, to] of [["DRAFT", "RESEARCHING"], ["RESEARCHING", "PRE-ENTRY"]]) {
    await jsonRequest(base, `/api/campaigns/${campaign.campaign_id}/transitions`, "POST", {
      expected_status: from,
      to_status: to,
    }, 200);
  }
  // 一条不终止研究的已确认变更（WEAKENED）；disproven 场景改用终态 DISPROVEN，
  // 只用于研究摘要截图与终态展示验证，不进入 Commit 流程。
  const deltaCreated = await jsonRequest(base, `/api/thesis/${thesisId}/deltas`, "POST", {
    delta_state: disprovenScenario ? "DISPROVEN" : "WEAKENED",
    reason: disprovenScenario
      ? "渠道复核数据证伪核心假设"
      : "渠道复核显示动销略低于预期，核心假设被削弱但未推翻",
    evidence_ids: [evDeltaOppose.id],
  });
  assert.equal(deltaCreated.delta_state, disprovenScenario ? "DISPROVEN" : "WEAKENED");
  seedActiveCampaign(backendDir, env, campaign.campaign_id);
  return { campaign, thesisId };
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before Chromium E2E");
  const disprovenScenario = process.env.BRIEF_SCENARIO === "disproven";
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-dc1-decision-commit-e2e-"));
  let backendProc;
  let backendLog = "";
  let staticServer;
  let browser;
  try {
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const backend = `http://127.0.0.1:${backendPort}`;
    const frontend = `http://127.0.0.1:${frontendPort}`;
    const py = pythonConfig();
    const env = {
      ...process.env,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      PYTHONUNBUFFERED: "1",
      // P1-SB1 Origin gate：page.route 转发保留 frontend Origin，
      // 与 decision-challenge.browser.mjs 相同，显式加入白名单。
      VR_ALLOW_ORIGINS: frontend,
      PYTHONPATH: [__dirname, backendDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    };
    backendProc = spawn(py.cmd, [...py.args, "decision_challenge_backend_harness:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backendProc.stdout.on("data", (chunk) => { backendLog += chunk.toString(); });
    backendProc.stderr.on("data", (chunk) => { backendLog += chunk.toString(); });
    await waitHttp(`${backend}/api/health`);
    await jsonRequest(backend, "/api/position/bootstrap-commit", "POST", {
      ledger_start_at: "2026-08-01",
      opening_cash: 100000,
      positions: [{ code: "600519", name: "贵州茅台", shares: 100, cost_basis: 150000 }],
    }, 200);
    const { campaign, thesisId } = await createFrozenCurrentThesis(backend, env, { disprovenScenario });
    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    try {
      browser = await chromium.launch(launchOptions);
    } catch {
      browser = await chromium.launch({ headless: true, channel: "chrome" });
    }
    const page = await browser.newPage();
    const consoleErrors = [];
    const failedRequests = [];
    const notFoundResponses = [];
    let authorityFailure = false;
    let committedDecisionId = null;
    const readbackVariant = process.env.DCR1_READBACK_VARIANT || "valid";
    assert.ok(
      ["valid", "malformed", "decision-mismatch", "campaign-mismatch"].includes(readbackVariant),
      `unsupported DCR1_READBACK_VARIANT: ${readbackVariant}`,
    );
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("requestfailed", (request) => failedRequests.push({ url: request.url(), error: request.failure()?.errorText }));
    page.on("response", (response) => {
      if (response.status() === 404) notFoundResponses.push(new URL(response.url()).pathname);
    });
    // 研究摘要零业务写入监控：打开 / 展开摘要不得产生任何非只读 API 请求。
    const apiWriteRequests = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/") && !["GET", "HEAD", "OPTIONS"].includes(request.method())) {
        apiWriteRequests.push(`${request.method()} ${url.pathname}`);
      }
    });
    // 与 decision-challenge.browser.mjs 相同方向的 node 侧代理：
    // route.continue({url}) 在当前 Chromium/Playwright 组合下会挂起；
    // undici fetch 连接池会复用已被 uvicorn keep-alive 超时关闭的连接
    // （表单交互跨越 5s 窗口后必现 ECONNRESET），因此用 node:http 每次
    // 新建连接并强制 Connection: close。
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      const contextPath = `/api/campaigns/${campaign.campaign_id}`;
      const committedPathPrefix = `${contextPath}/decision-proposal/committed/`;
      if (method === "GET" && url.pathname.startsWith(committedPathPrefix)) {
        committedDecisionId = url.pathname.slice(committedPathPrefix.length);
      }
      if (process.env.DF2_FORCE_CONTEXT_FALLBACK === "1" && method === "GET" && url.pathname === `${contextPath}/current-thesis`) {
        authorityFailure = true;
        const fallbackBody = { data: { campaign_id: campaign.campaign_id, thesis_id: "0123456789abcdef0123456789abcdef", binding: { thesis_revision_at_bind: 2, campaign_strategy_at_bind: "SWING", bound_at: "2026-08-22T00:00:00.000Z" }, formal_state: "confirmed", frozen_revision: null, ready: false, formal_status: "NOT_READY", reason: "NOT_FROZEN" } };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fallbackBody) });
        return;
      }
      try {
        const response = await proxyRequest(
          `${backend}${url.pathname}${url.search}`,
          method,
          request.headers(),
          method === "GET" || method === "HEAD" ? undefined : request.postDataBuffer(),
        );
        let responseBody = response.body;
        if (
          method === "GET"
          && url.pathname.startsWith(committedPathPrefix)
          && readbackVariant !== "valid"
          && response.status === 200
        ) {
          const payload = JSON.parse(response.body.toString("utf8"));
          if (readbackVariant === "malformed") {
            delete payload.data.formal_decision;
          } else if (readbackVariant === "decision-mismatch") {
            payload.data.committed.decision_id = `decision_${"e".repeat(32)}`;
          } else if (readbackVariant === "campaign-mismatch") {
            payload.data.committed.campaign_id = `campaign_${"f".repeat(32)}`;
          }
          responseBody = Buffer.from(JSON.stringify(payload));
        }
        const responseHeaders = { ...response.headers };
        if (responseBody !== response.body) {
          delete responseHeaders["content-length"];
          delete responseHeaders["Content-Length"];
        }
        await route.fulfill({
          status: response.status,
          headers: responseHeaders,
          body: responseBody,
        });
      } catch (error) {
        console.error(`[proxy] ${method} ${url.pathname} failed:`, error instanceof Error ? `${error.message} ${error.code ?? ""}` : error);
        await route.fulfill({
          status: 599,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "E2E backend proxy failed",
            error: error instanceof Error ? error.message : String(error),
          }),
        });
      }
    });
    await page.goto(`${frontend}/campaigns/${campaign.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Formal Decision Review" }).waitFor();
    if (process.env.DF2_FORCE_CONTEXT_FALLBACK === "1") {
      await page.locator('[data-horizon-source="MANUAL_FALLBACK"]').waitFor({ timeout: 30000 });
      assert.equal(authorityFailure, true, "fallback mode must intercept an authority request");
      assert.equal(await page.getByLabel("Strategy horizon").inputValue(), "", "fallback must not guess horizon");
      await page.getByLabel("Strategy horizon").fill("10 至 30 交易日");
    } else {
      await page.locator('[data-horizon-source="CURRENT_THESIS"]').waitFor({ timeout: 30000 });
      assert.equal(await page.getByLabel("Strategy horizon").inputValue(), "10–30 个交易日");
    }
    const brief = page.getByTestId("research-brief");
    await brief.waitFor();
    assert.equal(await brief.locator("input, textarea, select").count(), 0, "research brief must stay read-only");
    const subjectText = await page.getByTestId("research-brief-subject").innerText();
    assert.match(subjectText, /600519/);
    assert.match(subjectText, /波段|SWING/);
    const viewText = await page.getByTestId("research-brief-view").innerText();
    if (process.env.DF2_FORCE_CONTEXT_FALLBACK === "1") {
      assert.match(viewText, /未确认草稿|不可用/);
    } else {
      assert.match(viewText, /claim one/);
      assert.match(viewText, /最初冻结/, "original frozen view must be explicitly labeled as historical");
      assert.match(await page.getByTestId("research-brief-invalidation").innerText(), /不是这些条件已经触发/);
    }
    const evidenceText = await page.getByTestId("research-brief-evidence").innerText();
    const changesText = await page.getByTestId("research-brief-changes").innerText();
    if (process.env.DF2_FORCE_CONTEXT_FALLBACK === "1") {
      assert.match(evidenceText, /不展示未确认草稿/);
      assert.match(changesText, /来源冲突/);
    } else {
      // 有来源的支持 / 反对依据必须真实展示。
      assert.match(evidenceText, /终端动销保持稳定/);
      assert.match(evidenceText, /渠道调研周报/);
      assert.match(evidenceText, /竞品正在放量/);
      assert.equal(
        await evidenceText.includes("没有反对记录"),
        false,
        "fixture links opposing evidence, so the no-opposing disclaimer must not show",
      );
      assert.match(changesText, /基线 Candidate Research Formal Original/);
      assert.match(changesText, /读取时间 \d{4}-\d{2}-\d{2}T/);
      // 来源冲突：默认摘要含双方来源与立场；展开后原文、分类、置信度、来源时间可核对。
      assert.match(changesText, /来源冲突/);
      assert.match(changesText, /竞品跟踪简报：立场 反对/);
      assert.match(changesText, /卖方晨会纪要：立场 支持/);
      const conflictDetails = page.getByTestId("research-brief-conflict-records").first();
      await conflictDetails.locator("summary").click();
      const conflictText = await conflictDetails.innerText();
      assert.match(conflictText, /\[反对\] ?竞品正在放量/);
      assert.match(conflictText, /\[支持\] ?竞品正在放量/);
      assert.match(conflictText, /竞品跟踪简报/);
      assert.match(conflictText, /卖方晨会纪要/);
      assert.match(conflictText, /来源日期 2026-08-02/);
      assert.match(conflictText, /来源日期 2026-08-05/);
      assert.match(conflictText, /记录时间 2026-08-06T00:00:00/);
      assert.equal(
        await conflictText.includes("正确"),
        false,
        "conflict rendering must not declare a winner",
      );
    }
    await page.getByTestId("research-brief-freshness").waitFor();
    if (!process.env.DF2_FORCE_CONTEXT_FALLBACK) {
      // 当前确认状态与已确认变更来自 backend 投影，不只是最初冻结原文。
      const effectiveStateText = (await page.locator("[data-context-effective-state]").innerText()).trim();
      const updateItems = page.getByTestId("research-brief-update-item");
      await updateItems.first().waitFor();
      const updateText = await updateItems.first().innerText();
      if (disprovenScenario) {
        assert.equal(effectiveStateText, "已证伪");
        await page.getByTestId("research-brief-terminal-state").waitFor();
        assert.match(await page.getByTestId("research-brief-terminal-state").innerText(), /已证伪/);
        assert.match(updateText, /已证伪/);
      } else {
        assert.equal(effectiveStateText, "削弱");
        assert.equal(await page.getByTestId("research-brief-terminal-state").count(), 0, "WEAKENED is not terminal");
        assert.match(updateText, /削弱/);
      }
      assert.match(updateText, /确认时间：/);
      assert.match(updateText, /渠道复核/);
      // 展开已确认依据：反对依据带来源，且展开动作不产生任何业务写请求。
      await updateItems.first().locator("summary").click();
      await page.getByTestId("research-brief-evidence-oppose").filter({ hasText: "7 月渠道复核显示动销略低于预期" }).first().waitFor();
      assert.equal(apiWriteRequests.length, 0, `opening/expanding the brief must make no business writes, saw ${JSON.stringify(apiWriteRequests)}`);
    }
    const shotDir = join(root, ".pi", "generated-images");
    mkdirSync(shotDir, { recursive: true });
    const shotName = process.env.DF2_FORCE_CONTEXT_FALLBACK === "1"
      ? "research-brief-fallback.png"
      : disprovenScenario
        ? "research-brief-disproven-after.png"
        : "research-brief-after.png";
    await brief.screenshot({ path: join(shotDir, shotName) });
    if (disprovenScenario) {
      // 已证伪案例不进入 Preview / Commit：终态研究不要求成功提交正式决定。
      console.log("[E2E] research-brief disproven scenario captured");
      return;
    }
    // P1-DF3：结构化 review boundary——用户显式选择本地时间，页面展示
    // 解析时区与最终 canonical ISO；断言 canonical 确实等于所选时刻。
    await page.getByLabel("Review by").fill("2026-08-30T10:00");
    const expectedCanonicalIso = await page.evaluate(() => new Date("2026-08-30T10:00").toISOString());
    const displayedCanonical = (await page.locator("[data-review-by-canonical]").innerText()).trim();
    assert.equal(displayedCanonical, expectedCanonicalIso, "displayed canonical ISO must equal the user-selected local time");
    assert.match(displayedCanonical, /Z$/);
    const tzText = await page.locator("[data-review-by-tz]").innerText();
    assert.match(tzText, /解析时区/);
    await page.getByLabel("Key assumptions").fill("流动性保持稳定");
    await page.getByLabel("Event invalidation conditions").fill("业绩发生重大反转");
    // P1-DF1：三视图结构化表单——普通用户零 JSON 完成输入
    await page.getByLabel("Asset stance").selectOption("SUPPORT");
    await page.getByLabel("Asset note").fill("高端白酒需求稳定");
    await page.getByLabel("Trade stance").selectOption("WAIT");
    await page.getByLabel("Trade note").fill("等待缩量回调再入场");
    await page.getByLabel("Portfolio constraint").fill("单笔风险不超过组合 2%");
    const previewResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(
        `/api/campaigns/${campaign.campaign_id}/decision-proposal/preview`,
      )
    ), { timeout: 180000 });
    await page.getByRole("button", { name: "Preview Proposal" }).click();
    const previewResponse = await previewResponsePromise;
    assert.equal(previewResponse.ok(), true, `Preview failed: ${await previewResponse.text()}`);
    await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
    for (const viewName of ["asset_view", "trade_view", "portfolio_view"]) {
      await page.locator(`[data-view-form="${viewName}"]`).waitFor();
    }
    const criticalDataCard = page.locator("[data-critical-data-state]").first();
    await criticalDataCard.waitFor();
    const previewCriticalData = {
      state: await criticalDataCard.getAttribute("data-critical-data-state"),
      evaluation: await criticalDataCard.getAttribute("data-critical-data-evaluation"),
    };
    assert.ok(previewCriticalData.state, "Preview must expose Critical Data state");
    assert.ok(previewCriticalData.evaluation, "Preview must expose Critical Data evaluation");
    assert.notEqual(previewCriticalData.evaluation, "HEALTHY", "Critical Data must use authority evaluation vocabulary");
    assert.equal(existsSync(join(tempDataDir, "frozen_decisions.sqlite3")), false, "Preview must not create Frozen DB");
    const freeze = page.getByRole("button", { name: "Freeze Formal Decision" });
    assert.equal(await freeze.isEnabled(), false, "Freeze must be closed before checkbox");
    await page.getByRole("checkbox", { name: /我已检查三个独立 View/ }).check();
    assert.equal(await freeze.isEnabled(), true);
    await freeze.click();
    await page.waitForFunction(() => document.querySelector('[data-formal-decision-evaluation]') !== null || document.querySelector('[role="alert"]') !== null, null, { timeout: 180000 });
    assert.ok(committedDecisionId, "durable committed GET must be observed");
    assert.match(committedDecisionId, /^decision_[0-9a-f]{32}$/);
    const committedSuccess = page.locator('[data-formal-decision-evaluation="EVALUATED"]');
    if (readbackVariant === "valid") {
      await committedSuccess.waitFor({ timeout: 30000 });
      const committedLine = await page.locator("[data-formal-decision-evaluation] p.font-mono").innerText();
      const committedId = committedLine.replace(/^decision_id：/, "").trim();
      assert.equal(committedId, committedDecisionId);
    } else {
      assert.equal(await committedSuccess.count(), 0, `${readbackVariant} must not render committed success UI`);
      const readbackError = await page.locator('[role="alert"]').innerText();
      assert.match(readbackError, /COMMITTED_DECISION_READ_ERROR/);
    }
    const reread = await jsonRequest(backend, `/api/campaigns/${campaign.campaign_id}/decision-proposal/committed/${committedDecisionId}`);
    assert.equal(reread.formal_decision.evaluation, "EVALUATED");
    assert.equal(reread.committed.decision_id, committedDecisionId);
    assert.equal(reread.committed.campaign_id, campaign.campaign_id);
    assert.equal(reread.critical_data.critical_data_state, previewCriticalData.state);
    assert.equal(reread.critical_data.critical_data_evaluation, previewCriticalData.evaluation);
    assert.equal(reread.critical_data.campaign_id, campaign.campaign_id);
    assert.equal(reread.critical_data.security_code, "600519");
    assert.equal(reread.critical_data.strategy, "SWING");
    const inbox = await jsonRequest(backend, "/api/decision-inbox");
    const item = inbox.campaign_items.find((entry) => entry.campaign_id === campaign.campaign_id);
    assert.ok(item, "Decision Inbox must contain the active Campaign");
    assert.equal(item.last_frozen_decision.decision_id, committedDecisionId);
    assert.equal(item.formal_decision_evaluation, "EVALUATED");
    assert.equal(item.critical_data.critical_data_state, reread.critical_data.critical_data_state);
    assert.equal(item.critical_data.critical_data_evaluation, reread.critical_data.critical_data_evaluation);
    assert.equal(item.critical_data.campaign_id, reread.critical_data.campaign_id);
    assert.equal(item.critical_data.security_code, reread.critical_data.security_code);
    assert.equal(item.critical_data.strategy, reread.critical_data.strategy);
    await page.goto(`${frontend}/decision-inbox`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "决策待办" }).waitFor();
    const actionPanel = page.locator(`[data-decision-action-panel="${campaign.campaign_id}"]`);
    await actionPanel.waitFor();
    assert.equal(
      await actionPanel.locator("[data-frozen-decision-state]").getAttribute("data-frozen-decision-state"),
      "APPLICABLE",
      "backend EVALUATED must expose the Frozen Decision as applicable",
    );
    assert.equal(
      await actionPanel.locator("[data-frozen-decision-action]").getAttribute("data-frozen-decision-action"),
      item.last_frozen_decision.previous_next_best_action,
    );
    await actionPanel.getByText(committedDecisionId, { exact: true }).waitFor();
    await actionPanel.getByText("当前 Sell Review（只读）", { exact: true }).waitFor();
    assert.ok(item.sell_engine, "Decision Inbox backend must contain the Sell Engine projection");
    assert.equal(
      await actionPanel.locator("[data-sell-engine-evaluation]").getAttribute("data-sell-engine-evaluation"),
      item.sell_engine.sell_evaluation,
      "Sell Review must preserve the backend evaluation state",
    );
    assert.notEqual(
      await actionPanel.locator("[data-sell-engine-state]").getAttribute("data-sell-engine-state"),
      "UNAVAILABLE",
      "the exact backend Sell Engine contract must be productized, not silently discarded",
    );
    assert.equal(
      (await actionPanel.innerText()).includes("CURRENT_RECOMMENDATION"),
      false,
      "Frozen Decision must never be presented as CURRENT_RECOMMENDATION",
    );
    assert.equal(
      await actionPanel.getByRole("link", { name: "重新形成 Formal Decision →" }).getAttribute("href"),
      `/campaigns/${campaign.campaign_id}/decision-proposal`,
    );
    assert.equal(
      await actionPanel.getByRole("link", { name: "打开决策复盘 →" }).getAttribute("href"),
      "/decision-performance",
    );

    // ── 冻结后研究更新（R2/R3/R4）：冻结原文不变，新证据经 UI 显式确认进入 delta，
    //    连续性识别为 ADDED，旧决定的 baseline 截断保持其当时依据。 ──
    const apiWriteMarker = apiWriteRequests.length;
    // 1) 通过正常界面创建此前不存在的新证据（evidence 创建 ≠ 研究变化已确认）。
    await page.goto(`${frontend}/evidence/new?subject_type=stock&subject_id=600519&return_to=${encodeURIComponent(`/thesis/${thesisId}`)}`, { waitUntil: "domcontentloaded" });
    await page.locator("select").first().waitFor();
    await page.locator("select").nth(1).selectOption("news");
    await page.fill('input[placeholder*="600519"]', "600519");
    await page.fill('textarea[placeholder*="一句话"]', "冻结后渠道复核显示动销连续两周走弱");
    await page.fill('input[placeholder*="XX公司"]', "渠道复核周记");
    await page.fill('input[placeholder*="https://"]', "https://example.com/post-freeze-recheck");
    await page.fill('input[type="date"]', "2026-08-28");
    await page.locator("label:has-text('分类') select").selectOption("fact");
    await page.locator("label:has-text('置信度') select").selectOption("medium");
    await page.fill('input[type="datetime-local"]', "2026-08-28T18:00");
    await page.locator('button:has-text("保存")').click();
    await page.waitForURL(new RegExp(`/thesis/${thesisId}$`));
    // 2) 在冻结研究页完成 显式立场/状态/原因 → 预览 → 勾选 → 确认。
    const deltaPanel = page.getByTestId("thesis-delta-confirm");
    await deltaPanel.waitFor();
    const newOption = page.locator("select[aria-label='选择证据'] option", { hasText: "冻结后渠道复核显示动销连续两周走弱" }).last();
    const newOptionValue = await newOption.getAttribute("value");
    assert.ok(newOptionValue, "newly created evidence must appear in the selection list");
    await page.getByLabel("选择证据").selectOption(newOptionValue);
    await page.getByTestId("delta-evidence-summary").waitFor();
    await page.getByLabel("本次变更立场").selectOption("oppose");
    await page.getByLabel("研究变化状态").selectOption("WEAKENED");
    await page.getByLabel("变更原因").fill("冻结后渠道复核走弱，核心假设被削弱但未推翻");
    await page.getByTestId("delta-preview").waitFor();
    await page.getByLabel("我已核对证据内容与本次立场，确认追加这条研究变化").check();
    await page.getByTestId("confirm-thesis-delta").click();
    const readbackPanel = page.getByTestId("delta-readback");
    // fixture 里已有 1 条旧 delta；UI 确认成功后服务端读回必须出现第 2 条。
    await readbackPanel.getByText("#2 · WEAKENED").waitFor({ timeout: 30000 });
    assert.match(await readbackPanel.innerText(), /\[反对\] 冻结后渠道复核显示动销连续两周走弱/);
    // 本段的业务写入必须恰好是：一次证据创建 + 一次 delta 确认，无其他隐式写入。
    assert.deepEqual(
      apiWriteRequests.slice(apiWriteMarker),
      ["POST /api/evidence", `POST /api/thesis/${thesisId}/deltas`],
      "the only business writes must be evidence creation and the explicit delta confirmation",
    );
    // 3) 决策复核页：摘要接住新 delta（当前状态削弱），连续性识别 ADDED，冻结原文未改写。
    await page.goto(`${frontend}/campaigns/${campaign.campaign_id}/decision-proposal`, { waitUntil: "domcontentloaded" });
    await page.locator('[data-horizon-source="CURRENT_THESIS"]').waitFor({ timeout: 30000 });
    assert.equal((await page.locator("[data-context-effective-state]").innerText()).trim(), "削弱");
    const briefAfterUpdate = await page.getByTestId("research-brief").innerText();
    assert.match(briefAfterUpdate, /claim one/, "original frozen view must stay intact");
    assert.match(briefAfterUpdate, /冻结后渠道复核显示动销连续两周走弱/, "confirmed update evidence must surface in the brief");
    assert.match(briefAfterUpdate, /新增证据/, "continuity must classify the post-freeze evidence as ADDED");
    await page.getByTestId("research-brief").screenshot({ path: join(shotDir, "post-freeze-delta-brief.png") });
    const expectedFontBlock = "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap";
    const expectedChallenge404 = `/api/campaigns/${campaign.campaign_id}/decision-challenge`;
    assert.deepEqual(notFoundResponses, [expectedChallenge404], "only the optional challenge lookup may be 404");
    const unexpectedConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("ERR_NETWORK_ACCESS_DENIED")
        && !message.includes("Failed to load resource: the server responded with a status of 404 (Not Found)"),
    );
    const unexpectedFailedRequests = failedRequests.filter((request) =>
  request.url !== expectedFontBlock && !request.url.includes("fonts.gstatic.com"),
);
    assert.equal(unexpectedConsoleErrors.length, 0, `unexpected browser console errors: ${JSON.stringify(unexpectedConsoleErrors)}`);
    assert.equal(unexpectedFailedRequests.length, 0, `unexpected failed requests: ${JSON.stringify(unexpectedFailedRequests)}`);
    if (failedRequests.length > 0) console.log(`[E2E] environment-only blocked asset: ${expectedFontBlock}`);
    console.log("[E2E] P0-DC1 Decision Commit vertical passed");
  } catch (error) {
    if (backendProc && !backendProc.killed) console.error(backendLog || "backend log unavailable");
    throw error;
  } finally {
    if (browser) await browser.close();
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backendProc && !backendProc.killed) {
      if (process.platform === "win32") {
        spawnSync("taskkill", ["/PID", String(backendProc.pid), "/T", "/F"], {
          stdio: "ignore",
          windowsHide: true,
        });
      } else {
        backendProc.kill();
      }
      await new Promise((resolve) => backendProc.once("close", resolve));
    }
    rmSync(tempDataDir, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
