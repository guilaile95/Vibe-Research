import assert from "node:assert/strict";
import test, { describe } from "node:test";
import {
  traceStatusLabel,
  qualityStatusLabel,
  scopeLabel,
  traceStatusBadgeClass,
  qualityStatusBadgeClass,
  scopeBadgeClass,
  formatEvidenceTime,
  escapeHtmlText,
  safeRenderText,
  filterDecisionRuns,
  getExplanationEvidences,
} from "../src/lib/decisionEvidenceView.ts";
import type {
  DecisionRunRecord,
  EvidenceItemRecord,
  ExplanationItemRecord,
} from "../src/lib/api/types.ts";

describe("decisionEvidenceView pure functions", () => {
  test("traceStatusLabel maps statuses to Chinese labels correctly", () => {
    assert.equal(traceStatusLabel("complete"), "完整追踪");
    assert.equal(traceStatusLabel("archived"), "完整追踪");
    assert.equal(traceStatusLabel("partial"), "部分追踪");
    assert.equal(traceStatusLabel("failed"), "追踪失败");
    assert.equal(traceStatusLabel(null), "—");
    assert.equal(traceStatusLabel("custom_status"), "custom_status");
  });

  test("qualityStatusLabel maps data quality to Chinese labels", () => {
    assert.equal(qualityStatusLabel("valid"), "高可靠数据");
    assert.equal(qualityStatusLabel("partial"), "部分可用");
    assert.equal(qualityStatusLabel("missing"), "关键缺失");
    assert.equal(qualityStatusLabel("stale"), "数据陈旧");
    assert.equal(qualityStatusLabel("unavailable"), "不可用");
    assert.equal(qualityStatusLabel(undefined), "—");
  });

  test("scopeLabel maps evidence scopes", () => {
    assert.equal(scopeLabel("market"), "大盘宏观");
    assert.equal(scopeLabel("sector"), "行业板块");
    assert.equal(scopeLabel("stock"), "个股基本面");
    assert.equal(scopeLabel("portfolio"), "持仓组合");
    assert.equal(scopeLabel("account"), "账户资金");
    assert.equal(scopeLabel("risk"), "风控规则");
    assert.equal(scopeLabel("other"), "other");
  });

  test("badge classes returned for statuses and scopes", () => {
    assert.ok(traceStatusBadgeClass("complete").includes("emerald"));
    assert.ok(traceStatusBadgeClass("failed").includes("rose"));
    assert.ok(qualityStatusBadgeClass("valid").includes("emerald"));
    assert.ok(qualityStatusBadgeClass("missing").includes("rose"));
    assert.ok(scopeBadgeClass("market").includes("blue"));
  });

  test("formatEvidenceTime formats ISO date strings safely", () => {
    assert.equal(formatEvidenceTime(null), "—");
    assert.equal(formatEvidenceTime("invalid-date"), "invalid-date");
    const formatted = formatEvidenceTime("2026-07-29T12:00:00.000Z");
    assert.ok(formatted.includes("2026"), `Expected 2026 in ${formatted}`);
  });

  test("escapeHtmlText escapes HTML special characters", () => {
    const raw = `<script>alert('xss & "test"')</script>`;
    const escaped = escapeHtmlText(raw);
    assert.equal(escaped.includes("<script>"), false);
    assert.ok(escaped.includes("&lt;script&gt;"));
    assert.ok(escaped.includes("&amp;"));
    assert.ok(escaped.includes("&quot;"));
    assert.ok(escaped.includes("&#039;"));
  });

  test("safeRenderText converts primitives and JSON objects safely", () => {
    assert.equal(safeRenderText(null), "—");
    assert.equal(safeRenderText("hello"), "hello");
    assert.equal(safeRenderText(123.45), "123.45");
    assert.equal(safeRenderText(true), "true");
    const objStr = safeRenderText({ key: "value", num: 1 });
    assert.ok(objStr.includes('"key": "value"'));
  });

  test("filterDecisionRuns filters runs by symbol/code, date, quality and trace status", () => {
    const runs: DecisionRunRecord[] = [
      {
        id: "dr_1",
        code: "600519",
        trade_date: "2026-07-29",
        generated_at: "2026-07-29T10:00:00Z",
        quality_status: "valid",
        trace_status: "complete",
      },
      {
        id: "dr_2",
        code: "000001",
        trade_date: "2026-07-28",
        generated_at: "2026-07-28T10:00:00Z",
        quality_status: "missing",
        trace_status: "failed",
      },
    ];

    assert.equal(filterDecisionRuns(runs, { symbol: "600519" }).length, 1);
    assert.equal(filterDecisionRuns(runs, { trade_date: "2026-07-28" }).length, 1);
    assert.equal(filterDecisionRuns(runs, { quality_status: "valid" }).length, 1);
    assert.equal(filterDecisionRuns(runs, { trace_status: "failed" }).length, 1);
    assert.equal(filterDecisionRuns(runs, { symbol: "nonexistent" }).length, 0);
  });

  test("getExplanationEvidences matches supporting and limiting evidence items", () => {
    const explanation: ExplanationItemRecord = {
      id: "exp_1",
      decision_run_id: "dr_1",
      claim: "看好茅台突破",
      conclusion: "买入",
      supporting_evidence_ids: ["ev_1"],
      limiting_evidence_ids: ["ev_2"],
    };

    const evidences: EvidenceItemRecord[] = [
      {
        id: "ev_1",
        decision_run_id: "dr_1",
        scope: "stock",
        title: "业绩大超预期",
        quality_status: "valid",
      },
      {
        id: "ev_2",
        decision_run_id: "dr_1",
        scope: "market",
        title: "大盘整体缩量",
        quality_status: "partial",
      },
    ];

    const { supporting, limiting } = getExplanationEvidences(explanation, evidences);
    assert.equal(supporting.length, 1);
    assert.equal(supporting[0].title, "业绩大超预期");
    assert.equal(limiting.length, 1);
    assert.equal(limiting[0].title, "大盘整体缩量");
  });
});
