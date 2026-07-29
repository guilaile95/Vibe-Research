import { chromium } from "playwright";
import { createServer } from "node:http";
import { existsSync, createReadStream } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

function getFreePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const port = s.address().port;
      s.close(() => resolve(port));
    });
  });
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
  };
  const server = createServer((req, res) => {
    let pn = (req.url || "/").split("?")[0];
    if (pn === "/") pn = "/index.html";
    let target = path.join(dir, pn);
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

async function launchBrowser() {
  const home = process.env.USERPROFILE || process.env.HOME || "";
  const pwDir = path.join(home, "AppData", "Local", "ms-playwright");
  const candidates = [
    { label: "bundled", opts: { headless: true } },
    { label: "chromium-1208", opts: { executablePath: path.join(pwDir, "chromium-1208", "chrome-win64", "chrome.exe"), headless: true } },
    { label: "chromium-1234", opts: { executablePath: path.join(pwDir, "chromium-1234", "chrome-win64", "chrome.exe"), headless: true } },
    { label: "msedge", opts: { channel: "msedge", headless: true } },
    { label: "chrome", opts: { channel: "chrome", headless: true } },
  ];
  for (const c of candidates) {
    if (c.opts.executablePath && !existsSync(c.opts.executablePath)) continue;
    try {
      const b = await chromium.launch(c.opts);
      console.log(`Launched browser using candidate: ${c.label}`);
      return b;
    } catch {
      /* try next */
    }
  }
  throw new Error("Could not launch any browser candidate");
}

async function runTest() {
  console.log("Starting Decision Feedback Failure E2E Test...");
  const port = await getFreePort();
  const server = await startStaticServer(frontendDist, port);
  const baseUrl = `http://127.0.0.1:${port}`;

  const browser = await launchBrowser();
  const page = await browser.newPage();
  page.on("console", (msg) => console.log("PAGE CONSOLE:", msg.type(), msg.text()));
  page.on("pageerror", (err) => console.error("PAGE ERROR:", err));

  try {
    // ------------------------------------------------------------------------
    // Case 1: 列表首次加载失败展示错误卡片，点击「重试」后能够成功恢复
    // ------------------------------------------------------------------------
    console.log("Case 1: Testing list initial load failure and retry recovery...");
    let listFailedFirst = true;

    await page.route("**/api/decision-feedback*", async (route) => {
      const request = route.request();
      if (request.method() === "GET" && !request.url().includes("/api/decision-feedback/")) {
        if (listFailedFirst) {
          return route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "服务器内部错误，无法读取列表" }),
          });
        } else {
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              data: [
                {
                  feedback_id: "fb-001",
                  code: "600519",
                  advice_trade_date: "2026-07-29",
                  advice_generated_at: "2026-07-29T08:00:00Z",
                  trade_id: "trade_100",
                  adoption_status: "followed",
                  outcome_status: "not_evaluated",
                  note: "初始测试项",
                  created_at: "2026-07-29T08:30:00Z",
                  voided_at: null,
                  void_reason: null,
                },
              ],
            }),
          });
        }
      }
      return route.continue();
    });

    await page.goto(`${baseUrl}/decision-feedback`);
    await page.waitForSelector("text=服务器内部错误，无法读取列表");
    const retryBtn = page.locator("button:has-text('重试加载')");
    assert.ok(await retryBtn.isVisible(), "重试加载按钮应可见");

    // Click retry after setting listFailedFirst to false
    listFailedFirst = false;
    await retryBtn.click();
    await page.waitForSelector("td:has-text('600519')");
    console.log("  Pass: List failure card showed retry button and recovered upon click.");

    // Unroute for subsequent tests
    await page.unroute("**/api/decision-feedback*");

    // ------------------------------------------------------------------------
    // Case 2: 创建接口返回 404/409/422 错误时，Modal 顶部提示错误且保留表单用户输入不丢失
    // ------------------------------------------------------------------------
    console.log("Case 2: Testing create API 404/409/422 errors, error banner, and form input retention...");

    let createStatus = 404;
    let createErrorDetail = "关联数据不存在（持仓建议或交易记录）";

    await page.route("**/api/decision-feedback**", async (route) => {
      const req = route.request();
      const method = req.method();
      const url = req.url();
      if (method === "GET" && !url.includes("/api/decision-feedback/")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: [] }),
        });
      }
      if (method === "POST" && !url.includes("/void")) {
        return route.fulfill({
          status: createStatus,
          contentType: "application/json",
          body: JSON.stringify({ detail: createErrorDetail }),
        });
      }
      return route.continue();
    });

    // Click "新建决策反馈"
    await page.click("button:has-text('新建决策反馈')");
    await page.waitForSelector("form");

    // Fill form fields in modal
    await page.fill("div.fixed form input[placeholder*='6位数字']", "600519");
    await page.fill("div.fixed form textarea[placeholder*='备注']", "测试保留输入文本 - 404");

    // Submit form for 404
    await page.getByRole("button", { name: "提交创建" }).click();
    await page.getByText(createErrorDetail).waitFor();

    // Verify input fields preserved
    let codeValue = await page.inputValue("div.fixed form input[placeholder*='6位数字']");
    let noteValue = await page.inputValue("div.fixed form textarea[placeholder*='备注']");
    assert.equal(codeValue, "600519", "404 错误时股票代码输入应保留");
    assert.equal(noteValue, "测试保留输入文本 - 404", "404 错误时备注输入应保留");
    assert.ok(await page.isVisible("h3:has-text('新建决策反馈')"), "Modal 不应关闭");

    // Test 409 error on create
    createStatus = 409;
    createErrorDetail = "建议发生变化，生成时间不一致";
    await page.getByRole("button", { name: "提交创建" }).click();
    await page.getByText(createErrorDetail).waitFor();
    codeValue = await page.inputValue("div.fixed form input[placeholder*='6位数字']");
    noteValue = await page.inputValue("div.fixed form textarea[placeholder*='备注']");
    assert.equal(codeValue, "600519", "409 错误时股票代码输入应保留");
    assert.equal(noteValue, "测试保留输入文本 - 404", "409 错误时备注输入应保留");

    // Test 422 error on create
    createStatus = 422;
    createErrorDetail = "请求字段校验失败";
    await page.getByRole("button", { name: "提交创建" }).click();
    await page.getByText(createErrorDetail).waitFor();
    codeValue = await page.inputValue("div.fixed form input[placeholder*='6位数字']");
    assert.equal(codeValue, "600519", "422 错误时股票代码输入应保留");

    // Close create modal
    await page.click("div.fixed form button:has-text('取消')");
    await page.unroute("**/api/decision-feedback**");
    console.log("  Pass: Create API 404/409/422 errors display inside modal and preserve user input.");

    // ------------------------------------------------------------------------
    // Case 3: 详情加载失败时错误提示在 Modal 内可见
    // ------------------------------------------------------------------------
    console.log("Case 3: Testing detail load failure message visible inside Modal...");

    await page.route("**/api/decision-feedback**", async (route) => {
      const req = route.request();
      if (req.method() === "GET" && !req.url().includes("/api/decision-feedback/")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: [
              {
                feedback_id: "fb-detail-err",
                code: "000001",
                advice_trade_date: "2026-07-29",
                advice_generated_at: "2026-07-29T08:00:00Z",
                trade_id: null,
                adoption_status: "followed",
                outcome_status: "not_evaluated",
                note: "",
                created_at: "2026-07-29T08:30:00Z",
                voided_at: null,
                void_reason: null,
              },
            ],
          }),
        });
      }
      if (req.method() === "GET" && req.url().includes("/api/decision-feedback/fb-detail-err")) {
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "获取决策反馈详情异常" }),
        });
      }
      return route.continue();
    });

    await page.goto(`${baseUrl}/decision-feedback`);
    await page.waitForSelector("td:has-text('000001')");
    await page.locator("td button:has-text('详情')").click();
    await page.getByText("获取决策反馈详情异常").waitFor();
    assert.ok(await page.isVisible("h3:has-text('决策反馈详情')"), "详情 Modal 应打开");
    assert.ok(await page.getByText("获取决策反馈详情异常").isVisible(), "详情错误文案在 Modal 内可见");

    // Close detail modal
    await page.locator("h3:has-text('决策反馈详情') ~ button").click();
    await page.unroute("**/api/decision-feedback**");
    console.log("  Pass: Detail error message is visible inside detail Modal.");

    // ------------------------------------------------------------------------
    // Case 4: 作废接口返回 409 冲突时，作废确认 Modal 不关闭，并在弹窗内展示 409 错误提示
    // ------------------------------------------------------------------------
    console.log("Case 4: Testing void 409 conflict keeps Modal open and shows error...");

    await page.route("**/api/decision-feedback**", async (route) => {
      const req = route.request();
      if (req.method() === "GET" && !req.url().includes("/api/decision-feedback/")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: [
              {
                feedback_id: "fb-void-conflict",
                code: "600519",
                advice_trade_date: "2026-07-29",
                advice_generated_at: "2026-07-29T08:00:00Z",
                trade_id: null,
                adoption_status: "followed",
                outcome_status: "not_evaluated",
                note: "",
                created_at: "2026-07-29T08:30:00Z",
                voided_at: null,
                void_reason: null,
              },
            ],
          }),
        });
      }
      if (req.method() === "POST" && req.url().includes("/void")) {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "该决策反馈已被作废，无法重复作废" }),
        });
      }
      return route.continue();
    });

    await page.goto(`${baseUrl}/decision-feedback`);
    await page.waitForSelector("button:has-text('作废')");
    await page.click("button:has-text('作废')");
    await page.waitForSelector("h3:has-text('作废决策反馈')");

    await page.fill("div.fixed textarea[placeholder*='作废原因']", "并发作废测试");
    await page.click("div.fixed button:has-text('确认作废')");

    await page.getByText("该决策反馈已被作废，无法重复作废").waitFor();
    assert.ok(await page.isVisible("h3:has-text('作废决策反馈')"), "作废 Modal 在 409 时不应关闭");

    // Close void modal
    await page.click("div.fixed button:has-text('取消')");
    await page.unroute("**/api/decision-feedback**");
    console.log("  Pass: Void 409 conflict keeps Modal open and displays error message.");

    // ------------------------------------------------------------------------
    // Case 5: 确认 HTML 错误正文不直接显示在 UI 上
    // ------------------------------------------------------------------------
    console.log("Case 5: Testing HTML error responses are not dumped into UI...");

    await page.route("**/api/decision-feedback**", async (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 500,
          contentType: "text/html",
          body: "<html><body><h1>500 Internal Server Error</h1></body></html>",
        });
      }
      return route.continue();
    });

    await page.goto(`${baseUrl}/decision-feedback`);
    await page.waitForSelector("text=HTTP 500");
    const rawHtmlVisible = await page.isVisible("text=<h1>500 Internal Server Error</h1>");
    assert.equal(rawHtmlVisible, false, "HTML 标签正文绝不应直接渲染在 UI 上");
    console.log("  Pass: HTML error body is sanitized and not rendered raw in UI.");

    await page.unroute("**/api/decision-feedback**");

    // ------------------------------------------------------------------------
    // Case 6: 分页按钮上一页/下一页可用性核验
    // ------------------------------------------------------------------------
    console.log("Case 6: Testing pagination prev/next button states...");

    const generateItems = (count, startId = 1) =>
      Array.from({ length: count }, (_, i) => ({
        feedback_id: `fb-pg-${startId + i}`,
        code: "600519",
        advice_trade_date: "2026-07-29",
        advice_generated_at: "2026-07-29T08:00:00Z",
        trade_id: null,
        adoption_status: "followed",
        outcome_status: "not_evaluated",
        note: `分页条目 ${startId + i}`,
        created_at: "2026-07-29T08:30:00Z",
        voided_at: null,
        void_reason: null,
      }));

    await page.route("**/api/decision-feedback**", async (route) => {
      const url = new URL(route.request().url());
      const offset = parseInt(url.searchParams.get("offset") || "0");
      if (offset === 0) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: generateItems(10, 1) }),
        });
      } else {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: generateItems(4, 11) }),
        });
      }
    });

    await page.goto(`${baseUrl}/decision-feedback`);
    await page.waitForSelector("tbody tr");

    const prevBtn = page.locator("button:has-text('上一页')");
    const nextBtn = page.locator("button:has-text('下一页')");
    const rows = page.locator("tbody tr");

    assert.equal(await rows.count(), 10, "第一页应有10条数据");
    assert.equal(await prevBtn.isDisabled(), true, "第一页时上一页按钮应被禁用");
    assert.equal(await nextBtn.isDisabled(), false, "有满页数据时下一页按钮应可用");

    await nextBtn.click();
    await page.waitForFunction(() => document.querySelectorAll("tbody tr").length === 4);

    assert.equal(await rows.count(), 4, "第二页应有4条数据");
    assert.equal(await prevBtn.isDisabled(), false, "第二页时上一页按钮应可用");
    assert.equal(await nextBtn.isDisabled(), true, "第二页不足满页时下一页按钮应被禁用");

    await prevBtn.click();
    await page.waitForFunction(() => document.querySelectorAll("tbody tr").length === 10);
    assert.equal(await prevBtn.isDisabled(), true, "返回第一页后上一页按钮重新禁用");

    console.log("  Pass: Pagination prev/next buttons function and disable correctly.");

    console.log("\nAll Decision Feedback Failure E2E tests PASSED successfully!");
  } finally {
    await browser.close();
    server.close();
  }
}

runTest().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});
