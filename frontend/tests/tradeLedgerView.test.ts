import assert from "node:assert/strict";
import test, { describe } from "node:test";
import {
  buildTradeCreateInput,
  buildTradeListQuery,
  executionStatusLabel,
  formatTradeMoney,
  formatTradePercentage,
  formatTradeQuantity,
  formatTradeTime,
  operationLabel,
  validateTradeDraft,
  validateTradeListFilters,
  type TradeDraft,
} from "../src/lib/tradeLedgerView.ts";

describe("tradeLedgerView pure helpers", () => {
  test("operationLabel formats correctly", () => {
    assert.equal(operationLabel("buy"), "买入");
    assert.equal(operationLabel("add"), "加仓");
    assert.equal(operationLabel("reduce"), "减仓");
    assert.equal(operationLabel("sell"), "卖出");
    assert.equal(operationLabel("custom"), "custom");
  });

  test("executionStatusLabel formats correctly", () => {
    assert.equal(executionStatusLabel("full"), "已全部执行");
    assert.equal(executionStatusLabel("partial"), "部分执行");
    assert.equal(executionStatusLabel("not_executed"), "未执行");
  });

  test("formatTradeMoney formats values correctly", () => {
    assert.equal(formatTradeMoney(null), "—");
    assert.equal(formatTradeMoney(undefined), "—");
    assert.equal(formatTradeMoney(12000), "¥12,000.00");
    assert.equal(formatTradeMoney(-12000), "-¥12,000.00");
    assert.equal(formatTradeMoney(0), "¥0.00");
    assert.equal(formatTradeMoney(Infinity), "—");
  });

  test("formatTradeQuantity formats integers", () => {
    assert.equal(formatTradeQuantity(null), "—");
    assert.equal(formatTradeQuantity(1000), "1,000");
    assert.equal(formatTradeQuantity(0), "0");
  });

  test("formatTradeTime formats valid ISO strings", () => {
    assert.equal(formatTradeTime(null), "—");
    assert.equal(formatTradeTime("invalid"), "—");
    const formatted = formatTradeTime("2026-07-28T09:30:00.000Z");
    assert.ok(formatted.includes("2026"), `Expected date format, got: ${formatted}`);
  });

  test("validateTradeDraft checks full execution rules", () => {
    const valid: TradeDraft = {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "full",
      actual_price: 1500,
      actual_quantity: 100,
      executed_at: "2026-07-28T09:30",
    };
    assert.equal(validateTradeDraft(valid), null);

    const invalidCode: TradeDraft = { ...valid, code: "123" };
    assert.equal(validateTradeDraft(invalidCode), "股票代码必须是 6 位数字");

    const invalidQty: TradeDraft = { ...valid, planned_quantity: 200, actual_quantity: 100 };
    assert.equal(validateTradeDraft(invalidQty), "已全部执行状态下，实际数量必须等于计划数量");

    assert.equal(
      validateTradeDraft({ ...valid, actual_price: Infinity }),
      "已全部执行状态下，实际价格必须大于 0",
    );
    assert.equal(
      validateTradeDraft({ ...valid, actual_quantity: 100.5 }),
      "已全部执行状态下，实际数量必须是正整数",
    );
    assert.equal(
      validateTradeDraft({ ...valid, executed_at: "invalid" }),
      "已全部执行状态下，成交时间不合法",
    );
    assert.equal(
      validateTradeDraft({ ...valid, unexecuted_reason: "不应存在" }),
      "已全部执行状态下，不得填写未执行原因",
    );
  });

  test("validateTradeDraft checks partial execution rules", () => {
    const valid: TradeDraft = {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "partial",
      planned_quantity: 200,
      actual_price: 1500,
      actual_quantity: 100,
      executed_at: "2026-07-28T09:30",
      unexecuted_reason: "资金不足",
    };
    assert.equal(validateTradeDraft(valid), null);

    const missingReason: TradeDraft = { ...valid, unexecuted_reason: "" };
    assert.equal(validateTradeDraft(missingReason), "部分执行状态下，未执行原因不能为空");

    const qtyMismatch: TradeDraft = { ...valid, actual_quantity: 200 };
    assert.equal(validateTradeDraft(qtyMismatch), "部分执行状态下，实际数量必须小于计划数量");
  });

  test("validateTradeDraft checks not_executed rules", () => {
    const valid: TradeDraft = {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "not_executed",
      unexecuted_reason: "高开放弃",
    };
    assert.equal(validateTradeDraft(valid), null);

    const missingReason: TradeDraft = { ...valid, unexecuted_reason: "" };
    assert.equal(validateTradeDraft(missingReason), "未执行状态下，未执行原因不能为空");
  });

  test("buildTradeCreateInput formats input and handles not_executed", () => {
    const draft: TradeDraft = {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "not_executed",
      actual_price: 1500,
      actual_quantity: 100,
      executed_at: "2026-07-28T09:30",
      fee: 10,
      other_cost: 5,
      unexecuted_reason: "冲高放弃",
      advice_ref: {
        trade_date: "2026-07-28",
        generated_at: "2026-07-28 09:00:00",
      },
    };
    const input = buildTradeCreateInput(draft);
    assert.equal(input.execution_status, "not_executed");
    assert.equal("actual_price" in input, false);
    assert.equal("actual_quantity" in input, false);
    assert.equal("executed_at" in input, false);
    assert.equal("fee" in input, false);
    assert.equal("other_cost" in input, false);
    assert.equal(input.unexecuted_reason, "冲高放弃");
    assert.deepEqual(input.advice_ref, {
      trade_date: "2026-07-28",
      generated_at: "2026-07-28 09:00:00",
    });
  });

  test("buildTradeCreateInput formats executed trades in UTC", () => {
    const draft: TradeDraft = {
      code: " 600519 ",
      name: " 贵州茅台 ",
      operation: "sell",
      execution_status: "partial",
      planned_price: "1500",
      planned_quantity: "200",
      actual_price: "1510",
      actual_quantity: "100",
      executed_at: "2026-07-28T09:30",
      fee: "10",
      other_cost: "5",
      unexecuted_reason: "仅成交一半",
      note: "  手工记录  ",
      thesis_ref: { thesis_id: " thesis-1 ", revision_number: 2 },
    };

    const input = buildTradeCreateInput(draft);
    assert.equal(input.code, "600519");
    assert.equal(input.name, "贵州茅台");
    assert.equal(input.actual_price, 1510);
    assert.equal(input.actual_quantity, 100);
    assert.equal(input.executed_at, new Date("2026-07-28T09:30").toISOString());
    assert.equal(input.fee, 10);
    assert.equal(input.other_cost, 5);
    assert.equal(input.note, "手工记录");
    assert.deepEqual(input.thesis_ref, { thesis_id: "thesis-1", revision_number: 2 });
  });

  test("validateTradeDraft requires complete optional references", () => {
    const valid: TradeDraft = {
      code: "600519",
      name: "贵州茅台",
      operation: "buy",
      execution_status: "not_executed",
      unexecuted_reason: "等待确认",
    };

    assert.equal(
      validateTradeDraft({
        ...valid,
        advice_ref: { trade_date: "2026-07-28", generated_at: "" },
      }),
      "建议引用需同时填写交易日期和生成时间",
    );
    assert.equal(
      validateTradeDraft({
        ...valid,
        thesis_ref: { thesis_id: "thesis-1", revision_number: 0 },
      }),
      "Thesis 引用需填写有效 ID 和正整数版本号",
    );
  });

  test("formatTradePercentage and quantity reject invalid display values", () => {
    assert.equal(formatTradePercentage(null), "—");
    assert.equal(formatTradePercentage(12.345), "12.35%");
    assert.equal(formatTradePercentage(Infinity), "—");
    assert.equal(formatTradeQuantity(100.5), "—");
    assert.equal(formatTradeQuantity(Infinity), "—");
  });

  test("validateTradeListFilters checks code and date range", () => {
    assert.equal(validateTradeListFilters({ code: "123" }), "股票代码筛选必须是 6 位数字");
    assert.equal(
      validateTradeListFilters({ date_from: "2026-07-29", date_to: "2026-07-28" }),
      "开始日期不得晚于结束日期",
    );
    assert.equal(validateTradeListFilters({ date_from: "2026-07-28", date_to: "2026-07-29" }), null);
  });

  test("buildTradeListQuery filters empty values and applies pagination", () => {
    const query = buildTradeListQuery({
      code: " 600519 ",
      operation: "buy",
      execution_status: "",
      include_voided: true,
    }, 50, 0);
    assert.deepEqual(query, {
      code: "600519",
      operation: "buy",
      include_voided: true,
      limit: 50,
      offset: 0,
    });
  });
});
