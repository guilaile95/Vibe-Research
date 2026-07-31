import assert from "node:assert/strict";
import test from "node:test";

import {
  confidenceText,
  coverageText,
  fetchedAtText,
  limitationLines,
  riskLevel,
  riskScoreText,
  topRiskDirectionLabel,
  topRiskErrorMessage,
  topRiskFreshnessText,
  topRiskStatusLabel,
  traceArchiveStatusText,
} from "../src/lib/topRiskView.ts";

function rec(partial: Record<string, unknown> = {}): Record<string, unknown> {
  return { status: "normal", ...partial };
}

test("topRiskStatusLabel: normal", () => {
  const r = topRiskStatusLabel("normal");
  assert.equal(r.text, "正常");
  assert.ok(r.cls.includes("emerald"));
});

test("topRiskStatusLabel: partial", () => {
  const r = topRiskStatusLabel("partial");
  assert.equal(r.text, "部分缺失");
  assert.ok(r.cls.includes("amber"));
});

test("topRiskStatusLabel: unavailable", () => {
  const r = topRiskStatusLabel("unavailable");
  assert.equal(r.text, "不可用");
});

test("topRiskStatusLabel: null → unavailable fallback", () => {
  const r = topRiskStatusLabel(null);
  assert.equal(r.text, "不可用");
});

test("topRiskStatusLabel: undefined → unavailable fallback", () => {
  const r = topRiskStatusLabel(undefined);
  assert.equal(r.text, "不可用");
});

test("riskLevel: high risk (≥70)", () => {
  const r = riskLevel(85);
  assert.equal(r.text, "高风险");
  assert.ok(r.cls.includes("destructive"));
});

test("riskLevel: medium risk (40-69)", () => {
  const r = riskLevel(50);
  assert.equal(r.text, "中风险");
});

test("riskLevel: low risk (<40)", () => {
  const r = riskLevel(20);
  assert.equal(r.text, "低风险");
});

test("riskLevel: null → —", () => {
  const r = riskLevel(null);
  assert.equal(r.text, "—");
});

test("riskLevel: NaN → —", () => {
  const r = riskLevel(Number.NaN);
  assert.equal(r.text, "—");
});

test("riskScoreText: null → —", () => {
  assert.equal(riskScoreText(null), "—");
});

test("riskScoreText: value → rounded string", () => {
  assert.equal(riskScoreText(75.6), "76");
});

test("confidenceText: null → —", () => {
  assert.equal(confidenceText(null), "—");
});

test("confidenceText: null → — (undefined)", () => {
  assert.equal(confidenceText(undefined), "—");
});

test("confidenceText: value → percentage", () => {
  assert.equal(confidenceText(85), "85%");
});

test("coverageText: null → —", () => {
  assert.equal(coverageText(null), "—");
});

test("coverageText: null total → —", () => {
  assert.equal(coverageText({ completed: 0, total: null, ratio: 0 } as never), "—");
});

test("coverageText: valid", () => {
  assert.equal(coverageText({ completed: 3, total: 4, ratio: 0.75 }), "3/4（75%）");
});

test("coverageText: missing ratio → — placeholder", () => {
  assert.equal(coverageText({ completed: 2, total: 4, ratio: null } as never), "2/4（—）");
});

test("traceArchiveStatusText: archived", () => {
  const r = traceArchiveStatusText("archived");
  assert.equal(r.text, "已归档");
  assert.ok(r.cls.includes("emerald"));
});

test("traceArchiveStatusText: failed", () => {
  const r = traceArchiveStatusText("failed");
  assert.equal(r.text, "归档失败");
  assert.ok(r.cls.includes("amber"));
});

test("traceArchiveStatusText: skipped", () => {
  const r = traceArchiveStatusText("skipped");
  assert.equal(r.text, "未归档（不可用）");
});

test("traceArchiveStatusText: unknown → passthrough", () => {
  const r = traceArchiveStatusText("something");
  assert.equal(r.text, "something");
});

test("traceArchiveStatusText: null → —", () => {
  const r = traceArchiveStatusText(null);
  assert.equal(r.text, "—");
});

test("topRiskDirectionLabel: RISK", () => {
  assert.equal(topRiskDirectionLabel("RISK"), "风险");
});

test("topRiskDirectionLabel: SAFE", () => {
  assert.equal(topRiskDirectionLabel("SAFE"), "安全");
});

test("topRiskDirectionLabel: NEUTRAL", () => {
  assert.equal(topRiskDirectionLabel("NEUTRAL"), "中性");
});

test("topRiskDirectionLabel: unknown → —", () => {
  assert.equal(topRiskDirectionLabel("unknown"), "—");
});

test("riskLevel: Infinity → —", () => {
  assert.equal(riskLevel(Infinity).text, "—");
});

test("topRiskFreshnessText: null env → 交易日 unknown", () => {
  assert.equal(topRiskFreshnessText(null), "交易日未知");
});

test("topRiskFreshnessText: no trade_date → 交易日 unknown", () => {
  assert.equal(topRiskFreshnessText({ trade_date: null, is_stale: false }), "交易日未知");
});

test("topRiskFreshnessText: no trade_date is_stale=true → stale variant", () => {
  const txt = topRiskFreshnessText({ trade_date: null, is_stale: true });
  assert.ok(txt.includes("陈旧"));
});

test("topRiskFreshnessText: valid date → 交易日 YYYY-MM-DD", () => {
  const txt = topRiskFreshnessText({ trade_date: "2026-07-25", is_stale: false });
  assert.ok(txt.includes("交易日 2026-07-25"));
});

test("topRiskFreshnessText: stale variant", () => {
  const txt = topRiskFreshnessText({ trade_date: "2026-07-20", is_stale: true });
  assert.ok(txt.includes("交易日 2026-07-20"));
  assert.ok(txt.includes("陈旧"));
});

test("fetchedAtText: null → —", () => {
  assert.equal(fetchedAtText(null), "—");
});

test("fetchedAtText: valid ISO → human-readable", () => {
  assert.equal(fetchedAtText("2026-07-30T09:30:12.123456Z"), "2026-07-30 09:30:12");
});

test("fetchedAtText: short string → —", () => {
  assert.equal(fetchedAtText("abc"), "—");
});

test("limitationLines: null env → empty", () => {
  assert.deepEqual(limitationLines(null), []);
});

test("limitationLines: no limitations → empty", () => {
  assert.deepEqual(limitationLines(rec()), []);
});

test("limitationLines: with field + detail", () => {
  const env = rec({
    limitations: [
      { field: "engine", detail: "执行失败" },
    ],
  });
  const lines = limitationLines(env);
  assert.equal(lines.length, 1);
  assert.ok(lines[0].includes("engine"));
  assert.ok(lines[0].includes("执行失败"));
});

test("topRiskErrorMessage: 0 → network", () => {
  assert.equal(topRiskErrorMessage(0), "后端连接不可用");
});

test("topRiskErrorMessage: 501 → not ready", () => {
  assert.equal(topRiskErrorMessage(501), "依赖未就绪");
});

test("topRiskErrorMessage: other → fallback", () => {
  assert.equal(topRiskErrorMessage(500), "顶部风险分析暂不可用");
});

test("topRiskErrorMessage: undefined → fallback", () => {
  assert.equal(topRiskErrorMessage(undefined), "顶部风险分析暂不可用");
});
