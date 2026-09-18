import assert from "node:assert/strict";
import test from "node:test";
import {
  deriveMarketIntelStatus,
  knownCountText,
  knownHistoryItemCount,
  sourceHealthText,
} from "../src/lib/marketIntelStatus.ts";

const base = {
  loading: false,
  hasNativeData: true,
  hasRadarData: true,
  nativeStatus: "normal" as const,
  nativeError: null,
  radarError: null,
  radarFailedSources: 0,
};

test("market intel status isolates either source failure", () => {
  assert.equal(deriveMarketIntelStatus({ ...base, loading: true, hasNativeData: false, hasRadarData: false }), "loading");
  assert.equal(deriveMarketIntelStatus({ ...base, hasNativeData: false, hasRadarData: false }), "unavailable");
  assert.equal(deriveMarketIntelStatus(base), "normal");
  assert.equal(deriveMarketIntelStatus({ ...base, nativeStatus: "stale" }), "stale");
  assert.equal(deriveMarketIntelStatus({ ...base, nativeError: "公开资讯失败" }), "partial");
  assert.equal(deriveMarketIntelStatus({ ...base, radarError: "赛道摘要失败" }), "partial");
  assert.equal(deriveMarketIntelStatus({ ...base, radarFailedSources: 1 }), "partial");
  assert.equal(deriveMarketIntelStatus({ ...base, hasNativeData: false }), "partial");
  assert.equal(deriveMarketIntelStatus({ ...base, hasRadarData: false }), "partial");
});

test("known counts stay real, including a verified zero", () => {
  assert.equal(knownCountText(1), "1");
  assert.equal(knownCountText(0), "0");
  assert.equal(knownCountText(42), "42");
  assert.equal(sourceHealthText({ healthy: 4, total: 4 }), "4/4 正常");
  assert.equal(sourceHealthText({ healthy: 0, total: 0 }), "0/0 正常");
});

test("unread authority renders unknown instead of a fabricated zero", () => {
  for (const value of [undefined, null, Number.NaN, Number.POSITIVE_INFINITY, "3"]) {
    assert.equal(knownCountText(value), "未知");
  }
  // runtime 未读取 → sources 缺失；runtime 存在但 sources 缺失
  assert.equal(sourceHealthText(undefined), "未知");
  assert.equal(sourceHealthText(null), "未知");
  assert.equal(sourceHealthText({}), "未知");
  assert.equal(sourceHealthText({ healthy: 3 }), "未知");
  assert.equal(sourceHealthText({ total: 3 }), "未知");
  assert.notEqual(sourceHealthText(undefined), "0/0 正常");
});

test("a store-reported count wins over the items authority total", () => {
  assert.equal(knownHistoryItemCount({ store: { readable: true, item_count: 7 }, items: { status: "normal", total: 7 } }), 7);
  assert.equal(knownHistoryItemCount({ store: { readable: true, item_count: 0 }, items: { status: "normal", total: 0 } }), 0);
  // store 未自报计数时退回 items.total，但只在 items 权威没有自报不可用时
  assert.equal(knownHistoryItemCount({ store: { readable: true }, items: { status: "normal", total: 12 } }), 12);
  assert.equal(knownHistoryItemCount({ items: { status: "partial", total: 3 } }), 3);
});

test("store failure must not surface the router's hardcoded zero as a count", () => {
  // 后端 store 读取失败分支返回 HTTP 200 + items=[] + total=0，0 不是已核实的计数
  assert.equal(
    knownHistoryItemCount({ store: { readable: false }, items: { status: "unavailable", total: 0 } }),
    null,
  );
  assert.equal(knownHistoryItemCount({ items: { status: "unavailable", total: 0 } }), null);
  // 即使 items 权威自报不可用，store 直接读到的计数仍然是真实的
  assert.equal(
    knownHistoryItemCount({ store: { readable: true, item_count: 9 }, items: { status: "unavailable", total: 0 } }),
    9,
  );
  assert.equal(knownCountText(knownHistoryItemCount({ store: {}, items: {} })), "未知");
});
