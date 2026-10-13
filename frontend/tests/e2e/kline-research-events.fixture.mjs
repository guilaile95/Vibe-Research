import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const dates = ["2026-07-17", "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"];
const evidence = (code, id, date) => ({ id, subject_type: "stock", subject_id: code, evidence_type: "report", claim: "Synthetic evidence only", source_title: `合成证据 ${id}`, source_date: date, source_url: null, accessed_at: "2026-07-24", created_at: "2026-07-24", updated_at: "2026-07-24", classification: "fact", confidence: "high", deleted: 0, deleted_at: null });
const calendarEvent = (code, id, date) => ({ event_id: id, security_code: code, security_name: null, campaign_ids: ["campaign_alpha", "campaign_beta"], event_type: "ANNOUNCEMENT", event_date: date, date_semantics: date ? "DATE_ONLY" : "UNKNOWN", state: "OBSERVED", title: `合成事件 ${id}`, details: {}, source: "synthetic fixture", source_record_identity: id, fetched_at: "2026-07-24", limitations: [] });

export async function runKlineResearchEvents({ page, mock, baseUrl, openTab, expandKline, fillCode, clickQuery, waitForStockHeader }) {
  const calls = []; const writes = [];
  let hold = false; let release; let held; let calendarUnavailable = false; let chartPhase = false;
  const routeHandler = async (route) => {
    const request = route.request(); const url = new URL(request.url()); const code = url.searchParams.get("security_code") || url.searchParams.get("subject_id") || url.searchParams.get("code") || "000001";
    if (request.method() !== "GET") writes.push({ path: url.pathname, method: request.method() });
    const send = (data) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data }) });
    if (url.pathname === "/api/kline") return send(dates.map((date, i) => ({ date, open: 10 + i, high: 11 + i, low: 9 + i, close: 10.5 + i, volume: 1000, amount: 10000 })));
    if (url.pathname === "/api/research-events") {
      calls.push({ kind: "calendar", surface: chartPhase ? "chart" : "overview", code, from: url.searchParams.get("date_from"), to: url.searchParams.get("date_to") });
      if (hold) {
        hold = false; let timer;
        held = new Promise((resolve) => { release = resolve; timer = setTimeout(resolve, 5000); });
        try { await held; } finally { clearTimeout(timer); }
      }
      return send({ schema_version: "research_event_calendar.v0.1", as_of: "2026-07-24", fetched_at: "2026-07-24", window: { date_from: dates[0], date_to: dates.at(-1), semantics: "CALENDAR_DAYS" }, universe: { kind: "SINGLE_SECURITY", status: "NORMAL", campaign_count: 2, unique_security_count: 1, max_unique_securities: 1, securities: [{ security_code: code, security_name: null, campaign_ids: ["campaign_alpha", "campaign_beta"] }] }, sources: [], writes: { campaign: 0, thesis: 0, evidence: 0, decision: 0, trade: 0, account: 0 }, status: calendarUnavailable ? "UNAVAILABLE" : "NORMAL", events: calendarUnavailable ? [] : [calendarEvent(code, `${code}-weekend`, "2026-07-18"), calendarEvent(code, `${code}-unknown`, null), calendarEvent("foreign", "must-not-crosslink", "2026-07-20")], limitations: calendarUnavailable ? ["SYNTHETIC_SOURCE_UNAVAILABLE"] : [] });
    }
    if (url.pathname === "/api/evidence") {
      calls.push({ kind: "evidence", code, limit: url.searchParams.get("limit"), offset: url.searchParams.get("offset") });
      return send({ items: [evidence(code, `${code}-exact`, "2026-07-20"), evidence(code, `${code}-old`, "2026-07-01"), evidence("foreign", "must-not-leak", "2026-07-20")], total: 103, limit: 100, offset: 0 });
    }
    if (/\/api\/evidence\/[^/]+\/temporal-authority$/.test(url.pathname)) return send({ temporal_state: "UNPROVEN", temporal_basis: "NONE", effective_at: null, authority_refs: [], reason_codes: [], ec1_evaluation: "NOT_EVALUATED", observed_time_is_not_effective_time: true });
    if (/\/api\/evidence\/[^/]+$/.test(url.pathname)) return send(evidence("000001", decodeURIComponent(url.pathname.split("/").at(-1)), "2026-07-20"));
    return route.fallback();
  };
  await page.route("**/api/**", routeHandler);
  mock.setTechnicalIndicatorsStatus("unavailable");
  try {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      chartPhase = false;
      await page.goto(`${baseUrl}/stock-data?code=000001`, { waitUntil: "domcontentloaded" });
      await waitForStockHeader(page, "000001", "平安银行");
      // Existing overview calendar has its own default-window request. Finish it
      // before measuring the separate opt-in chart reads.
      await page.getByTestId("research-event-calendar").getByTestId("research-event-row").first().waitFor();
      await openTab(page, "market"); chartPhase = true; await expandKline(page);
      await page.getByTestId("kline-candle").first().waitFor();
      const before = calls.length;
      const toggle = page.getByRole("button", { name: "显示研究事件", exact: true });
      await toggle.waitFor(); assert.equal(calls.length, before, "viewing prices cannot request events");
      await toggle.focus(); await page.keyboard.press("Enter");
      const weekend = page.locator('[data-event-id="000001-weekend"]');
      await weekend.waitFor();
      const list = page.getByTestId("kline-research-list");
      assert.match(await weekend.innerText(), /2026-07-18/);
      assert.match(await weekend.innerText(), /下一条可用 K 线 2026-07-20/);
      assert.equal(await page.getByTestId("kline-research-marker").count(), 1, "same-bar records grouped, no overlap");
      assert.equal(await page.getByTestId("kline-candle").count(), 5, "unavailable indicators preserve prices");
      assert.equal(await page.getByTestId("kline-overlay-legend").count(), 0);
      assert.match(await list.innerText(), /证据共 103 条，本次仅取得 3 条/);
      assert.match(await page.locator('[data-event-id="000001-old"]').innerText(), /超出当前可见/);
      assert.match(await page.locator('[data-event-id="000001-unknown"]').innerText(), /不落点，也不以今天/);
      assert.equal(await page.locator('[data-event-id="must-not-crosslink"], [data-event-id="must-not-leak"]').count(), 0);
      const links = await weekend.getByRole("link").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("href")));
      assert.deepEqual(links, ["/decision-inbox#campaign-campaign_alpha", "/decision-inbox#campaign-campaign_beta"]);
      const marker = page.getByTestId("kline-research-marker");
      const target = await marker.getAttribute("href");
      await marker.focus(); await page.keyboard.press("Enter");
      assert.equal(await page.evaluate(() => document.activeElement?.id), target.slice(1), "keyboard marker targets matching visible text group");
      const evidenceRow = page.locator('[data-event-id="000001-exact"]');
      assert.match(await evidenceRow.innerText(), /来源日期（非有效时间）/);
      assert.equal(await evidenceRow.getByRole("link").getAttribute("href"), "/evidence/000001-exact");
      const chart = page.getByTestId("research-kline-chart");
      await chart.evaluate((node) => node.scrollIntoView({ block: "start" }));
      assert.equal(await chart.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true, "chart/list must fit viewport");
      if (process.env.E2E_KLINE_RESEARCH_SCREENSHOT_DIR) {
        await mkdir(process.env.E2E_KLINE_RESEARCH_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.E2E_KLINE_RESEARCH_SCREENSHOT_DIR, `kline-research-synthetic-${width}.png`), fullPage: false });
      }
      await evidenceRow.getByRole("link").focus(); await page.keyboard.press("Enter");
      await page.waitForURL("**/evidence/000001-exact");
      await page.getByText("合成证据 000001-exact", { exact: true }).waitFor();
    }
    // A held old-stock reply must not survive hide/show or a real query switch.
    chartPhase = false;
    await page.goto(`${baseUrl}/stock-data?code=000001`, { waitUntil: "domcontentloaded" });
    await waitForStockHeader(page, "000001", "平安银行");
    await page.getByTestId("research-event-calendar").getByTestId("research-event-row").first().waitFor();
    await openTab(page, "market"); chartPhase = true; await expandKline(page);
    hold = true;
    await page.getByRole("button", { name: "显示研究事件", exact: true }).click();
    await page.locator('[data-event-id="000001-exact"]').waitFor();
    assert.ok(release, "calendar response is held before switching stock");
    await fillCode(page, "000002"); await clickQuery(page);
    await waitForStockHeader(page, "000002", "万科A"); await openTab(page, "market"); await expandKline(page);
    await page.getByRole("button", { name: "显示研究事件", exact: true }).waitFor();
    assert.equal(await page.getByTestId("kline-research-list").count(), 0);
    release(); release = null;
    await page.getByRole("button", { name: "显示研究事件", exact: true }).click();
    await page.locator('[data-event-id="000002-weekend"]').waitFor();
    assert.equal(await page.locator('[data-event-id^="000001-"]').count(), 0);
    calendarUnavailable = true;
    await page.getByRole("button", { name: "重新读取研究事件", exact: true }).click();
    await page.getByText(/日历状态：UNAVAILABLE/).waitFor();
    assert.equal(await page.locator('[data-event-id="000002-weekend"]').count(), 0);
    await page.locator('[data-event-id="000002-exact"]').waitFor();
    assert.equal(await page.locator('[data-event-id="000002-exact"]').count(), 1);
    assert.equal(await page.getByTestId("kline-candle").count(), 5);
    await page.getByRole("button", { name: "隐藏研究事件", exact: true }).click();
    assert.equal(await page.getByTestId("kline-research-marker").count(), 0);
    calendarUnavailable = false;
    await page.getByRole("button", { name: "显示研究事件", exact: true }).click();
    await page.locator('[data-event-id="000002-weekend"]').waitFor();
    const chartCalls = calls.filter((call) => call.kind === "calendar" && call.surface === "chart");
    assert.ok(chartCalls.length >= 5, "all explicit chart loads/retries were observed");
    assert.ok(chartCalls.every((call) => call.from === dates[0] && call.to === dates.at(-1)), JSON.stringify(chartCalls));
    assert.ok(calls.filter((call) => call.kind === "evidence").every((call) => call.limit === "100" && call.offset === "0"));
    assert.deepEqual(writes, [], "all event linkage flows are read-only");
    console.log("PASS synthetic K-line research: 1440/390, keyboard ID navigation, gaps, bounded reads, cancellation and no writes");
  } finally {
    release?.();
    await page.unroute("**/api/**", routeHandler);
    mock.setTechnicalIndicatorsStatus("normal");
  }
}
