/**
 * P0-HR1 Hard Risk render-level fixture scaffold（不依赖 backend / O/C runtime）。
 *
 * 用 built frontend（dist）+ Chromium + Playwright route mock 注入 frozen
 * Decision Inbox payload，验证 Hard Risk 用户可见面：
 * - CONFIRMED 高优先级可见，且文案绝不包含卖出/退出/清仓/EXIT/SELL
 * - CLEAR 只有显式 positive-proof 才显示安全绿色
 * - UNKNOWN / NOT_EVALUATED / ERROR 一律不绿
 * - sibling Campaign（同 security 不同 strategy）状态隔离
 * - reason codes / authority refs 透传可见
 *
 * 真实 FastAPI + 最终 O/C runtime 的集成 E2E 在 integration fan-in 后执行。
 */
import assert from "node:assert/strict";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

const AS_OF = "2026-08-16T00:00:00Z";

function item(overrides) {
  return {
    schema_version: "decision_inbox_runtime.v0.1",
    visible_state: "BLOCKED_BY_DATA",
    reason_codes: [],
    security_code: "600519",
    strategy: "SWING",
    campaign_id: `campaign_${"a".repeat(32)}`,
    campaign_status: "ACTIVE",
    as_of: AS_OF,
    ...overrides,
  };
}

// Hard Risk 只消费专属字段：hard_risk_state / hard_risk_evaluation /
// hard_risk_reason_codes / hard_risk_authority_refs。
// item.reason_codes 是 Campaign-level generic reason list（污染对照物）。

const CONFIRMED_ITEM = item({
  visible_state: "REVIEW_REQUIRED",
  reason_codes: ["HARD_RISK_CONFIRMED", "REVIEW_BY_REACHED"],
  hard_risk_state: "CONFIRMED",
  hard_risk_evaluation: "EVALUATED",
  hard_risk_authority_refs: ["hard-risk:fixture-confirmed"],
  hard_risk_reason_codes: ["HARD_RISK_CONFIRMED", "REVIEW_BY_REACHED"],
  campaign_id: `campaign_${"a".repeat(32)}`,
});

const CLEAR_ITEM = item({
  visible_state: "NO_ACTION_REQUIRED",
  reason_codes: ["CLEAN"],
  hard_risk_state: "CLEAR",
  hard_risk_evaluation: "EVALUATED",
  hard_risk_authority_refs: ["hard-risk:fixture-clear"],
  strategy: "SHORT",
  campaign_id: `campaign_${"b".repeat(32)}`,
});

const NOT_EVALUATED_ITEM = item({
  visible_state: "BLOCKED_BY_DATA",
  reason_codes: ["HARD_RISK_NOT_EVALUATED", "COVERAGE_INCOMPLETE"],
  hard_risk_state: "NOT_EVALUATED",
  hard_risk_evaluation: "NOT_EVALUATED",
  hard_risk_reason_codes: ["HARD_RISK_NOT_EVALUATED", "COVERAGE_INCOMPLETE"],
  formal_decision_evaluation: "NOT_EVALUATED",
  security_code: "000001",
  strategy: "MEDIUM",
  campaign_id: `campaign_${"c".repeat(32)}`,
});

const EVALUATED_ITEM = item({
  visible_state: "REVIEW_REQUIRED",
  reason_codes: ["REVIEW_BY_REACHED"],
  formal_decision_evaluation: "EVALUATED",
  security_code: "300750",
  strategy: "SWING",
  campaign_id: `campaign_${"g".repeat(32)}`,
});

const UNKNOWN_FORMAL_DECISION_ITEM = item({
  formal_decision_evaluation: "UNKNOWN",
  security_code: "601318",
  strategy: "MEDIUM",
  campaign_id: `campaign_${"h".repeat(32)}`,
});

const ERROR_FORMAL_DECISION_ITEM = item({
  formal_decision_evaluation: "ERROR",
  security_code: "601398",
  strategy: "SHORT",
  campaign_id: `campaign_${"i".repeat(32)}`,
});

const MALFORMED_FORMAL_DECISION_ITEM = item({
  formal_decision_evaluation: "FUTURE_ENUM",
  security_code: "601988",
  strategy: "SWING",
  campaign_id: `campaign_${"j".repeat(32)}`,
});

