import assert from "node:assert/strict";
import test from "node:test";

import {
  formatIndicator,
  formatPrice,
  formatVolumeRatio,
  indicatorErrorMessage,
  indicatorStatusLabel,
  limitationLines,
  rsiZoneLabel,
  triggerLines,
} from "../src/lib/technicalIndicatorsView.ts";

test("indicatorStatusLabel tri-state mapping", () => {
  assert.equal(indicatorStatusLabel("normal").text, "正常");
  assert.ok(indicatorStatusLabel("normal").cls.includes("emerald"));

  assert.equal(indicatorStatusLabel("partial").text, "部分可用");
  assert.ok(indicatorStatusLabel("partial").cls.includes("amber"));

  assert.equal(indicatorStatusLabel("unavailable").text, "不可用");
  assert.ok(indicatorStatusLabel("unavailable").cls.includes("muted-foreground"));

  // 未知 / null 统一兜底为「不可用」
  assert.equal(indicatorStatusLabel("garbage").text, "不可用");
  assert.equal(indicatorStatusLabel(null).text, "不可用");
  assert.equal(indicatorStatusLabel(undefined).text, "不可用");
});

test("null / NaN render as '—' and NEVER produce '0' or '0.00'", () => {
  assert.equal(formatPrice(null), "—");
  assert.equal(formatPrice(undefined), "—");
  assert.equal(formatPrice(Number.NaN), "—");
  assert.notEqual(formatPrice(null), "0");
  assert.notEqual(formatPrice(null), "0.00");

  assert.equal(formatIndicator(null), "—");
  assert.equal(formatIndicator(undefined, 3), "—");
  assert.notEqual(formatIndicator(undefined), "0.00");

  assert.equal(formatVolumeRatio(null), "—");
  assert.notEqual(formatVolumeRatio(undefined), "0.00x");
});

test("formatPrice keeps 2 decimals, formatIndicator respects digits", () => {
  assert.equal(formatPrice(12.3456), "12.35");
  assert.equal(formatPrice(12), "12.00");
  assert.equal(formatIndicator(3.14159, 3), "3.142");
  assert.equal(formatIndicator(3.14159), "3.14");
});

test("formatVolumeRatio appends 'x' suffix with 2 decimals", () => {
  assert.equal(formatVolumeRatio(2.345), "2.35x");
  assert.equal(formatVolumeRatio(1), "1.00x");
  assert.equal(formatVolumeRatio(0.5), "0.50x");
});

test("rsiZoneLabel zones: >=70 high / <=30 low / between neutral / null", () => {
  assert.equal(rsiZoneLabel(70).text, "高位区间");
  assert.equal(rsiZoneLabel(85).text, "高位区间");
  assert.ok(rsiZoneLabel(85).cls.includes("danger"));

  assert.equal(rsiZoneLabel(30).text, "低位区间");
  assert.equal(rsiZoneLabel(12).text, "低位区间");
  assert.ok(rsiZoneLabel(12).cls.includes("success"));

  assert.equal(rsiZoneLabel(50).text, "中性区间");
  assert.equal(rsiZoneLabel(31).text, "中性区间");
  assert.equal(rsiZoneLabel(69).text, "中性区间");

  assert.equal(rsiZoneLabel(null).text, "—");
  assert.equal(rsiZoneLabel(undefined).text, "—");
  assert.ok(rsiZoneLabel(undefined).cls.includes("muted-foreground"));
});

test("triggerLines map triggers to messages and ignore empty", () => {
  const lines = triggerLines([
    { type: "sma_golden_cross", message: "检测到 SMA5 上穿 SMA10 的金叉", value: 1 },
    { type: "volume_spike", message: "5 日平均成交量超过 20 日平均成交量的 2 倍", value: 2.35 },
  ]);
  assert.deepEqual(lines, [
    "检测到 SMA5 上穿 SMA10 的金叉",
    "5 日平均成交量超过 20 日平均成交量的 2 倍",
  ]);

  assert.deepEqual(triggerLines([]), []);
  assert.deepEqual(triggerLines(null), []);
  assert.deepEqual(triggerLines(undefined), []);
});

test("limitationLines map limitations to readable text", () => {
  const lines = limitationLines({
    limitations: [
      { field: "macd", detail: "样本不足，仅返回部分窗口" },
      { field: "rsi14", detail: "数据源暂未就绪" },
    ],
  });
  assert.deepEqual(lines, [
    "macd: 样本不足，仅返回部分窗口",
    "rsi14: 数据源暂未就绪",
  ]);

  assert.deepEqual(limitationLines(null), []);
  assert.deepEqual(limitationLines(undefined), []);
  assert.deepEqual(limitationLines({ limitations: [] }), []);
});

test("indicatorErrorMessage three branches", () => {
  assert.equal(indicatorErrorMessage(0), "后端连接不可用");
  assert.equal(indicatorErrorMessage(501), "依赖未就绪");
  assert.equal(indicatorErrorMessage(999), "技术指标暂不可用");
  assert.equal(indicatorErrorMessage(undefined), "技术指标暂不可用");
});
