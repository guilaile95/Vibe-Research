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

const CONFIRMED_ITEM = item({
  visible_state: "REVIEW_REQUIRED",
  reason_codes: ["HARD_RISK_CONFIRMED", "REVIEW_BY_REACHED"],
  hard_risk_state: "CONFIRMED",
  hard_risk_evaluation: "EVALUATED",
  authority_refs: ["hard-risk:fixture-confirmed"],
  campaign_id: `campaign_${"a".repeat(32)}`,
});

const CLEAR_ITEM = item({
  visible_state: "NO_ACTION_REQUIRED",
  reason_codes: ["CLEAN"],
  hard_risk_state: "CLEAR",
  hard_risk_evaluation: "EVALUATED",
  authority_refs: ["hard-risk:fixture-clear"],
  strategy: "SHORT",
  campaign_id: `campaign_${"b".repeat(32)}`,
});

const NOT_EVALUATED_ITEM = item({
  visible_state: "BLOCKED_BY_DATA",
  reason_codes: ["HARD_RISK_NOT_EVALUATED", "COVERAGE_INCOMPLETE"],
  hard_risk_state: "NOT_EVALUATED",
  hard_risk_evaluation: "NOT_EVALUATED",
  security_code: "000001",
  strategy: "MEDIUM",
  campaign_id: `campaign_${"c".repeat(32)}`,
});

const ERROR_ITEM = item({
  visible_state: "BLOCKED_BY_DATA",
  reason_codes: ["HARD_RISK_UNKNOWN"],
  hard_risk_state: "UNKNOWN",
  hard_risk_evaluation: "ERROR",
  strategy: "SWING",
  campaign_id: `campaign_${"d".repeat(32)}`,
});

const SNAPSHOT = {
  schema_version: "decision_inbox_runtime.v0.1",
  as_of: AS_OF,
  evaluation_status: "EVALUATED",
  canonical: true,
  reason_codes: [],
  holding_setup_items: [],
  campaign_items: [CONFIRMED_ITEM, CLEAR_ITEM, NOT_EVALUATED_ITEM, ERROR_ITEM],
  total_holdings: 0,
  total_campaign_items: 4,
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

    // 1. CONFIRMED：高优先级可见 + 文案安全
    const confirmedPanel = page.locator(`[data-hard-risk-state="CONFIRMED"]`);
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

    // 3. CLEAR：显式 positive-proof 才显示安全
    const clearPanel = page.locator(`[data-hard-risk-state="CLEAR"]`);
    await clearPanel.waitFor();
    assert.equal(await clearPanel.getAttribute("data-hard-risk-tone"), "safe");
    assert.equal(await clearPanel.getAttribute("data-hard-risk-safe"), "true");
    await clearPanel.getByText("已确认无 Hard Risk", { exact: false }).waitFor();
    await clearPanel.getByText("hard-risk:fixture-clear", { exact: false }).waitFor();

    // 4/5. NOT_EVALUATED / ERROR：一律不绿
    const notEvaluatedPanel = page.locator(`[data-hard-risk-state="NOT_EVALUATED"]`);
    await notEvaluatedPanel.waitFor();
    assert.equal(await notEvaluatedPanel.getAttribute("data-hard-risk-safe"), "false");
    await notEvaluatedPanel.getByText("尚未完成 Hard Risk 评估", { exact: false }).first().waitFor();

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
