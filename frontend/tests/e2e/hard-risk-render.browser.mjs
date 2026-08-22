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

    await page.goto(`http://127.0.0.1:${port}/decision-inbox`, { waitUntil: "networkidle" });

    // 1. CONFIRMED：高优先级可见 + 文案安全（专属 evidence 齐备）
    const confirmedPanel = page.locator(
      `[data-hard-risk-state="CONFIRMED"][data-hard-risk-campaign="${CONFIRMED_ITEM.campaign_id}"]`,
    );
    await confirmedPanel.waitFor();
    assert.equal(await confirmedPanel.getAttribute("data-hard-risk-tone"), "danger");
    assert.equal(await confirmedPanel.getAttribute("data-hard-risk-safe"), "false");
    await confirmedPanel.getByText("已确认 Hard Risk", { exact: false }).first().waitFor();
    await confirmedPanel.getByText("重新审查", { exact: false }).waitFor();

    // 2. CONFIRMED != EXIT/SELL：面板文本绝不含自动交易指令词
    const confirmedText = await confirmedPanel.innerText();
    for (const token of ["卖出", "退出", "清仓", "EXIT", "SELL"]) {
      assert.equal(confirmedText.includes(token), false, `CONFIRMED 面板不得含「${token}」`);
    }

    // 3. CLEAR：显式 positive-proof（CLEAR+EVALUATED+专属 refs）才显示安全
    const clearPanel = page.locator(
      `[data-hard-risk-state="CLEAR"][data-hard-risk-campaign="${CLEAR_ITEM.campaign_id}"]`,
    );
    await clearPanel.waitFor();
    assert.equal(await clearPanel.getAttribute("data-hard-risk-tone"), "safe");
    assert.equal(await clearPanel.getAttribute("data-hard-risk-safe"), "true");
    await clearPanel.getByText("已确认无 Hard Risk", { exact: false }).waitFor();
    await clearPanel.getByText("hard-risk:fixture-clear", { exact: false }).waitFor();

    // BLOCKER 回归：CLEAR 缺少专属 evaluation/refs（generic CLEAN 存在）→ fail closed
    const malformedClearPanel = page.locator(
      `[data-hard-risk-state="CLEAR"][data-hard-risk-campaign="${MALFORMED_CLEAR_ITEM.campaign_id}"]`,
    );
    await malformedClearPanel.waitFor();
    assert.equal(await malformedClearPanel.getAttribute("data-hard-risk-tone"), "muted");
    await malformedClearPanel.getByText("Hard Risk 状态未知", { exact: false }).first().waitFor();
    const malformedText = await malformedClearPanel.innerText();
    assert.equal(malformedText.includes("已确认无 Hard Risk"), false, "malformed CLEAR 不得显示已确认安全");

    // 污染回归：generic reason 存在（含 HARD_RISK_CONFIRMED）但专属 evidence 缺失
    // → 不得声称已确认，必须 fail closed。
    const genericOnlyPanel = page.locator(
      `[data-hard-risk-state="CONFIRMED"][data-hard-risk-campaign="${GENERIC_ONLY_ITEM.campaign_id}"]`,
    );
    await genericOnlyPanel.waitFor();
    assert.equal(await genericOnlyPanel.getAttribute("data-hard-risk-safe"), "false");
    const genericOnlyText = await genericOnlyPanel.innerText();
    assert.equal(genericOnlyText.includes("已确认 Hard Risk"), false, "generic reason 不得证明 CONFIRMED");
    await genericOnlyPanel.getByText("Hard Risk 状态未知", { exact: false }).first().waitFor();

    // 4/5. NOT_EVALUATED / ERROR：一律不绿
    const notEvaluatedPanel = page.locator(`[data-hard-risk-state="NOT_EVALUATED"]`);
    await notEvaluatedPanel.waitFor();
    assert.equal(await notEvaluatedPanel.getAttribute("data-hard-risk-safe"), "false");
    await notEvaluatedPanel.getByText("尚未完成 Hard Risk 评估", { exact: false }).first().waitFor();

    // DIUX3：适用 Frozen Decision 只提供两个显式、语义分离的下一步入口。
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
    await evaluatedDecision.getByText("已有 Frozen Decision 不代表需要立刻 Freeze 新 Decision", { exact: false }).waitFor();
    assert.equal(await evaluatedDecision.getByText("打开 Formal Decision Review", { exact: true }).count(), 0);

    const notEvaluatedDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="NOT_EVALUATED"]`,
    );
    await notEvaluatedDecision.waitFor();
    await notEvaluatedDecision.getByTestId("formal-decision-next-step-proposal").waitFor();
    assert.equal(await notEvaluatedDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await notEvaluatedDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);
    assert.equal(
      await notEvaluatedDecision.getByTestId("formal-decision-next-step-proposal").innerText(),
      "打开 Formal Decision Review →",
    );

    const unknownFormalDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="UNKNOWN"]`,
    );
    await unknownFormalDecision.waitFor();
    assert.equal(
      await unknownFormalDecision.getAttribute("data-formal-decision-evaluation-status"),
      "UNKNOWN",
    );
    await unknownFormalDecision.getByText("当前无法评价 Formal Decision。", { exact: true }).waitFor();
    await unknownFormalDecision.getByTestId("formal-decision-next-step-proposal").waitFor();
    assert.equal(
      await unknownFormalDecision.getByTestId("formal-decision-next-step-proposal").innerText(),
      "打开 Formal Decision Review →",
    );
    assert.equal(await unknownFormalDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await unknownFormalDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);

    const errorFormalDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="ERROR"]`,
    );
    await errorFormalDecision.waitFor();
    assert.equal(
      await errorFormalDecision.getAttribute("data-formal-decision-evaluation-status"),
      "ERROR",
    );
    await errorFormalDecision.getByText("Formal Decision 评估读取失败。", { exact: true }).waitFor();
    await errorFormalDecision.getByTestId("formal-decision-next-step-proposal").waitFor();
    assert.equal(
      await errorFormalDecision.getByTestId("formal-decision-next-step-proposal").innerText(),
      "打开 Formal Decision Review →",
    );
    assert.equal(await errorFormalDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await errorFormalDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);

    const malformedFormalDecision = page.locator(
      `[data-formal-decision-inbox-evaluation="FUTURE_ENUM"]`,
    );
    await malformedFormalDecision.waitFor();
    assert.equal(
      await malformedFormalDecision.getAttribute("data-formal-decision-evaluation-status"),
      "FORMAL_DECISION_EVALUATION_UNKNOWN",
    );
    await malformedFormalDecision.getByText("FUTURE_ENUM", { exact: true }).waitFor();
    await malformedFormalDecision.getByText("FORMAL_DECISION_EVALUATION_UNKNOWN", { exact: true }).waitFor();
    assert.equal(await malformedFormalDecision.getByTestId("formal-decision-next-step-proposal").count(), 0);
    assert.equal(await malformedFormalDecision.getByTestId("formal-decision-next-step-review").count(), 0);
    assert.equal(await malformedFormalDecision.getByTestId("formal-decision-next-step-new-decision").count(), 0);
    assert.equal(
      (await malformedFormalDecision.innerText()).includes("已读取适用的 Frozen Decision"),
      false,
    );
    assert.equal(page.url().endsWith("/decision-inbox"), true);

    const errorPanel = page.locator(`[data-hard-risk-state="UNKNOWN"]`);
    await errorPanel.waitFor();
    assert.equal(await errorPanel.getAttribute("data-hard-risk-safe"), "false");
    await errorPanel.getByText("Hard Risk 评估失败", { exact: false }).first().waitFor();
    await errorPanel.getByText("ERROR", { exact: true }).waitFor();

    // 7. reason codes 透传可见（CONFIRMED 面板的评估说明，展开后断言）
    await confirmedPanel.getByText("评估说明（2）", { exact: false }).waitFor();
    await confirmedPanel.getByText("评估说明（2）", { exact: false }).click();
    await confirmedPanel.getByText("HARD_RISK_CONFIRMED", { exact: false }).waitFor();

    // 8. provenance 可见
    await confirmedPanel.getByText("hard-risk:fixture-confirmed", { exact: false }).waitFor();

    // anti-D/E：HardRiskPanel 不展示 generic reason / generic refs
    // （CLEAR_ITEM 的 generic reason_codes=["CLEAN"] 只属于 lifecycle card 的
    // Campaign-level explanation，不得进入 Hard Risk 面板）
    const clearText = await clearPanel.innerText();
    assert.equal(clearText.includes("CLEAN"), false, "generic reason 不得出现在 HardRiskPanel");

    // 9. sibling 隔离：同 security 600519 下 CONFIRMED(SWING) 与 CLEAR(SHORT) 互不影响
    assert.equal(await confirmedPanel.getAttribute("data-hard-risk-safe"), "false");
    assert.equal(await clearPanel.getAttribute("data-hard-risk-safe"), "true");

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
