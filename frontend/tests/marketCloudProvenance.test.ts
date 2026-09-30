import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { marketObservationLabels } from "../src/lib/dataHealthView.ts";
import type { MarketCloudEnvelope } from "../src/lib/marketCloud.ts";

const legacy: MarketCloudEnvelope = {
  status: "partial", data: null, warnings: ["缺字段"], is_stale: false,
  fetched_at: "2026-09-27 09:29:00", source: "eastmoney_push2",
};

test("cache, stale and quality are independent; full fetch date is retained", () => {
  const cached = { ...legacy, is_cached: true, market_time_unknown: true };
  const labels = marketObservationLabels(cached);
  assert.ok(labels.includes("缓存结果"));
  assert.ok(!labels.includes("数据陈旧"));
  assert.ok(labels.includes("来源：东方财富"));
  assert.ok(labels.includes("行情时间未知"));
  assert.ok(labels.includes("抓取完成：2026-09-27 09:29:00（北京时间）"));
  assert.equal(cached.status, "partial");
  assert.ok(marketObservationLabels({ ...cached, is_stale: true }).includes("数据陈旧"));
  assert.ok(marketObservationLabels({ ...legacy, status: "stale" }).includes("数据陈旧"));
});

test("legacy and null provenance never invent quote time or cache state", () => {
  assert.ok(marketObservationLabels(legacy).includes("行情时间未知"));
  assert.ok(!marketObservationLabels(legacy).includes("缓存结果"));
  assert.deepEqual(marketObservationLabels(null), []);
  assert.deepEqual(marketObservationLabels(undefined), []);
  assert.deepEqual(marketObservationLabels({ ...legacy, status: "unavailable" }), []);
  assert.deepEqual(marketObservationLabels({status: "normal"}), ["来源：未知", "抓取时间未知", "行情时间未知"]);
  const withTime = { ...legacy, trade_date: "2026-09-27", data_time: "09:28:00" };
  assert.ok(marketObservationLabels(withTime).includes("行情时间：2026-09-27 09:28:00"));
  assert.ok(marketObservationLabels({ ...withTime, market_time_unknown: true }).includes("行情时间未知"));
  assert.ok(marketObservationLabels({ ...legacy, market_time_unknown: false }).includes("行情时间未知"));
});

test("MarketCloud wires provenance and suppresses previous request metadata while loading or failed", () => {
  const source = readFileSync(new URL("../src/components/market/MarketCloud.tsx", import.meta.url), "utf8");
  assert.ok(source.includes("!loading && !error && marketObservationLabels(data).map"));
  assert.ok(source.includes('status === "partial"'));
  assert.ok(source.includes("抓取完成（北京时间）"));
  assert.ok(!source.includes("数据更新："));
  assert.ok(!source.includes("fetched_at.slice"));
});
