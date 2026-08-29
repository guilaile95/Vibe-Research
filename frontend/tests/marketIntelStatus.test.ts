import assert from "node:assert/strict";
import test from "node:test";
import { deriveMarketIntelStatus } from "../src/lib/marketIntelStatus.ts";

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