const ERROR_ITEM = item({
  visible_state: "BLOCKED_BY_DATA",
  reason_codes: ["HARD_RISK_UNKNOWN"],
  hard_risk_state: "UNKNOWN",
  hard_risk_evaluation: "ERROR",
  hard_risk_reason_codes: ["HARD_RISK_EVALUATION_ERROR"],
  strategy: "SWING",
  campaign_id: `campaign_${"d".repeat(32)}`,
});

// BLOCKER 回归：CLEAR 但缺少专属 evaluation 与专属 authority refs
// （generic 数据存在）→ 页面绝不出现 safe green。
const MALFORMED_CLEAR_ITEM = item({
  visible_state: "BLOCKED_BY_DATA",
  reason_codes: ["CLEAN"],
  hard_risk_state: "CLEAR",
  strategy: "MEDIUM",
  campaign_id: `campaign_${"e".repeat(32)}`,
});

// 污染 fixture：generic reason 存在（含 HARD_RISK_CONFIRMED），
// Hard Risk 专属 evidence 缺失 → 必须 fail closed，不得声称已确认。
const GENERIC_ONLY_ITEM = item({
  visible_state: "BLOCKED_BY_DATA",
  reason_codes: ["HARD_RISK_CONFIRMED", "CRITICAL_DATA_BLOCKED"],
  hard_risk_state: "CONFIRMED",
  hard_risk_evaluation: "EVALUATED",
  strategy: "SHORT",
  campaign_id: `campaign_${"f".repeat(32)}`,
});

const SNAPSHOT = {
  schema_version: "decision_inbox_runtime.v0.1",
  as_of: AS_OF,
  evaluation_status: "EVALUATED",
  canonical: true,
  reason_codes: [],
  holding_setup_items: [],
  campaign_items: [
    CONFIRMED_ITEM,
    CLEAR_ITEM,
    NOT_EVALUATED_ITEM,
    ERROR_ITEM,
    MALFORMED_CLEAR_ITEM,
    GENERIC_ONLY_ITEM,
    EVALUATED_ITEM,
    UNKNOWN_FORMAL_DECISION_ITEM,
    ERROR_FORMAL_DECISION_ITEM,
    MALFORMED_FORMAL_DECISION_ITEM,
  ],
  total_holdings: 0,
  total_campaign_items: 10,
};

/**
 * 研究事件日历：IA-CONVERGENCE-V1 后它常驻决策待办页面底部并独立加载，
 * fixture 必须给出合法 payload（否则整页会被日历的读取异常带走）。
 */
