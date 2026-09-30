import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { FundFlowRow, Report } from "../src/lib/api/types.ts";
import {
  type EvidenceState, loadEvidenceSource, resolveEvidence, evidenceStatusText,
  resolveEvidenceList, evidenceListStatusText, reportEvidenceContext,
  announcementEvidenceContext, quoteEvidenceContext, summarizeStockFundFlow,
} from "../src/lib/stockDataEvidence.ts";

const report: Report = { title: "Synthetic report", publishDate: "2026-09-01", orgSName: "Synthetic institution", pdfUrl: "https://example.com/report.pdf" };

test("evidence sources distinguish pending, successful empty, populated, and rejected states", async () => {
  const empty = await resolveEvidenceList(Promise.resolve<Report[]>([]), "研报数据暂不可用");
  const success = await resolveEvidenceList(Promise.resolve([report]), "研报数据暂不可用");
  const failure = await resolveEvidenceList(Promise.reject(new Error("private provider detail")), "研报数据暂不可用");
  assert.equal(empty.status, "success");
  assert.equal(success.status, "success");
  assert.equal(failure.status, "error");
  assert.match(reportEvidenceContext(empty), /本次接口返回 0 条/);
  assert.match(reportEvidenceContext(success), /Synthetic report/);
  assert.match(reportEvidenceContext(failure), /暂不可用；不能据此判断没有记录/);
  assert.doesNotMatch(reportEvidenceContext(failure), /private provider detail|近期研报：无|查询成功/);
  assert.match(evidenceListStatusText({ status: "loading", data: [] }), /加载中/);
  assert.match(evidenceListStatusText({ status: "idle", data: [] }), /尚未查询/);
});

test("report and announcement context retain supplied source, date and institution", () => {
  const context = reportEvidenceContext({ status: "success", data: [report] });
  for (const value of [report.publishDate, report.orgSName, report.pdfUrl!]) assert.ok(context.includes(value));
  const announcement = announcementEvidenceContext({ status: "success", data: [{ title: "Synthetic notice", date: "2026-08-31", type: "notice", url: "https://example.com/notice" }] });
  assert.match(announcement, /2026-08-31/);
  assert.match(announcement, /https:\/\/example.com\/notice/);
  assert.match(announcementEvidenceContext({ status: "error", data: [], error: "公告数据暂不可用" }), /不能据此判断没有记录/);
  assert.match(announcementEvidenceContext({ status: "loading", data: [] }), /加载中/);
  assert.match(announcementEvidenceContext({ status: "success", data: [] }), /本次接口返回 0 条/);
});

test("quote provenance never borrows a composite valuation date", () => {
  assert.match(quoteEvidenceContext({ quote_source: "tencent", quote_data_time: "2026-09-01T15:00:00+08:00", quote_trade_date: "2026-09-01" }), /tencent.*2026-09-01T15:00:00\+08:00.*仅适用于报价/);
  assert.match(quoteEvidenceContext({}), /报价时间 未知.*报价交易日 未知/);
});

const flow = (date: string, main_net: number | null): FundFlowRow => ({ date, main_net, small_net: null, mid_net: null, large_net: null, super_net: null });
test("fundflow preserves actual zero and rejects incomplete or nonfinite totals", () => {
  assert.deepEqual(summarizeStockFundFlow([flow("2026-09-01", 0)]), { observed: 1, valid: 1, total: 0, latestDate: "2026-09-01" });
  for (const missing of [null, NaN, Infinity]) {
    const result = summarizeStockFundFlow([flow("2026-09-01", 10), flow("2026-09-02", missing)]);
    assert.equal(result.total, null);
    assert.equal(result.valid, 1);
    assert.equal(result.observed, 2);
  }
  assert.equal(summarizeStockFundFlow([]).total, null);
});

test("fundflow uses latest observations without mutating or filling missing dates", () => {
  const rows = Array.from({ length: 21 }, (_, i) => flow(`2026-09-${String(i + 1).padStart(2, "0")}`, i + 1));
  const result = summarizeStockFundFlow(rows);
  assert.equal(result.observed, 20);
  assert.equal(result.total, 230);
  assert.equal(result.latestDate, "2026-09-21");
  assert.equal(rows[0].date, "2026-09-01");
});

