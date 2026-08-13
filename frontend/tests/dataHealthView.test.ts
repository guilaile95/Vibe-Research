import assert from "node:assert/strict";
import test from "node:test";

import {
  cacheDetailText,
  cacheTag,
  confirmedUnavailableCount,
  coverageText,
  degradedDetailText,
  degradedTag,
  emptySystemGuideFromItems,
  filterItems,
  freshnessLabel,
  freshnessState,
  gateAdviceLabel,
  gateAdviceState,
  isProblemSource,
  notInitializedCount,
  parseHealthSearchParams,
  presentationLabel,
  presentationState,
  requestScopeCardHint,
  requestScopeDetailDisclaimer,
  sourceTotalCount,
  statusAriaLabel,
  statusLabel,
  summaryQualityTotal,
  type DataHealthRecord,
} from "../src/lib/dataHealthView.ts";

function rec(partial: Partial<DataHealthRecord> & { source_id: string }): DataHealthRecord {
  return {
    module: "m",
    display_name: "d",
    status: "normal",
    is_stale: false,
    observed_at: null,
    last_success_at: null,
    data_trade_date: null,
    data_cutoff: null,
    stale_after_seconds: null,
    is_cached: null,
    is_degraded: null,
    coverage_current: null,
    coverage_expected: null,
    last_error_code: null,
    last_error_summary: null,
    last_error_at: null,
    blocks_advice: false,
    block_reason: null,
    detail_path: null,
    ...partial,
  };
}

test("status labels are text not color-only", () => {
  assert.equal(statusLabel("normal"), "正常");
  assert.equal(statusLabel("partial"), "部分可用");
  assert.equal(statusLabel("unavailable"), "不可用");
  assert.ok(statusAriaLabel("normal").includes("正常"));
});

test("cache and degraded tri-state", () => {
  assert.equal(cacheTag(true), "缓存结果");
  assert.equal(cacheTag(false), null);
  assert.equal(cacheTag(null), null);
  assert.equal(cacheDetailText(null), "当前来源未提供该信息");
  assert.equal(cacheDetailText(false), null);
  assert.equal(degradedTag(true), "降级结果");
  assert.equal(degradedTag(false), null);
  assert.equal(degradedDetailText(null), "当前来源未提供该信息");
  // null 不得显示为实时/未降级
  assert.notEqual(cacheDetailText(null), "实时数据");
  assert.notEqual(degradedDetailText(null), "未降级");
});

test("coverage unknown", () => {
  assert.equal(coverageText(null, null), "未提供");
  assert.equal(coverageText(0, 0), "0 / 0");
  assert.equal(coverageText(3, 5), "3 / 5");
});

test("gate states", () => {
  assert.equal(gateAdviceState(null), "not_evaluated");
  assert.equal(
    gateAdviceState(rec({ source_id: "portfolio_advice_gate", last_error_code: "SOURCE_NOT_INITIALIZED", status: "unavailable" })),
    "not_evaluated",
  );
  assert.equal(
    gateAdviceLabel(
      gateAdviceState(
        rec({
          source_id: "portfolio_advice_gate",
          status: "normal",
          blocks_advice: true,
          last_error_code: "NO_HOLDINGS",
        }),
      ),
    ),
    "当前阻止",
  );
  assert.equal(
    gateAdviceLabel(
      gateAdviceState(
        rec({
          source_id: "portfolio_advice_gate",
          status: "normal",
          blocks_advice: false,
        }),
      ),
    ),
    "允许生成",
  );
  assert.equal(
    gateAdviceState(
      rec({
        source_id: "portfolio_advice_gate",
        status: "unavailable",
        blocks_advice: false,
        last_error_code: "SOURCE_TIMEOUT",
      }),
    ),
    "runtime_failed",
  );
});

test("NO_HOLDINGS is blocked evaluation not runtime fail", () => {
  const s = gateAdviceState(
    rec({
      source_id: "portfolio_advice_gate",
      status: "normal",
      blocks_advice: true,
      last_error_code: "NO_HOLDINGS",
    }),
  );
  assert.equal(s, "blocked");
  assert.notEqual(s, "runtime_failed");
});

test("request scoped hints", () => {
  assert.equal(requestScopeCardHint("quotes"), "最近一次真实调用");
  assert.ok(
    (requestScopeDetailDisclaimer("quotes") || "").includes("不代表全部股票或板块均已验证"),
  );
  assert.equal(requestScopeCardHint("daily_review"), null);
});

test("summary quality total counts backend tri-state only", () => {
  const s = { normal: 5, partial: 2, unavailable: 4, stale: 3, not_initialized: 2 };
  assert.equal(summaryQualityTotal(s), 11);
});

