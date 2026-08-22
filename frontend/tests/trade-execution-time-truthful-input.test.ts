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
    unexecuted_reason: status === "partial" ? "仅成交一半" : "",
  };
}

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

test("页面显示时区、offset 和 canonical UTC 预览", () => {
  assert.match(pageSource, /浏览器解析时区/);
  assert.match(pageSource, /UTC offset/);
  assert.match(pageSource, /Canonical UTC ISO/);
  assert.match(pageSource, /请显式选择真实成交时间/);
  assert.match(pageSource, /type="datetime-local"/);
});
