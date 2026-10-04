import assert from "node:assert/strict";

const result = (marker, count, from = null) => ({
  as_of_date: "2026-07-31", date_from: from, date_to: null, selected_trade_count: count,
  positions: [{ code: "600001", name: marker, closed_quantity: 0, realized_pnl: 0, remaining_quantity: 1, avg_cost: 10, cost_basis: 10, total_fees: 0, unrealized_pnl: null, data_limitations: [] }],
  totals: { total_realized_pnl: 0, total_unrealized_pnl: null, total_fees: 0, total_cost_basis: 10, position_count: 1 }, data_limitations: [],
});
const summary = (id) => ({ snapshot_id: id, created_at: `SYNTHETIC ${id}`, as_of_date: "2026-07-31", total_realized_pnl: 0, position_count: 1 });

export async function runAttributionOwnership(browser, frontend) {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    const page = await context.newPage();
    const calls = [], errors = [], pending = new Set(), holds = new Map(), allHolds = new Set(), expectedFailureUrls = new Set();
    const expired = [];
    let failNextList = false, frozenCount = 0;
    const snapshots = [summary("A"), summary("B"), summary("C")];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error" && !expectedFailureUrls.has(message.location().url)) errors.push(message.text());
    });
    const holdNext = (key) => {
      let release, started;
      const gate = new Promise((resolve) => { release = resolve; });
      const entered = new Promise((resolve) => { started = resolve; });
      const hold = { gate, entered, release, started };
      holds.set(key, hold); allHolds.add(hold); return hold;
    };
    const handle = async (route) => {
      const request = route.request(), url = new URL(request.url());
      const endpoint = url.pathname;
      const kind = request.method() === "POST" ? "freeze" : endpoint.endsWith("/snapshots") ? "list" : endpoint.includes("/snapshots/") ? endpoint.split("/").at(-1) : "live";
      if (endpoint.startsWith("/api/performance-attribution")) calls.push({ kind, method: request.method(), url: request.url(), body: request.postDataJSON() });
      const hold = holds.get(kind);
      if (hold) {
        holds.delete(kind); hold.started();
        let timer;
        const bounded = new Promise((resolve) => { timer = setTimeout(() => { expired.push(kind); resolve(); }, 15000); });
        try { await Promise.race([hold.gate, bounded]); } finally { clearTimeout(timer); }
      }
      let data;
      if (endpoint === "/api/performance-attribution/snapshot") {
        assert.equal(request.method(), "POST");
        const id = `frozen-${++frozenCount}`; snapshots.push(summary(id));
        data = { snapshot: summary(id), attribution: result(`SYNTHETIC ${id}`, 404, request.postDataJSON()?.date_from ?? null) };
      } else if (endpoint === "/api/performance-attribution/snapshots") {
        if (failNextList) {
          failNextList = false; expectedFailureUrls.add(request.url());
          return route.fulfill({ status: 500, json: { detail: "Synthetic list refresh failure" } });
        }
        data = { items: snapshots };
      } else if (endpoint.includes("/api/performance-attribution/snapshots/")) {
        const id = endpoint.split("/").at(-1);
        if (id === "C") {
          expectedFailureUrls.add(request.url());
          return route.fulfill({ status: 500, json: { detail: "Synthetic snapshot unavailable" } });
        }
        const payload = result(`SYNTHETIC ${id}`, id === "B" ? 202 : 101);
        data = { snapshot: { ...summary(id), payload }, positions: payload.positions };
      } else if (endpoint === "/api/performance-attribution") {
        data = result("SYNTHETIC LIVE", 303, url.searchParams.get("date_from"));
      } else if (endpoint === "/api/trades") data = [];
      else data = {};
      return route.fulfill({ json: { data } });
    };
    await page.route("**/api/**", (route) => {
      const work = handle(route); pending.add(work); void work.finally(() => pending.delete(work)); return work;
    });
    const settle = async () => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const releaseAndFinish = async (hold, path) => {
      const response = page.waitForResponse((response) => new URL(response.url()).pathname === path);
      hold.release(); await (await response).finished(); await settle();
    };
    try {
      await page.goto(`${frontend}/performance-attribution`, { waitUntil: "domcontentloaded" });
      const scope = page.getByTestId("attribution-scope");
      await scope.getByText("303 笔", { exact: true }).waitFor();
      await page.getByRole("button", { name: /历史快照/ }).click();
      const row = (id) => page.getByRole("row").filter({ hasText: `SYNTHETIC ${id}` });
      await row("B").waitFor();
      const oldLive = holdNext("live");
      await page.getByRole("button", { name: "计算", exact: true }).click(); await oldLive.entered;
      await row("B").click(); await scope.getByText("202 笔", { exact: true }).waitFor();
      await releaseAndFinish(oldLive, "/api/performance-attribution");
      assert.match(await scope.innerText(), /202 笔/); await page.getByText("正在查看历史快照 B", { exact: false }).waitFor();

      const oldSnapshot = holdNext("A"); await row("A").click(); await oldSnapshot.entered;
      await row("B").click(); await scope.getByText("202 笔", { exact: true }).waitFor();
      await releaseAndFinish(oldSnapshot, "/api/performance-attribution/snapshots/A");
      assert.match(await scope.innerText(), /202 笔/);

      await row("C").click();
      await page.getByText("归因结果暂不可用，请检查读取状态后重试。", { exact: true }).waitFor();
      assert.equal(await page.getByTestId("attribution-scope").count(), 0);
      assert.equal(await page.getByText("当前结果没有可归因的交易流水。", { exact: true }).count(), 0);

      const oldDate = holdNext("live"); await page.getByLabel("起始日期", { exact: true }).fill("2026-07-01"); await oldDate.entered;
      await page.getByLabel("起始日期", { exact: true }).fill("2026-07-15");
      await scope.getByText("2026-07-15 至 不设结束", { exact: true }).waitFor();
      await releaseAndFinish(oldDate, "/api/performance-attribution");
      assert.match(await scope.innerText(), /2026-07-15 至 不设结束/);

      const freeze = holdNext("freeze"); await page.getByRole("button", { name: "冻结快照", exact: true }).click(); await freeze.entered;
      await row("B").click(); await scope.getByText("202 笔", { exact: true }).waitFor();
      failNextList = true;
      await releaseAndFinish(freeze, "/api/performance-attribution/snapshot");
      await page.getByTestId("attribution-freeze-notice").getByText(/已冻结快照 frozen-1/).waitFor();
      await page.getByRole("alert").getByText(/历史快照列表刷新失败/).waitFor();
      assert.match(await scope.innerText(), /202 笔/);
      assert.equal(calls.filter((call) => call.kind === "freeze").length, 1);
      await page.getByRole("button", { name: "刷新历史列表", exact: true }).click();
      await row("frozen-1").waitFor();
      await page.getByRole("alert").filter({ hasText: "历史快照列表刷新失败" }).waitFor({ state: "detached" });

      const leaveFreeze = holdNext("freeze"); await page.getByRole("button", { name: "冻结快照", exact: true }).click(); await leaveFreeze.entered;
      await page.locator('a[href="/trades"]').last().click(); await page.waitForURL("**/trades");
      await releaseAndFinish(leaveFreeze, "/api/performance-attribution/snapshot");
      await page.locator("[data-sonner-toast]").getByText(/已冻结快照 frozen-2/).waitFor();
      await page.getByRole("heading", { name: "交易流水", exact: true }).waitFor();
      assert.equal(await page.getByTestId("attribution-scope").count(), 0);
      assert.equal(calls.filter((call) => call.kind === "freeze").length, 2, "two explicit clicks only; no automatic retry");
      assert.deepEqual(calls.filter((call) => call.method !== "GET").map((call) => new URL(call.url).pathname), ["/api/performance-attribution/snapshot", "/api/performance-attribution/snapshot"]);
      assert.deepEqual(expired, []); assert.deepEqual(errors, []);
      console.log(`PASS synthetic PA1 ownership ${width}: live/history/date races, confirmed freeze after view change, list failure, unmount acknowledgement`);
    } finally {
      for (const hold of allHolds) hold.release();
      await Promise.allSettled([...pending]);
      await context.close();
    }
  }
}
