/**
 * P0-DCH1 pre-freeze Decision Challenge vertical — isolated FastAPI + Chromium.
 *
 * Preview → optional Challenge finalize → backend readback → Freeze binding.
 * The no-challenge path must still freeze and must not invent a challenge ref.
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
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
    for (const entry of readdirSync(base)) {
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

async function createFrozenCurrentThesis(base, env, title) {
  const campaign = await jsonRequest(base, "/api/campaigns", "POST", {
    security_code: "600519",
    strategy: "SWING",
  }, 201);
  const created = await jsonRequest(base, "/api/thesis", "POST", {
    subject_type: "stock",
    subject_id: "600519",
    title,
    summary: "isolated current thesis",
    core_claims: ["claim one", "claim two", "claim three"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    change_summary: "DCH1 browser fixture",
  }, 200);
  const thesisId = created.thesis.id;
  const begun = await jsonRequest(base, `/api/thesis/${thesisId}/begin-formalization`, "POST", {}, 200);
  const updated = await jsonRequest(base, `/api/thesis/${thesisId}`, "PUT", {
    title: begun.thesis.title,
    summary: begun.thesis.summary,
    status: "active",
    core_claims: begun.thesis.core_claims,
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
    free_notes: null,
    expected_revision: begun.thesis.current_revision,
    change_summary: "DCH1 browser formal content",
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
  seedActiveCampaign(backendDir, env, campaign.campaign_id);
  return campaign;
}

const draft = {
  reviewBy: "2026-08-30T10:00",
  horizon: "10 至 30 交易日",
  assumptions: "流动性保持稳定",
  invalidations: "业绩发生重大反转",
};

async function fillProposalDraft(page) {
  await page.getByLabel("下次必须重新检查的时间").fill(draft.reviewBy);
  await page.getByLabel("这次判断关注的时间范围").fill(draft.horizon);
  await page.getByLabel("这个判断成立依赖什么").fill(draft.assumptions);
  await page.getByLabel("出现什么情况说明判断错了").fill(draft.invalidations);
  await page.waitForFunction((expected) => {
    const review = document.querySelector('[aria-label="下次必须重新检查的时间"]');
    const horizon = document.querySelector('[aria-label="这次判断关注的时间范围"]');
    return Boolean(
      review && review.value === expected.reviewBy
      && horizon && horizon.value === expected.horizon
    );
  }, draft);
}

async function run() {
  assert.ok(existsSync(frontendDist), "frontend/dist must be built before Chromium E2E");
  const tempDataDir = mkdtempSync(join(tmpdir(), "vr-dch1-decision-challenge-e2e-"));
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
      VR_ALLOW_ORIGINS: frontend,
      VR_DATA_DIR: tempDataDir,
      VR_REPORTS_DIR: tempDataDir,
      VIBE_RESEARCH_TRADE_LEDGER_DB: join(tempDataDir, "trade_ledger.sqlite3"),
      VIBE_RESEARCH_REVIEW_DB: join(tempDataDir, "review_history.db"),
      VIBE_RESEARCH_EVIDENCE_THESIS_DB: join(tempDataDir, "evidence_thesis.db"),
      VIBE_RESEARCH_CAMPAIGN_DB: join(tempDataDir, "campaigns.sqlite3"),
      VIBE_RESEARCH_FROZEN_DECISION_DB: join(tempDataDir, "frozen_decisions.sqlite3"),
      VIBE_RESEARCH_DECISION_CHALLENGE_DB: join(tempDataDir, "decision_challenges.sqlite3"),
      PYTHONUNBUFFERED: "1",
    };
    backendProc = spawn(py.cmd, [...py.args, "decision_challenge_backend_harness:app", "--host", "127.0.0.1", "--port", String(backendPort)], {
      cwd: backendDir,
      env: {
        ...env,
        PYTHONPATH: [__dirname, backendDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      },
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
    const withChallenge = await createFrozenCurrentThesis(backend, env, "DCH1 with challenge");
    staticServer = await startStaticServer(frontendDist, frontendPort);
    const launchOptions = { headless: true };
    const executablePath = chromiumPath();
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    const failedRequests = [];
    const apiTrace = [];
    let challengeReadFailureStatus = null;
    let challengeReadFailureCampaignId = null;
    page.on("console", (message) => {
      if (message.type() === "error") backendLog += `\n[browser] ${message.text()}`;
    });
    page.on("requestfailed", (request) => {
      failedRequests.push({ url: request.url(), error: request.failure()?.errorText });
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      apiTrace.push(`${method} ${url.pathname}${url.search}`);
      try {
        if (
          challengeReadFailureStatus !== null
          && method === "GET"
          && url.pathname === `/api/campaigns/${challengeReadFailureCampaignId}/decision-challenge`
        ) {
          await route.fulfill({
            status: challengeReadFailureStatus,
            contentType: "application/json",
            body: JSON.stringify({ detail: "simulated Challenge read failure" }),
          });
          return;
        }
        const response = await fetch(`${backend}${url.pathname}${url.search}`, {
          method,
          headers: request.headers(),
          body: method === "GET" || method === "HEAD" ? undefined : request.postDataBuffer(),
        });
        await route.fulfill({
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          body: Buffer.from(await response.arrayBuffer()),
        });
      } catch (error) {
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

    await page.goto(`${frontend}/campaigns/${withChallenge.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "正式决策" }).waitFor();
    await page.locator(`[data-decision-proposal-page="${withChallenge.campaign_id}"]`).waitFor();
    await fillProposalDraft(page);
    const previewResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(
        `/api/campaigns/${withChallenge.campaign_id}/decision-proposal/preview`
      )
    ), { timeout: 180000 });
    await page.getByRole("button", { name: "预览决策草案" }).click();
    const previewResponse = await previewResponsePromise;
    const previewBody = await previewResponse.text();
    if (!previewResponse.ok()) {
      throw new Error(
        `[DCH1] preview failed: status=${previewResponse.status()} body=${previewBody}; `
        + `failedRequests=${JSON.stringify(failedRequests)}`
      );
    }
    await page.locator('[data-proposal-status="UNCOMMITTED"]').waitFor();
    await page.locator('[data-challenge-state="ABSENT"]').waitFor();
    assert.equal(existsSync(join(tempDataDir, "decision_challenges.sqlite3")), false, "Preview must not write Challenge DB");
    assert.equal(existsSync(join(tempDataDir, "frozen_decisions.sqlite3")), false, "Preview must not write Frozen DB");

    await page.getByRole("textbox", { name: "最有力的支持证据" }).fill("渠道与报表支持当前等待");
    await page.getByRole("textbox", { name: "最有力的反对证据" }).fill("估值不便宜");
    await page.getByLabel("如果判断失败，最可能的原因 status", { exact: true }).selectOption("UNKNOWN");
    await page.getByRole("textbox", { name: "如果判断失败，最可能的原因" }).fill("还没有足够的失效路径样本");
    await page.getByRole("textbox", { name: "哪些事实会推翻判断" }).fill("连续两个季度毛利率下修则失效");
    const finalize = page.getByRole("button", { name: "完成决策挑战" });
    assert.equal(await finalize.isEnabled(), false, "Finalize must require explicit confirmation");
    await page.getByRole("checkbox", { name: /我已明确填写四个挑战问题/ }).check();
    assert.equal(await finalize.isEnabled(), true);
    const finalizeResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(
        `/api/campaigns/${withChallenge.campaign_id}/decision-challenge/finalize`
      )
    ));
    await finalize.click();
    const finalizeResponse = await finalizeResponsePromise;
    const finalizeBody = await finalizeResponse.text();
    if (!finalizeResponse.ok()) {
      throw new Error(
        `[DCH1] finalize failed: status=${finalizeResponse.status()} body=${finalizeBody}`
      );
    }
    await page.locator('[data-challenge-state="FOUND"]').waitFor();
    const challengeId = await page.locator("[data-challenge-id]").getAttribute("data-challenge-id");
    assert.match(challengeId, /^decision_challenge_[0-9a-f]{32}$/);
    const durable = await jsonRequest(backend, `/api/decision-challenges/${challengeId}`);
    assert.equal(durable.challenge.challenge_id, challengeId);
    assert.equal(durable.challenge.packet_state, "COMPLETE");
    assert.equal(durable.decision_quality, "NOT_EVALUATED");
    assert.equal(durable.challenge.two_pass_semantic_independence_verified, "NO");

    const commitResponsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes(`/api/campaigns/${withChallenge.campaign_id}/decision-proposal/commit`)
    ));
    await page.getByRole("checkbox", { name: /我已检查股票判断、操作倾向、组合限制/ }).check();
    await page.getByRole("button", { name: "确认并冻结正式决策" }).click();
    const commitResponse = await commitResponsePromise;
    const commitBody = await commitResponse.json();
    if (!commitResponse.ok()) {
      throw new Error(`[DCH2] bound Freeze HTTP error: ${commitResponse.status()} ${JSON.stringify(commitBody)}`);
    }
    await page.waitForTimeout(500);
    const commitError = await page.locator('[role="alert"]').allTextContents();
    if (commitError.length > 0) {
      throw new Error(`[DCH2] bound Freeze UI error: ${commitError.join(" | ")}; failedRequests=${JSON.stringify(failedRequests)}`);
    }
    await page.waitForSelector("[data-formal-decision-evaluation]", { timeout: 180000 });
    const actualEvaluation = await page.locator("[data-formal-decision-evaluation]").getAttribute("data-formal-decision-evaluation");
    if (actualEvaluation !== "EVALUATED") {
      throw new Error(`[DCH2] bound Freeze returned evaluation=${actualEvaluation}; alerts=${JSON.stringify(commitError)}; trace=${JSON.stringify(apiTrace)}`);
    }
    const committedLine = await page.locator("[data-formal-decision-evaluation] p.font-mono").innerText();
    const boundId = committedLine.replace(/^decision_id：/, "").trim();
    const bound = await jsonRequest(backend, `/api/campaigns/${withChallenge.campaign_id}/decision-proposal/committed/${boundId}`);
    assert.ok(
      bound.committed.source_refs.includes(`decision_challenge:${challengeId}`),
      `Frozen Decision must carry server challenge ref, got ${JSON.stringify(bound.committed.source_refs)}`,
    );

    const previewAfter = await jsonRequest(backend, `/api/campaigns/${withChallenge.campaign_id}/decision-proposal/preview`, "POST", {
      asset_view: { view: "ASSET", stance: "WAIT", note: "changed after challenge" },
      trade_view: { view: "TRADE", stance: "WAIT" },
      portfolio_view: { view: "PORTFOLIO", constraint: "unknown" },
      review_by: "2026-08-30T10:00:00.000000Z",
      key_assumptions: ["流动性保持稳定"],
      event_invalidation_conditions: ["业绩发生重大反转"],
      strategy_horizon: "10 至 30 交易日",
    });
    const staleCommit = await fetch(`${backend}/api/campaigns/${withChallenge.campaign_id}/decision-proposal/commit`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        asset_view: previewAfter.proposal.asset_view,
        trade_view: previewAfter.proposal.trade_view,
        portfolio_view: previewAfter.proposal.portfolio_view,
        review_by: previewAfter.commit_fields.review_by,
        key_assumptions: previewAfter.commit_fields.key_assumptions,
        event_invalidation_conditions: previewAfter.commit_fields.event_invalidation_conditions,
        strategy_horizon: previewAfter.commit_fields.strategy_horizon,
        as_of: previewAfter.proposal.as_of,
        expected_proposal_fingerprint: previewAfter.proposal_fingerprint,
        user_confirmed: true,
        challenge_id: challengeId,
      }),
    });
    const staleCommitBody = await staleCommit.text();
    assert.equal(
      staleCommit.status,
      409,
      `stale proposal must not silently bind the old challenge: body=${staleCommitBody}`,
    );

    const withoutChallenge = await createFrozenCurrentThesis(backend, env, "DCH1 without challenge");
    await page.goto(`${frontend}/campaigns/${withoutChallenge.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await fillProposalDraft(page);
    await page.getByRole("button", { name: "预览决策草案" }).click();
    await page.locator('[data-challenge-state="ABSENT"]').waitFor();
    await page.getByRole("checkbox", { name: /我已检查股票判断、操作倾向、组合限制/ }).check();
    await page.getByRole("button", { name: "确认并冻结正式决策" }).click();
    await page.locator('[data-formal-decision-evaluation="EVALUATED"]').waitFor({ timeout: 180000 });
    const plainLine = await page.locator("[data-formal-decision-evaluation] p.font-mono").innerText();
    const plainId = plainLine.replace(/^decision_id：/, "").trim();
    const plain = await jsonRequest(backend, `/api/campaigns/${withoutChallenge.campaign_id}/decision-proposal/committed/${plainId}`);
    assert.equal(
      plain.committed.source_refs.some((item) => String(item).startsWith("decision_challenge:")),
      false,
      "no-challenge freeze must not invent a challenge ref",
    );

    const readErrorCampaign = await createFrozenCurrentThesis(backend, env, "DCH2 read error");
    challengeReadFailureCampaignId = readErrorCampaign.campaign_id;
    challengeReadFailureStatus = 500;
    await page.goto(`${frontend}/campaigns/${readErrorCampaign.campaign_id}/decision-proposal`, { waitUntil: "networkidle" });
    await fillProposalDraft(page);
    await page.getByRole("button", { name: "预览决策草案" }).click();
    const challengeErrorSection = page.locator('[data-challenge-state="ERROR"]');
    await challengeErrorSection.waitFor();
    await challengeErrorSection.getByText("决策挑战读取失败", { exact: false }).waitFor();
    assert.equal(await page.getByRole("button", { name: "完成决策挑战" }).isDisabled(), true);
    assert.equal(await page.getByRole("checkbox", { name: /Freeze 将绑定|未找到已 Finalize|Challenge 状态当前无法安全验证/ }).isDisabled(), true);
    await page.getByRole("checkbox", { name: /我已检查股票判断、操作倾向、组合限制/ }).check();
    assert.equal(await page.getByRole("button", { name: "确认并冻结正式决策" }).isDisabled(), true);
    assert.equal(await page.locator("[data-challenge-id]").getAttribute("data-challenge-id"), "");
    assert.equal(existsSync(join(tempDataDir, "frozen_decisions.sqlite3")), true, "prior freezes may exist, but error path adds no linkage");

    console.log("[E2E] P1-DCH2 Decision Challenge truthful read states passed");
  } catch (error) {
    if (backendProc && !backendProc.killed) console.error(backendLog || "backend log unavailable");
    throw error;
  } finally {
    if (browser) await browser.close();
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
    if (backendProc && !backendProc.killed) backendProc.kill();
    rmSync(tempDataDir, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
