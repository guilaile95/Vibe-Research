import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildTradeCreateInput,
  canonicalizeTradeExecutionTime,
  validateTradeDraft,
  type TradeDraft,
} from "../src/lib/tradeLedgerView.ts";

const pageSource = readFileSync(new URL("../src/pages/Trades.tsx", import.meta.url), "utf8");

function executedDraft(status: "full" | "partial"): TradeDraft {
  return {
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: status,
    planned_quantity: status === "partial" ? 200 : 100,
    actual_price: 1500,
    actual_quantity: status === "partial" ? 100 : 100,
    executed_at: "2098-01-02T10:00",
    fee: 0,
    other_cost: 0,
    unexecuted_reason: status === "partial" ? "仅成交一半" : "",
  };
}

test("新建 Trade 不自动选择 operation 或 execution status", () => {
  assert.match(pageSource, /operation: ""/);
  assert.match(pageSource, /execution_status: ""/);
  assert.doesNotMatch(pageSource, /operation: "buy",\s*execution_status: "full"/);
  assert.match(pageSource, /<option value="" disabled>请选择操作类型<\/option>/);
  assert.match(pageSource, /<option value="" disabled>请选择执行状态<\/option>/);
  assert.match(pageSource, /<select\s+required\s+value=\{createDraft\.operation\}/);
  assert.match(pageSource, /<select\s+required\s+value=\{createDraft\.execution_status\}/);
});

test("新建 executed Trade 不自动生成成交时间", () => {
  assert.match(pageSource, /executed_at: ""/);
  assert.doesNotMatch(pageSource, /const nowLocal = new Date\(\)/);
  assert.doesNotMatch(pageSource, /const isoNow =/);
  assert.doesNotMatch(pageSource, /executed_at: isoNow/);
});

test("full 与 partial 未填写成交时间时 fail closed", () => {
  assert.equal(
    validateTradeDraft({ ...executedDraft("full"), executed_at: "" }),
    "已全部执行状态下，成交时间不能为空",
  );
  assert.equal(
    validateTradeDraft({ ...executedDraft("partial"), executed_at: "" }),
    "部分执行状态下，成交时间不能为空",
  );
});

test("显式成交时间的预览和 payload 使用同一个 canonical UTC ISO", () => {
  for (const status of ["full", "partial"] as const) {
    const draft = executedDraft(status);
    assert.equal(validateTradeDraft(draft), null);
    const payload = buildTradeCreateInput(draft);
    assert.equal(payload.executed_at, canonicalizeTradeExecutionTime(draft.executed_at));
    assert.match(payload.executed_at ?? "", /Z$/);
  }
});

test("executed Trade 必须显式填写非负费用，0 是用户确认值", () => {
  for (const status of ["full", "partial"] as const) {
    const valid = executedDraft(status);
    assert.equal(validateTradeDraft({ ...valid, fee: "", other_cost: 0 }), `${status === "full" ? "已全部执行" : "部分执行"}状态下，手续费不能为空`);
    assert.equal(validateTradeDraft({ ...valid, fee: 0, other_cost: "" }), `${status === "full" ? "已全部执行" : "部分执行"}状态下，其他费用不能为空`);
    assert.equal(validateTradeDraft({ ...valid, fee: 0, other_cost: 0 }), null);
    const payload = buildTradeCreateInput({ ...valid, fee: 0, other_cost: 0 });
    assert.equal(payload.fee, 0);
    assert.equal(payload.other_cost, 0);
  }
});

test("费用拒绝负数、非有限值和非法文本", () => {
  const valid = executedDraft("full");
  for (const value of [-0.01, Number.NaN, Number.POSITIVE_INFINITY, "not-a-cost"]) {
    assert.equal(validateTradeDraft({ ...valid, fee: value }), "手续费不得小于 0");
    assert.equal(validateTradeDraft({ ...valid, other_cost: value }), "其他费用不得小于 0");
  }
});

test("页面费用输入默认为空、执行态必填且不猜测费用", () => {
  assert.match(pageSource, /fee: ""/);
  assert.match(pageSource, /other_cost: ""/);
  assert.doesNotMatch(pageSource, /fee: "0"/);
  assert.doesNotMatch(pageSource, /other_cost: "0"/);
  assert.match(pageSource, /placeholder="请输入实际费用，0 表示确认费用为 0"/);
  assert.match(pageSource, /手续费 \(¥\)[\s\S]*?required/);
  assert.match(pageSource, /其他费用 \(¥\)[\s\S]*?required/);
});

test("not_executed 继续不要求并且不提交 executed_at", () => {
  const draft: TradeDraft = {
    code: "600519",
    name: "贵州茅台",
    operation: "buy",
    execution_status: "not_executed",
    executed_at: "",
    unexecuted_reason: "触发价未到达",
  };
  assert.equal(validateTradeDraft(draft), null);
  const payload = buildTradeCreateInput(draft);
  assert.equal("executed_at" in payload, false);
});

test("未选择执行状态时不显示成交事实字段", () => {
  assert.match(pageSource, /明确选择 full\/partial 时展示/);
  assert.match(pageSource, /createDraft\.execution_status === "full" \|\| createDraft\.execution_status === "partial"/);
});

test("页面显示时区、offset 和 canonical UTC 预览", () => {
  assert.match(pageSource, /浏览器解析时区/);
  assert.match(pageSource, /UTC offset/);
  assert.match(pageSource, /Canonical UTC ISO/);
  assert.match(pageSource, /请显式选择真实成交时间/);
  assert.match(pageSource, /type="datetime-local"/);
});