test("StockData wires guarded independent source requests to both UI and AI context", () => {
  const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
  assert.match(source, /rid === runIdRef\.current\) set\(v\)/);
  assert.match(source, /resolveEvidenceList\(api\.reports\(c\).*\.then\(ok\(setReportResult\)\)/);
  assert.match(source, /resolveEvidenceList\(api\.announcements\(c\).*\.then\(ok\(setAnnouncementResult\)\)/);
  assert.match(source, /reportEvidenceContext\(reportResult\)/);
  assert.match(source, /announcementEvidenceContext\(announcementResult\)/);
  assert.match(source, /data-source-state=\{reportResult.status\}/);
  assert.match(source, /data-source-state=\{announcementResult.status\}/);
  assert.equal((source.match(/quoteEvidenceContext\(val\)/g) || []).length, 2);
  assert.match(source, /fundFlowSummary.total === null/);
  assert.doesNotMatch(source, /api\.(reports|announcements)\(c\)\.catch\(\(\) => \[\]\)/);
});


function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test("secondary request handler emits loading then an honest terminal state, with sanitized 501 distinction", async () => {
  for (const outcome of ["populated", "empty", "failure", "unsupported", "syncFailure"] as const) {
    const states: EvidenceState<number[]>[] = [];
    await loadEvidenceSource(() => {
      if (outcome === "syncFailure") throw new Error("private synchronous detail");
      if (outcome === "failure") return Promise.reject(new Error("https://private-provider/key=secret"));
      if (outcome === "unsupported") return Promise.reject({ status: 501, message: "private dependency location" });
      return Promise.resolve(outcome === "empty" ? [] : [0]);
    }, [], "数据暂不可用", (state) => states.push(state), () => true);
    assert.equal(states.length, 2);
    assert.equal(states[0].status, "loading");
    const final = states[1];
    assert.equal(final.status, outcome === "unsupported" ? "unsupported" : outcome === "failure" || outcome === "syncFailure" ? "error" : "success");
    assert.doesNotMatch(JSON.stringify(states), /private|key=secret/);
    if (outcome === "populated") assert.deepEqual(final.data, [0]);
    if (outcome === "empty") assert.match(evidenceStatusText(final), /本次接口返回 0 条.*不能排除上游缺失/);
    if (outcome === "unsupported") assert.match(evidenceStatusText(final), /不支持.*501/);
  }
});

test("object source emptiness is based on its records, never truthiness of zero metrics", async () => {
  const isEmpty = (data: { metrics: { percentile?: number } } | null) => data === null || data.metrics.percentile === undefined;
  const zero = await resolveEvidence(Promise.resolve({ metrics: { percentile: 0 } }), null, "分位暂不可用", isEmpty);
  const empty = await resolveEvidence(Promise.resolve({ metrics: {} }), null, "分位暂不可用", isEmpty);
  assert.equal(zero.status, "success");
  assert.match(evidenceStatusText(zero), /已返回数据/);
  assert.match(evidenceStatusText(empty), /未返回可展示记录/);
});

test("independent sources settle without waiting for another source, including failure", async () => {
  const slow = deferred<number[]>();
  const slowStates: EvidenceState<number[]>[] = [];
  const fastStates: EvidenceState<number[]>[] = [];
  const slowTask = loadEvidenceSource(() => slow.promise, [], "slow unavailable", (state) => slowStates.push(state), () => true);
  await loadEvidenceSource(() => Promise.resolve([0]), [], "fast unavailable", (state) => fastStates.push(state), () => true);
  assert.deepEqual(slowStates.map((state) => state.status), ["loading"]);
  assert.deepEqual(fastStates.map((state) => state.status), ["loading", "success"]);
  slow.reject(new Error("private slow failure"));
  await slowTask;
  assert.equal(slowStates[1].status, "error");
  assert.deepEqual(fastStates[1].data, [0]);
});

test("switching stocks rejects both stale successes and stale errors without replacing current data", async () => {
  for (const rejected of [false, true]) {
    let runId = 1;
    const old = deferred<number[]>();
    const committed: EvidenceState<number[]>[] = [];
    const commit = (state: EvidenceState<number[]>) => committed.push(state);
    const oldTask = loadEvidenceSource(() => old.promise, [], "old unavailable", commit, () => runId === 1);
    runId = 2;
    await loadEvidenceSource(() => Promise.resolve([2]), [], "new unavailable", commit, () => runId === 2);
    if (rejected) old.reject(new Error("old failure"));
    else old.resolve([1]);
    await oldTask;
    assert.deepEqual(committed.map((state) => state.status), ["loading", "loading", "success"]);
    assert.deepEqual(committed.at(-1)?.data, [2]);
  }
});

test("an already obsolete source request neither starts nor clears the latest state", async () => {
  let calls = 0;
  await loadEvidenceSource(() => { calls++; return Promise.resolve([]); }, [], "unavailable", () => { calls++; }, () => false);
  assert.equal(calls, 0);
});

test("each secondary source wires an independently guarded request and visible status", () => {
  const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
  for (const [method, setter, state] of [
    ["margin", "Margin", "margin"], ["holders", "Holders", "holders"], ["fundFlow", "FundFlow", "fundFlow"],
    ["dividend", "Dividend", "dividend"], ["blockTrade", "BlockT", "blockT"], ["dragonTiger", "Dt", "dt"],
    ["lockup", "Lockup", "lockup"], ["blocks", "Blocks", "blocks"], ["hotConcepts", "HotCon", "hotCon"],
    ["investorQa", "Qa", "qa"], ["percentile", "Pctl", "pctl"], ["news", "News", "news"],
  ]) {
    const request = source.split("\n").find((line) => line.includes(`loadEvidenceSource(() => api.${method}(c)`));
    assert.ok(request, method);
    assert.ok(request.includes(`set${setter}Result, () => rid === runIdRef.current`), method);
    assert.ok(source.includes(`state={${state}Result}`), state);
    assert.ok(source.includes(`set${setter}Result({ status: "idle"`), `${state} reset`);
  }
  assert.ok(source.includes("evidenceStatusText(pctlResult)"));
  assert.doesNotMatch(source, /api\.(news|percentile)\(c\)\.catch/);
  assert.doesNotMatch(source, /暂无新闻|未来 90 天无待解禁/);
});
