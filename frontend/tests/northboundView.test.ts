import test from "node:test";
import assert from "node:assert/strict";
import {
  fetchedAtText,
  formatCount,
  formatTurnoverMn,
  formatTurnoverYuan,
  limitationLines,
  northboundErrorMessage,
  northboundFreshnessText,
  northboundStatusLabel,
} from "../src/lib/northboundView.ts";

test("northboundStatusLabel handles normal, partial, and unavailable states", () => {
  const normal = northboundStatusLabel("normal");
  assert.equal(normal.text, "正常");
  assert.ok(normal.cls.includes("emerald"));

  const partial = northboundStatusLabel("partial");
  assert.equal(partial.text, "部分缺失");
  assert.ok(partial.cls.includes("amber"));

  const unavailable = northboundStatusLabel("unavailable");
  assert.equal(unavailable.text, "不可用");

  const unknown = northboundStatusLabel("random");
  assert.equal(unknown.text, "不可用");
});

test("null and undefined inputs return '—' and NEVER produce '0' or '0.00'", () => {
  assert.equal(formatTurnoverMn(null), "—");
  assert.equal(formatTurnoverMn(undefined), "—");
  assert.equal(formatTurnoverMn(Number.NaN), "—");
  assert.notEqual(formatTurnoverMn(null), "0");
  assert.notEqual(formatTurnoverMn(null), "0.00");

  assert.equal(formatTurnoverYuan(null), "—");
  assert.equal(formatTurnoverYuan(undefined), "—");
  assert.equal(formatTurnoverYuan(Number.NaN), "—");
  assert.notEqual(formatTurnoverYuan(null), "0");
  assert.notEqual(formatTurnoverYuan(null), "0.00");

  assert.equal(formatCount(null), "—");
  assert.equal(formatCount(undefined), "—");
  assert.equal(formatCount(Number.NaN), "—");
  assert.notEqual(formatCount(null), "0");
});

test("formatTurnoverMn converts million RMB to 亿 correctly", () => {
  assert.equal(formatTurnoverMn(159631.57), "1596.32 亿");
  assert.equal(formatTurnoverMn(2811.9), "28.12 亿");
  assert.equal(formatTurnoverMn(100), "1.00 亿");
  assert.equal(formatTurnoverMn(50), "0.50 亿");
});

test("formatTurnoverYuan converts Yuan to 亿/万 automatically", () => {
  assert.equal(formatTurnoverYuan(125_000_000_000), "1250.00 亿");
  assert.equal(formatTurnoverYuan(15_963_157_000), "159.63 亿");
  assert.equal(formatTurnoverYuan(28_119_000), "2811.90 万");
  assert.equal(formatTurnoverYuan(5_000), "5000 元");
});

test("formatCount formats integer with thousands separator", () => {
  assert.equal(formatCount(1234567), "1,234,567");
  assert.equal(formatCount(890), "890");
});

test("northboundFreshnessText formats trade_date and stale status", () => {
  assert.equal(
    northboundFreshnessText({ trade_date: "2026-07-29", is_stale: false }),
    "交易日 2026-07-29",
  );
  assert.equal(
    northboundFreshnessText({ trade_date: "2026-07-29", is_stale: true }),
    "交易日 2026-07-29 · 数据陈旧",
  );
  assert.equal(
    northboundFreshnessText({ trade_date: null, is_stale: false }),
    "交易日未知",
  );
  assert.equal(
    northboundFreshnessText({ trade_date: null, is_stale: true }),
    "交易日未知 · 数据陈旧",
  );
  assert.equal(northboundFreshnessText(null), "交易日未知");
});

test("fetchedAtText slices ISO date string or returns fallback", () => {
  assert.equal(fetchedAtText("2026-07-30T15:30:00.123Z"), "2026-07-30 15:30:00");
  assert.equal(fetchedAtText("invalid"), "—");
  assert.equal(fetchedAtText(null), "—");
  assert.equal(fetchedAtText(""), "—");
});

test("limitationLines formats limitations safely", () => {
  const env = {
    limitations: [
      { field: "net_buy_mn", reason_code: "SOURCE_OMITTED", detail: "HKEX no longer publishes net buy" },
      { field: "active_stocks.net_buy_yuan", reason_code: "SOURCE_OMITTED", detail: "Active stocks net buy unavailable" },
    ],
  };
  const lines = limitationLines(env);
  assert.equal(lines.length, 2);
  assert.equal(lines[0], "net_buy_mn: HKEX no longer publishes net buy");
  assert.equal(lines[1], "active_stocks.net_buy_yuan: Active stocks net buy unavailable");

  assert.deepEqual(limitationLines(null), []);
  assert.deepEqual(limitationLines({ limitations: [] }), []);
});

test("northboundErrorMessage maps HTTP status codes correctly", () => {
  assert.equal(northboundErrorMessage(0), "后端连接不可用");
  assert.equal(northboundErrorMessage(501), "依赖未就绪");
  assert.equal(northboundErrorMessage(500), "北向资金暂不可用");
  assert.equal(northboundErrorMessage(404), "北向资金暂不可用");
  assert.equal(northboundErrorMessage(undefined), "北向资金暂不可用");
});