test("R1: confirmed unavailable excludes not-initialized; counts are item-derived", () => {
  // 8 not_initialized + 1 true failure + 其余正常（验收 G/H）
  const items: DataHealthRecord[] = [];
  for (let i = 0; i < 8; i++) {
    items.push(rec({
      source_id: `s${i}`,
      status: "unavailable",
      last_error_code: "SOURCE_NOT_INITIALIZED",
    }));
  }
  items.push(rec({
    source_id: "failure",
    status: "unavailable",
    last_error_code: "SOURCE_UNAVAILABLE",
  }));
  items.push(rec({ source_id: "ok", status: "normal" }));
  // unavailable = 1（真实失败），not initialized = 8
  assert.equal(confirmedUnavailableCount(items), 1);
  assert.equal(notInitializedCount(items), 8);
  // source total 动态派生（10，不是 hardcoded 11/15）
  assert.equal(sourceTotalCount(items), 10);
  assert.equal(emptySystemGuideFromItems(items), false);
});

test("R1: empty-system guide only when every item is not-initialized (dynamic)", () => {
  const all = [1, 2, 3].map((i) =>
    rec({
      source_id: `s${i}`,
      status: "unavailable",
      last_error_code: "SOURCE_NOT_INITIALIZED",
    }),
  );
  assert.equal(emptySystemGuideFromItems(all), true);
  assert.equal(emptySystemGuideFromItems([]), false);
});

test("url filter parse cleans invalid", () => {
  const sp = new URLSearchParams("status=bad&is_stale=maybe&module=a,b");
  const f = parseHealthSearchParams(sp);
  assert.equal(f.status, null);
  assert.equal(f.is_stale, null);
  assert.equal(f.module, null);
  const ok = parseHealthSearchParams(new URLSearchParams("status=partial&is_stale=true"));
  assert.equal(ok.status, "partial");
  assert.equal(ok.is_stale, true);
});

test("filter items", () => {
  const items = [
    rec({ source_id: "a", status: "normal", is_stale: true }),
    rec({ source_id: "b", status: "partial", is_stale: false }),
  ];
  assert.equal(filterItems(items, { status: "partial" }).length, 1);
  assert.equal(filterItems(items, { is_stale: true }).length, 1);
});

// ---------------------------------------------------------------------------
// P0-DS1：presentation 语义（未初始化/未检测 ≠ 不可用）与 freshness 独立
// ---------------------------------------------------------------------------

test("presentationState: SOURCE_NOT_INITIALIZED is not_initialized (never unavailable)", () => {
  assert.equal(
    presentationState(rec({ source_id: "quotes", status: "unavailable", last_error_code: "SOURCE_NOT_INITIALIZED" })),
    "not_initialized",
  );
  assert.equal(presentationState(rec({ source_id: "quotes" })), "normal");
  assert.equal(presentationState(rec({ source_id: "quotes", status: "partial" })), "partial");
  assert.equal(
    presentationState(rec({ source_id: "quotes", status: "unavailable", last_error_code: "SOURCE_UNAVAILABLE" })),
    "unavailable",
  );
  assert.equal(presentationState(null), "not_initialized");
});

test("presentationLabel distinguishes not_initialized from unavailable", () => {
  assert.equal(presentationLabel("not_initialized"), "未初始化");
  assert.equal(presentationLabel("unavailable"), "不可用");
  assert.notEqual(presentationLabel("not_initialized"), presentationLabel("unavailable"));
});

test("freshnessState: independent of quality status", () => {
  // 未初始化 → 新鲜度未知
  assert.equal(
    freshnessState(rec({ source_id: "q", status: "unavailable", last_error_code: "SOURCE_NOT_INITIALIZED" })),
    "UNKNOWN",
  );
  // 陈旧
  assert.equal(freshnessState(rec({ source_id: "q", status: "normal", is_stale: true })), "STALE");
  // 新鲜（质量正常）
  assert.equal(freshnessState(rec({ source_id: "q", status: "normal", is_stale: false })), "FRESH");
  // 新鲜（质量部分可用但数据不陈旧）
  assert.equal(freshnessState(rec({ source_id: "q", status: "partial", is_stale: false })), "FRESH");
  // stale 信号缺失 → 未知
  assert.equal(freshnessState(rec({ source_id: "q", is_stale: null })), "UNKNOWN");
  assert.equal(freshnessState(null), "UNKNOWN");
});

test("freshnessLabel maps FRESH/STALE/UNKNOWN", () => {
  assert.equal(freshnessLabel("FRESH"), "数据新鲜");
  assert.equal(freshnessLabel("STALE"), "数据陈旧");
  assert.equal(freshnessLabel("UNKNOWN"), "新鲜度未知");
});

test("isProblemSource excludes not-initialized (unobserved is not a problem)", () => {
  assert.equal(
    isProblemSource(rec({ source_id: "q", status: "unavailable", last_error_code: "SOURCE_NOT_INITIALIZED" })),
    false,
  );
  assert.equal(
    isProblemSource(rec({ source_id: "q", status: "unavailable", last_error_code: "SOURCE_UNAVAILABLE" })),
    true,
  );
  assert.equal(isProblemSource(rec({ source_id: "q", status: "partial" })), true);
  assert.equal(isProblemSource(rec({ source_id: "q", status: "normal", is_stale: true })), true);
});
