import assert from "node:assert/strict";
import test, { describe } from "node:test";
import {
  adoptionStatusLabel,
  buildFeedbackCreateInput,
  buildFeedbackListQuery,
  formatFeedbackTime,
  outcomeStatusLabel,
  validateFeedbackDraft,
  validateFeedbackListFilters,
  type DecisionFeedbackDraft,
  type DecisionFeedbackListFilters,
} from "../src/lib/decisionFeedbackView.ts";

describe("decisionFeedbackView pure helpers", () => {
  test("adoptionStatusLabel formats correctly", () => {
    assert.equal(adoptionStatusLabel("followed"), "按照建议执行");
    assert.equal(adoptionStatusLabel("partially_followed"), "部分执行建议");
    assert.equal(adoptionStatusLabel("not_followed"), "明确未执行");
    assert.equal(adoptionStatusLabel("not_applicable"), "不适用/未达成条件");
    assert.equal(adoptionStatusLabel("unknown"), "unknown");
  });

  test("outcomeStatusLabel formats correctly", () => {
    assert.equal(outcomeStatusLabel("better_than_expected"), "超出预期");
    assert.equal(outcomeStatusLabel("as_expected"), "符合预期");
    assert.equal(outcomeStatusLabel("worse_than_expected"), "低于预期");
    assert.equal(outcomeStatusLabel("not_evaluated"), "暂未评估");
    assert.equal(outcomeStatusLabel("unknown"), "unknown");
  });

  test("formatFeedbackTime formats ISO strings", () => {
    assert.equal(formatFeedbackTime(null), "—");
    assert.equal(formatFeedbackTime("invalid"), "invalid");
    const formatted = formatFeedbackTime("2026-07-29T10:00:00.000Z");
    assert.ok(formatted.includes("2026"), `Expected date format, got: ${formatted}`);
  });

  test("validateFeedbackDraft validates code, dates, and enums", () => {
    const validDraft: DecisionFeedbackDraft = {
      code: "600519",
      advice_trade_date: "2026-07-29",
      advice_generated_at: "2026-07-29T08:00:00Z",
      adoption_status: "followed",
      outcome_status: "as_expected",
      note: "符合预期",
    };
    assert.equal(validateFeedbackDraft(validDraft), null);

    const invalidCode: DecisionFeedbackDraft = { ...validDraft, code: "123" };
    assert.equal(validateFeedbackDraft(invalidCode), "股票代码必须是 6 位数字");

    const invalidDate: DecisionFeedbackDraft = { ...validDraft, advice_trade_date: "2026/07/29" };
    assert.equal(validateFeedbackDraft(invalidDate), "建议交易日期格式须为 YYYY-MM-DD");

    const emptyGenAt: DecisionFeedbackDraft = { ...validDraft, advice_generated_at: "  " };
    assert.equal(validateFeedbackDraft(emptyGenAt), "建议生成时间不能为空");

    const invalidAdoption: DecisionFeedbackDraft = { ...validDraft, adoption_status: "invalid" as any };
    assert.equal(validateFeedbackDraft(invalidAdoption), "采纳执行状态无效");

    const invalidOutcome: DecisionFeedbackDraft = { ...validDraft, outcome_status: "invalid" as any };
    assert.equal(validateFeedbackDraft(invalidOutcome), "事后评估结果无效");

    const longNote: DecisionFeedbackDraft = { ...validDraft, note: "a".repeat(2001) };
    assert.equal(validateFeedbackDraft(longNote), "备注长度不能超过 2000 字符");
  });

  test("buildFeedbackCreateInput constructs input correctly", () => {
    const draft: DecisionFeedbackDraft = {
      code: " 000001 ",
      advice_trade_date: " 2026-07-29 ",
      advice_generated_at: " 2026-07-29T08:00:00Z ",
      trade_id: " trade_123 ",
      adoption_status: "followed",
      outcome_status: "better_than_expected",
      note: " 超出预期 ",
    };

    const input = buildFeedbackCreateInput(draft);
    assert.deepEqual(input, {
      code: "000001",
      advice_trade_date: "2026-07-29",
      advice_generated_at: "2026-07-29T08:00:00Z",
      trade_id: "trade_123",
      adoption_status: "followed",
      outcome_status: "better_than_expected",
      note: "超出预期",
      advice_ref: {
        trade_date: "2026-07-29",
        generated_at: "2026-07-29T08:00:00Z",
      },
    });
  });

  test("validateFeedbackListFilters validates code and date ranges", () => {
    const valid: DecisionFeedbackListFilters = {
      code: "600519",
      date_from: "2026-07-01",
      date_to: "2026-07-29",
    };
    assert.equal(validateFeedbackListFilters(valid), null);

    assert.equal(
      validateFeedbackListFilters({ ...valid, code: "abc" }),
      "股票代码筛选必须是 6 位数字",
    );
    assert.equal(
      validateFeedbackListFilters({ ...valid, date_from: "2026/07/01" }),
      "开始日期格式须为 YYYY-MM-DD",
    );
    assert.equal(
      validateFeedbackListFilters({ ...valid, date_from: "2026-07-30", date_to: "2026-07-01" }),
      "开始日期不得晚于结束日期",
    );
  });

  test("buildFeedbackListQuery builds query parameters", () => {
    const filters: DecisionFeedbackListFilters = {
      code: "600519",
      adoption_status: "followed",
      outcome_status: "as_expected",
      date_from: "2026-07-01",
      date_to: "2026-07-29",
      include_voided: true,
    };
    const query = buildFeedbackListQuery(filters, 10, 0);
    assert.deepEqual(query, {
      code: "600519",
      adoption_status: "followed",
      outcome_status: "as_expected",
      date_from: "2026-07-01",
      date_to: "2026-07-29",
      include_voided: true,
      limit: 10,
      offset: 0,
    });
  });
});
