import assert from "node:assert/strict";
import test from "node:test";
import {
  deriveMarketIntelStatus,
  knownCountText,
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
