import assert from "node:assert/strict";
import test, { describe } from "node:test";
import {
  stageLabel,
  stageBadgeColor,
  severityLabel,
  severityBadgeColor,
  actionLabel,
  actionBadgeColor,
  formatSignalTime,
  validateSignalFilters,
} from "../src/lib/signalLedgerView.ts";

describe("signalLedgerView pure functions", () => {
  test("formats stage labels and badge colors", () => {
    assert.ok(stageLabel("schema").includes("模式校验"));
    assert.ok(stageLabel("execution").includes("执行裁决"));
    assert.ok(stageLabel("account_constraint").includes("资金约束"));
    assert.equal(stageLabel("unknown_stage"), "unknown_stage");

    assert.ok(stageBadgeColor("schema").includes("purple"));
    assert.ok(stageBadgeColor("execution").includes("emerald"));
  });

  test("formats severity labels and badge colors", () => {
    assert.ok(severityLabel("info").includes("正常"));
    assert.ok(severityLabel("warning").includes("预警"));
    assert.ok(severityLabel("error").includes("错误"));

    assert.ok(severityBadgeColor("info").includes("blue"));
    assert.ok(severityBadgeColor("error").includes("rose"));
  });

  test("formats action labels and badge colors", () => {
    assert.equal(actionLabel("buy"), "买入");
    assert.equal(actionLabel("sell"), "卖出");
    assert.equal(actionLabel("hold"), "持有");

    assert.ok(actionBadgeColor("buy").includes("rose"));
    assert.ok(actionBadgeColor("sell").includes("emerald"));
  });

  test("formats signal timestamp safely", () => {
    assert.equal(formatSignalTime(null), "—");
    assert.equal(formatSignalTime("invalid-date"), "—");
    const formatted = formatSignalTime("2026-07-29T10:00:00Z");
    assert.notEqual(formatted, "—");
  });

  test("validates filters correctly", () => {
    assert.equal(validateSignalFilters({}), null);
    assert.equal(validateSignalFilters({ code: "600519" }), null);
    assert.equal(validateSignalFilters({ code: "invalid" }), "股票代码必须是 6 位数字");
  });
});