const RESEARCH_EVENT_CALENDAR = {
  schema_version: "research_event_calendar.v0.1",
  status: "NORMAL",
  as_of: AS_OF,
  fetched_at: AS_OF,
  window: { date_from: "2026-08-01", date_to: "2026-08-31", semantics: "CALENDAR_DAYS" },
  universe: {
    kind: "ACTIVE_RESEARCH_CAMPAIGNS",
    status: "NORMAL",
    campaign_count: 0,
    unique_security_count: 0,
    max_unique_securities: 20,
    securities: [],
  },
  events: [],
  sources: [],
  limitations: [],
  writes: { campaign: 0, thesis: 0, evidence: 0, decision: 0 },
};

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
  };
  const server = createServer((request, response) => {
    let pathname = (request.url || "/").split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    if (!existsSync(target)) target = path.join(dir, "index.html");
    response.setHeader("Content-Type", mime[path.extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

/** 探测已安装的 Playwright chromium（headless shell 可能缺失，回退完整版）。 */
function findChromium() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  for (const base of candidates) {
    if (!base || !existsSync(base)) continue;
    try {
      for (const dir of readdirSync(base)) {
        if (!dir.startsWith("chromium-") || dir.includes("headless")) continue;
        const executable = join(base, dir, "chrome-win64", "chrome.exe");
        if (existsSync(executable)) return executable;
      }
    } catch {
      // Try the next Playwright cache.
    }
  }
  return undefined;
}

async function run() {
  let staticServer;
  let browser;
  try {
    const port = await getFreePort();
    staticServer = await startStaticServer(frontendDist, port);

    browser = await chromium.launch({ executablePath: findChromium(), headless: true });
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    // 纯 fixture 注入：拦截全部 /api 调用，不触达真实 backend。
    await page.route("**/api/decision-inbox", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: SNAPSHOT }),
      }));
    await page.route("**/api/campaigns*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [] }),
      }));
    await page.route("**/api/campaigns/*/next-actions", (route) =>
      route.fulfill({ status: 404, body: "{}" }));
    await page.route("**/api/research-events*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: RESEARCH_EVENT_CALENDAR }),
      }));

    await page.goto(`http://127.0.0.1:${port}/decision-inbox`, { waitUntil: "networkidle" });

    // IA-CONVERGENCE-V1：右侧只挂载「选中投资计划」的详情；Hard Risk 面板与
    // Frozen Decision 入口都属于选中对象。因此每段断言前先在工作列表里选中该 campaign
    // （10 个 fixture campaign 都落在「当前投资计划」分组）。
    await page.getByRole("heading", { name: "当前投资计划" }).waitFor();
    const selectCampaign = async (campaignId) => {
      const row = page.getByTestId(`decision-inbox-item-${campaignId}`);
      await row.waitFor({ state: "visible", timeout: 15000 });
      await row.click();
      await page.waitForFunction(
        (id) =>
          document.querySelector(`[data-testid="decision-inbox-item-${id}"]`)?.getAttribute("data-selected") === "true",
        campaignId,
        { timeout: 15000 },
      );
    };

    // 1. CONFIRMED：高优先级可见 + 文案安全（专属 evidence 齐备）
    await selectCampaign(CONFIRMED_ITEM.campaign_id);
    const confirmedPanel = page.locator(
      `[data-hard-risk-state="CONFIRMED"][data-hard-risk-campaign="${CONFIRMED_ITEM.campaign_id}"]`,
    );
    await confirmedPanel.waitFor();
    // 只挂载选中对象：其它 fixture campaign 的 Hard Risk 面板不得同时出现。
    assert.equal(
      await page.locator("[data-hard-risk-state]").count(),
      1,
      "只有选中的投资计划可以挂载 Hard Risk 面板",
    );
    assert.equal(await confirmedPanel.getAttribute("data-hard-risk-tone"), "danger");
    assert.equal(await confirmedPanel.getAttribute("data-hard-risk-safe"), "false");
    await confirmedPanel.getByText("已确认硬风险", { exact: false }).first().waitFor();
    await confirmedPanel.getByText("重新审查", { exact: false }).waitFor();

    // 2. CONFIRMED != EXIT/SELL：面板文本绝不含自动交易指令词
    const confirmedText = await confirmedPanel.innerText();
    for (const token of ["卖出", "退出", "清仓", "EXIT", "SELL"]) {
      assert.equal(confirmedText.includes(token), false, `CONFIRMED 面板不得含「${token}」`);
    }

    // 3. CLEAR：显式 positive-proof（CLEAR+EVALUATED+专属 refs）才显示安全
    await selectCampaign(CLEAR_ITEM.campaign_id);
    const clearPanel = page.locator(
      `[data-hard-risk-state="CLEAR"][data-hard-risk-campaign="${CLEAR_ITEM.campaign_id}"]`,
    );
    await clearPanel.waitFor();
    assert.equal(await clearPanel.getAttribute("data-hard-risk-tone"), "safe");
    assert.equal(await clearPanel.getAttribute("data-hard-risk-safe"), "true");
    await clearPanel.getByText("已确认无硬风险", { exact: false }).waitFor();
    // 专属 authority refs 在折叠的「技术依据」区块里：展开后必须可读。
    await clearPanel.getByText("技术依据（1）", { exact: false }).click();
    await clearPanel.getByText("hard-risk:fixture-clear", { exact: false }).waitFor();

    // BLOCKER 回归：CLEAR 缺少专属 evaluation/refs（generic CLEAN 存在）→ fail closed
    await selectCampaign(MALFORMED_CLEAR_ITEM.campaign_id);
    const malformedClearPanel = page.locator(
      `[data-hard-risk-state="CLEAR"][data-hard-risk-campaign="${MALFORMED_CLEAR_ITEM.campaign_id}"]`,
    );
    await malformedClearPanel.waitFor();
    assert.equal(await malformedClearPanel.getAttribute("data-hard-risk-tone"), "muted");
    await malformedClearPanel.getByText("硬风险状态未知", { exact: false }).first().waitFor();
    const malformedText = await malformedClearPanel.innerText();
    assert.equal(malformedText.includes("已确认无硬风险"), false, "malformed CLEAR 不得显示已确认安全");

    // 污染回归：generic reason 存在（含 HARD_RISK_CONFIRMED）但专属 evidence 缺失
    // → 不得声称已确认，必须 fail closed。
    await selectCampaign(GENERIC_ONLY_ITEM.campaign_id);
    const genericOnlyPanel = page.locator(
      `[data-hard-risk-state="CONFIRMED"][data-hard-risk-campaign="${GENERIC_ONLY_ITEM.campaign_id}"]`,
    );
    await genericOnlyPanel.waitFor();
    assert.equal(await genericOnlyPanel.getAttribute("data-hard-risk-safe"), "false");
    const genericOnlyText = await genericOnlyPanel.innerText();
    assert.equal(genericOnlyText.includes("已确认硬风险"), false, "generic reason 不得证明 CONFIRMED");
    await genericOnlyPanel.getByText("硬风险状态未知", { exact: false }).first().waitFor();

    // 4/5. NOT_EVALUATED / ERROR：一律不绿
    await selectCampaign(NOT_EVALUATED_ITEM.campaign_id);
    const notEvaluatedPanel = page.locator(
      `[data-hard-risk-state="NOT_EVALUATED"][data-hard-risk-campaign="${NOT_EVALUATED_ITEM.campaign_id}"]`,
    );
    await notEvaluatedPanel.waitFor();
    assert.equal(await notEvaluatedPanel.getAttribute("data-hard-risk-safe"), "false");
    await notEvaluatedPanel.getByText("尚未完成硬风险评估", { exact: false }).first().waitFor();

    // DIUX3：适用 Frozen Decision 只提供两个显式、语义分离的下一步入口。
    await selectCampaign(EVALUATED_ITEM.campaign_id);
    const evaluatedDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="EVALUATED"]`,
    );
    await evaluatedDecision.waitFor();
    await evaluatedDecision.getByTestId("formal-decision-next-step-review").waitFor();
    await evaluatedDecision.getByTestId("formal-decision-next-step-new-decision").waitFor();
    assert.equal(
      await evaluatedDecision.getByTestId("formal-decision-next-step-review").getAttribute("href"),
      "/decision-performance",
    );
    assert.equal(
      await evaluatedDecision.getByTestId("formal-decision-next-step-new-decision").getAttribute("href"),
      `/campaigns/${encodeURIComponent(EVALUATED_ITEM.campaign_id)}/decision-proposal`,
    );
    await evaluatedDecision.getByText("这不代表需要立刻形成新决策", { exact: false }).waitFor();
    assert.equal(await evaluatedDecision.getByText("进入正式决策", { exact: true }).count(), 0);

    await selectCampaign(NOT_EVALUATED_ITEM.campaign_id);
    const notEvaluatedDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="NOT_EVALUATED"]`,
    );
    await notEvaluatedDecision.waitFor();
    await notEvaluatedDecision.getByTestId("formal-decision-next-step-proposal").waitFor();
    assert.equal(await notEvaluatedDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await notEvaluatedDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);
    assert.equal(
      await notEvaluatedDecision.getByTestId("formal-decision-next-step-proposal").innerText(),
      "进入正式决策 →",
    );

    await selectCampaign(UNKNOWN_FORMAL_DECISION_ITEM.campaign_id);
    const unknownFormalDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="UNKNOWN"]`,
    );
    await unknownFormalDecision.waitFor();
    assert.equal(
      await unknownFormalDecision.getAttribute("data-formal-decision-evaluation-status"),
      "UNKNOWN",
    );
    await unknownFormalDecision.getByText("当前决策状态：当前信息不足，暂时无法判断。", { exact: true }).waitFor();
    await unknownFormalDecision.getByTestId("formal-decision-next-step-proposal").waitFor();
    assert.equal(
      await unknownFormalDecision.getByTestId("formal-decision-next-step-proposal").innerText(),
      "进入正式决策 →",
    );
    assert.equal(await unknownFormalDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await unknownFormalDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);

    await selectCampaign(ERROR_FORMAL_DECISION_ITEM.campaign_id);
    const errorFormalDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="ERROR"]`,
    );
    await errorFormalDecision.waitFor();
    assert.equal(
      await errorFormalDecision.getAttribute("data-formal-decision-evaluation-status"),
      "ERROR",
    );
    await errorFormalDecision.getByText("当前决策状态：决策状态读取失败。", { exact: true }).waitFor();
    await errorFormalDecision.getByTestId("formal-decision-next-step-proposal").waitFor();
    assert.equal(
      await errorFormalDecision.getByTestId("formal-decision-next-step-proposal").innerText(),
      "进入正式决策 →",
    );
    assert.equal(await errorFormalDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await errorFormalDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);

    await selectCampaign(MALFORMED_FORMAL_DECISION_ITEM.campaign_id);
    const malformedFormalDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="FUTURE_ENUM"]`,
    );
    await malformedFormalDecision.waitFor();
    assert.equal(
      await malformedFormalDecision.getAttribute("data-formal-decision-evaluation-status"),
      "FORMAL_DECISION_EVALUATION_UNKNOWN",
    );
    // 原始状态值只在折叠的「技术详情」里，展开后断言（与 CONFIRMED 的区块一致）。
    // 该行是一行完整文案「常量 · 原始值」，两个事实在同一条里可见。
    await malformedFormalDecision.getByText("技术详情", { exact: true }).click();
    await malformedFormalDecision
      .getByText("FORMAL_DECISION_EVALUATION_UNKNOWN · FUTURE_ENUM", { exact: true })
      .waitFor();
    assert.equal(await malformedFormalDecision.getByTestId("formal-decision-next-step-proposal").count(), 0);
    assert.equal(await malformedFormalDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await malformedFormalDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);
    assert.equal(
      (await malformedFormalDecision.innerText()).includes("已读取适用的 Frozen Decision"),
      false,
    );
    assert.equal(page.url().endsWith("/decision-inbox"), true);

    await selectCampaign(ERROR_ITEM.campaign_id);
    const errorPanel = page.locator(
      `[data-hard-risk-state="UNKNOWN"][data-hard-risk-campaign="${ERROR_ITEM.campaign_id}"]`,
    );
    await errorPanel.waitFor();
    assert.equal(await errorPanel.getAttribute("data-hard-risk-safe"), "false");
    // UNKNOWN + evaluation ERROR：只表达「读取失败 / 不能视为安全」，绝不给安全绿。
    await errorPanel.getByText("硬风险读取失败", { exact: false }).first().waitFor();
    await errorPanel.getByText("读取失败", { exact: true }).waitFor();
    assert.ok(
      (await errorPanel.innerText()).includes("不能视为安全"),
      "UNKNOWN/ERROR 必须明确说明不能视为安全",
    );

    // 7. reason codes 透传可见（CONFIRMED 面板的评估说明，展开后断言）
    await selectCampaign(CONFIRMED_ITEM.campaign_id);
    await confirmedPanel.getByText("评估说明（2）", { exact: false }).waitFor();
    await confirmedPanel.getByText("评估说明（2）", { exact: false }).click();
    await confirmedPanel.getByText("HARD_RISK_CONFIRMED", { exact: false }).waitFor();

    // 8. provenance 可见（同样在折叠的「技术依据」区块里，展开后断言）
    await confirmedPanel.getByText("技术依据（1）", { exact: false }).click();
    await confirmedPanel.getByText("hard-risk:fixture-confirmed", { exact: false }).waitFor();

    // anti-D/E：HardRiskPanel 不展示 generic reason / generic refs
    // （CLEAR_ITEM 的 generic reason_codes=["CLEAN"] 只属于 lifecycle card 的
    // Campaign-level explanation，不得进入 Hard Risk 面板）
    await selectCampaign(CLEAR_ITEM.campaign_id);
    const clearText = await clearPanel.innerText();
    assert.equal(clearText.includes("CLEAN"), false, "generic reason 不得出现在 HardRiskPanel");

    // 9. sibling 隔离：同 security 600519 下 CONFIRMED(SWING) 与 CLEAR(SHORT) 互不影响。
    // 新 IA 下一次只挂载一个选中对象，因此改为「分别选中两个 campaign，各自读到的
    // Hard Risk 判定必须保持独立」。
    await selectCampaign(CONFIRMED_ITEM.campaign_id);
    assert.equal(await confirmedPanel.getAttribute("data-hard-risk-safe"), "false");
    assert.equal(await clearPanel.count(), 0, "未选中的 sibling 不得同时挂载");
    await selectCampaign(CLEAR_ITEM.campaign_id);
    assert.equal(await clearPanel.getAttribute("data-hard-risk-safe"), "true");
    assert.equal(await confirmedPanel.count(), 0, "未选中的 sibling 不得同时挂载");

    // 12. 页面无 console error（next-actions 故意 404 属预期 mock，过滤）
    const unexpectedConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("404"),
    );
    assert.deepEqual(
      unexpectedConsoleErrors,
      [],
      `console errors: ${unexpectedConsoleErrors.join("\n")}`,
    );

    console.log("[HR1 render scaffold] passed.");
  } finally {
    if (browser) await browser.close();
    if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
  }
}

run().catch((error) => {
  console.error("[HR1 render scaffold] FAILED:", error);
  process.exit(1);
});
