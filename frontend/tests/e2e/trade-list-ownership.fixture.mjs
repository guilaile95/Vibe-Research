import assert from "node:assert/strict";

const trade = (code, offset, i = 0) => ({
  trade_id: `synthetic_${code}_${offset}_${i}`, code, name: `SYNTHETIC ${code} ${offset} ${i}`,
  operation: "buy", execution_status: "full", planned_price: null, planned_quantity: null,
  actual_price: 10, actual_quantity: 1, executed_at: "2026-07-31T01:30:00Z", fee: 0, other_cost: 0,
  unexecuted_reason: null, note: null, advice_trade_date: null, advice_generated_at: null, advice_snapshot: null,
  thesis_id: null, thesis_revision: null, created_at: "2026-07-31T01:30:00Z", voided_at: null, void_reason: null,
  gross_amount: 10, total_cost: 10, net_cash_flow: -10, price_variance: null, price_variance_pct: null, quantity_completion_pct: null,
});

export async function runTradeListOwnership(browser, frontend) {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    const page = await context.newPage();
    const reads = [], writes = [], errors = [], expectedFailures = new Set(), holds = new Map(), allHolds = new Set(), pending = new Set(), expired = [];
    let failCurrent = false;
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error" && !expectedFailures.has(message.location().url)) errors.push(message.text()); });
    const holdNext = (code, offset = 0) => {
      let release, entered;
      const gate = new Promise((resolve) => { release = resolve; });
      const started = new Promise((resolve) => { entered = resolve; });
      const hold = { gate, started, entered, release, fail: false };
      holds.set(`${code}:${offset}`, hold); allHolds.add(hold); return hold;
    };
    const handle = async (route) => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() !== "GET") writes.push({ path: url.pathname, method: request.method() });
      if (url.pathname !== "/api/trades") return route.fulfill({ json: { data: {} } });
      const code = url.searchParams.get("code") || "ALL", offset = Number(url.searchParams.get("offset") || 0);
      reads.push({ code, offset, limit: url.searchParams.get("limit"), method: request.method() });
      const hold = holds.get(`${code}:${offset}`);
      if (hold) {
        holds.delete(`${code}:${offset}`); hold.entered(); let timer;
        const timeout = new Promise((resolve) => { timer = setTimeout(() => { expired.push(`${code}:${offset}`); resolve(); }, 15000); });
        try { await Promise.race([hold.gate, timeout]); } finally { clearTimeout(timer); }
      }
      if (hold?.fail || (code === "000003" && failCurrent)) {
        expectedFailures.add(request.url()); return route.fulfill({ status: 500, json: { detail: "Synthetic trade list failure" } });
      }
      const data = code === "ALL" ? Array.from({ length: 10 }, (_, i) => trade(`6000${String(i + 1).padStart(2, "0")}`, offset, i)) : [trade(code, offset)];
      return route.fulfill({ json: { data } });
    };
    await page.route("**/api/**", (route) => {
      const work = handle(route); pending.add(work); void work.finally(() => pending.delete(work)); return work;
    });
    const settle = async () => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const releaseAndFinish = async (hold, code, offset = 0) => {
      const response = page.waitForResponse((response) => {
        const url = new URL(response.url()); return url.pathname === "/api/trades" && (url.searchParams.get("code") || "ALL") === code && Number(url.searchParams.get("offset") || 0) === offset;
      });
      hold.release(); await (await response).finished(); await settle();
    };
    const rows = page.getByTestId("trade-list-row");
    const filter = page.getByPlaceholder("6位数字代码", { exact: true });
    const submit = async (code) => { await filter.fill(code); await page.getByRole("button", { name: "筛选", exact: true }).click(); };
    const rowFor = (code) => page.locator(`[data-testid="trade-list-row"][data-security-code="${code}"]`);
    try {
      await page.goto(`${frontend}/trades`, { waitUntil: "domcontentloaded" });
      await page.getByRole("heading", { name: "交易流水", exact: true }).waitFor(); await rowFor("600001").waitFor();
      const initialReads = reads.length; await filter.fill("000001"); await settle(); assert.equal(reads.length, initialReads, "draft edits alone must not query");
      const first = holdNext("000001"); await submit("000001"); await first.started;
      await submit("000002"); await rowFor("000002").waitFor(); await releaseAndFinish(first, "000001");
      assert.equal(await filter.inputValue(), "000002"); assert.equal(await rows.count(), 1); assert.equal(await rowFor("000001").count(), 0);
      assert.equal(await rows.first().getAttribute("data-trade-id"), "synthetic_000002_0_0");

      const staleError = holdNext("000001"); staleError.fail = true; await submit("000001"); await staleError.started;
      await submit("000002"); await rowFor("000002").waitFor(); await releaseAndFinish(staleError, "000001");
      assert.equal(await page.getByRole("heading", { name: "加载交易流水失败", exact: true }).count(), 0); assert.equal(await rowFor("000002").count(), 1);

      const early = holdNext("000001"), current = holdNext("000002");
      await submit("000001"); await early.started; await submit("000002"); await current.started;
      await releaseAndFinish(early, "000001");
      await page.getByText("加载交易流水中...", { exact: true }).waitFor(); assert.equal(await rows.count(), 0);
      await releaseAndFinish(current, "000002"); await rowFor("000002").waitFor();

      const beforeReset = holdNext("000001"); await submit("000001"); await beforeReset.started;
      await page.getByRole("button", { name: "重置", exact: true }).click(); await rowFor("600001").waitFor();
      await releaseAndFinish(beforeReset, "000001"); assert.equal(await filter.inputValue(), ""); assert.equal(await rows.count(), 10); assert.equal(await rowFor("000001").count(), 0);

      const oldPage = holdNext("ALL", 10); await page.getByRole("button", { name: "下一页", exact: true }).click(); await oldPage.started;
      await page.getByRole("button", { name: "重置", exact: true }).click(); await rowFor("600001").waitFor();
      await releaseAndFinish(oldPage, "ALL", 10); assert.match(await rows.first().getAttribute("data-trade-id"), /_0_0$/);
      await page.getByText("第 1 页", { exact: true }).waitFor();

      failCurrent = true; await submit("000003"); await page.getByRole("heading", { name: "加载交易流水失败", exact: true }).waitFor(); assert.equal(await rows.count(), 0);
      failCurrent = false; await page.getByRole("button", { name: "重试", exact: true }).click(); await rowFor("000003").waitFor(); assert.equal(await filter.inputValue(), "000003");

      const leaving = holdNext("000001"); await submit("000001"); await leaving.started;
      await page.getByTestId("section-nav").getByRole("link", { name: "收益归因", exact: true }).click();
      await page.getByRole("heading", { name: "收益归因", exact: true }).waitFor();
      await releaseAndFinish(leaving, "000001"); assert.equal(await rows.count(), 0);
      assert.ok(reads.every((read) => read.method === "GET" && read.limit === "10"));
      assert.deepEqual(writes, []); assert.deepEqual(expired, []); assert.deepEqual(errors, []);
      console.log(`PASS synthetic trade list ownership ${width}: route/query/row IDs, stale success/error/finally, reset/page/retry/unmount, zero writes`);
    } finally {
      for (const hold of allHolds) hold.release();
      await Promise.allSettled([...pending]); await context.close();
    }
  }
}
