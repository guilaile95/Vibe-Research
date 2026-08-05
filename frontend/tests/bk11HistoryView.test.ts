import assert from "node:assert/strict";
import test from "node:test";

import type { Bk11HistoryEnvelope } from "../src/lib/api/types";
import {
  dataTimeText,
  deltaValue,
  digestText,
  factValue,
  formatDeltaNumber,
  formatNullableNumber,
  gapValue,
  hasComparableDelta,
  ladderRows,
  ladderValue,
  limitationLines,
  previousTradeDate,
  statusLabel,
} from "../src/lib/bk11HistoryView.ts";

function envelope(overrides: Partial<Bk11HistoryEnvelope> = {}): Bk11HistoryEnvelope {
  return {
    schema_version: "bk11-history-query-v0.1",
    status: "normal",
    window: { requested: 5, snapshot_count: 1 },
    trade_date: "2026-07-30",
    data_time: "2026-07-30T15:10:00.000000Z",
    snapshots: [],
    latest: {
      schema_version: "short-term-daily-facts-v0.1",
      trade_date: "2026-07-30",
      session: "final",
      is_final: true,
      source_ids: ["eastmoney_getTopicZTPool"],
      fetched_at: "2026-07-30T15:05:00.000000Z",
      snapshot_at: "2026-07-30T15:10:00.000000Z",
      status: "normal",
      reason_codes: [],
      warnings: [],
      limitations: ["fixture"],
      source_schema_version: "short-term-limit-up-final-snapshot-v0.1",
      source_status: "normal",
      source_reason_codes: [],
      sections: {
        facts: {
          schema_version: "short-term-market-facts-v0.1",
          status: "normal",
          facts: {
            advance_count: 100,
            decline_count: 50,
            flat_count: 20,
            suspended_count: 3,
            eligible_count: 173,
            valid_count: 170,
            up_ratio: 0.6,
            limit_up_count: 10,
            limit_down_count: 1,
            failed_limit_up_count: 2,
            touched_limit_up_count: 12,
            sealed_limit_up_count: 10,
            seal_rate: 0.8,
            failed_board_rate: 0.2,
          },
        },
        ladder: {
          schema_version: "short-term-limit-up-ladder-v0.1",
          status: "normal",
          metrics: {
            max_boards: 6,
            lianban_count: 3,
            // 故意乱序输入，验证稳定排序
            ladder: [
              { boards: 6, count: 1 },
              { boards: 2, count: 8 },
              { boards: 3, count: 4 },
            ],
          },
        },
        gap: {
          schema_version: "short-term-ladder-gap-v0.1",
          status: "normal",
          metrics: {
            gap_level_count: 1,
            gap_segment_count: 1,
            largest_gap_width: 2,
            first_gap_board: 4,
            is_continuous: false,
          },
        },
      },
    },
    delta: {
      schema_version: "short-term-fact-compare-v0.1",
      previous_trade_date: "2026-07-29",
      current_trade_date: "2026-07-30",
      status: "normal",
      reason_codes: [],
      warnings: [],
      limitations: [],
      section_status: { facts: "normal" },
      deltas: {
        facts: {
          limit_up_count: 2,
          advance_count: -5,
          decline_count: null,
          failed_limit_up_count: 0,
        },
      },
    },
    summary: {
      schema_version: "short-term-fact-summary-v0.1",
      window: { count: 2, first_trade_date: "2026-07-29", last_trade_date: "2026-07-30" },
      status: "normal",
      reason_codes: [],
      warnings: [],
      limitations: [],
      stats: null,
    },
    digest: {
      schema_version: "short-term-fact-digest-v0.1",
      status: "normal",
      reason_codes: [],
      warnings: [],
      limitations: [],
      digest_text: "# 短线市场事实摘要（2 天）",
    },
    reason_codes: [],
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

test("formatNullableNumber never shows NaN/0 for missing values", () => {
  assert.equal(formatNullableNumber(null), "—");
  assert.equal(formatNullableNumber(undefined), "—");
  assert.equal(formatNullableNumber(Number.NaN), "—");
  assert.equal(formatNullableNumber(Number.POSITIVE_INFINITY), "—");
  assert.equal(formatNullableNumber("NaN"), "—");
  assert.equal(formatNullableNumber("  "), "—");
  assert.equal(formatNullableNumber(true), "—");
  assert.equal(formatNullableNumber(10), "10");
  assert.equal(formatNullableNumber("10"), "10");
});

test("formatDeltaNumber adds plus for positive, dash for missing", () => {
  assert.equal(formatDeltaNumber(2), "+2");
  assert.equal(formatDeltaNumber(-5), "-5");
  assert.equal(formatDeltaNumber(0), "0");
  assert.equal(formatDeltaNumber(null), "—");
  assert.equal(formatDeltaNumber(Number.NaN), "—");
});

test("statusLabel covers all envelope statuses", () => {
  assert.equal(statusLabel("normal"), "正常");
  assert.equal(statusLabel("partial"), "部分缺失");
  assert.equal(statusLabel("unavailable"), "不可用");
  assert.equal(statusLabel("empty"), "暂无历史");
  assert.equal(statusLabel("error"), "读取失败");
  assert.equal(statusLabel(undefined), "未知");
});

test("factValue reads latest facts and returns null when absent", () => {
  const env = envelope();
  assert.equal(factValue(env, "advance_count"), 100);
  assert.equal(factValue(env, "decline_count"), 50);
  assert.equal(factValue(env, "limit_up_count"), 10);
  assert.equal(factValue(env, "missing_field"), null);
  assert.equal(factValue(envelope({ status: "empty", latest: null }), "limit_up_count"), null);
});

test("factValue requires the real nested facts body", () => {
  const env = envelope();
  const latest = env.latest!;
  // 扁平化伪合同（旧错误结构）：必须返回 null 而不是读错层级
  const flat = {
    ...env,
    latest: {
      ...latest,
      sections: {
        facts: {
          schema_version: "short-term-market-facts-v0.1",
          status: "normal",
          advance_count: 999,
        },
        ladder: null,
        gap: null,
      },
    },
  } as Bk11HistoryEnvelope;
  assert.equal(factValue(flat, "advance_count"), null);
});

test("ladderValue and ladderRows read the real metrics contract", () => {
  const env = envelope();
  assert.equal(ladderValue(env, "max_boards"), 6);
  assert.equal(ladderValue(env, "lianban_count"), 3);
  assert.deepEqual(ladderRows(env), [
    { boards: 2, count: 8 },
    { boards: 3, count: 4 },
    { boards: 6, count: 1 },
  ]);
});

test("ladderRows handles empty and malformed ladder without crashing", () => {
  const base = envelope();
  const empty = {
    ...base,
    latest: {
      ...base.latest!,
      sections: {
        ...base.latest!.sections,
        ladder: { schema_version: "x", status: "normal", metrics: { max_boards: 6, lianban_count: 3, ladder: [] } },
      },
    },
  } as Bk11HistoryEnvelope;
  assert.deepEqual(ladderRows(empty), []);

  const malformed = {
    ...base,
    latest: {
      ...base.latest!,
      sections: {
        ...base.latest!.sections,
        ladder: { schema_version: "x", status: "normal", metrics: { ladder: [{ boards: "bad", count: null }, null, 42] } },
      },
    },
  } as unknown as Bk11HistoryEnvelope;
  assert.deepEqual(ladderRows(malformed), []);

  const missing = {
    ...base,
    latest: {
      ...base.latest!,
      sections: { ...base.latest!.sections, ladder: null },
    },
  } as Bk11HistoryEnvelope;
  assert.deepEqual(ladderRows(missing), []);
});

test("gapValue reads the real gap metrics field names", () => {
  const env = envelope();
  assert.equal(gapValue(env, "gap_level_count"), 1);
  assert.equal(gapValue(env, "gap_segment_count"), 1);
  assert.equal(gapValue(env, "largest_gap_width"), 2);
  // 旧错误字段名不存在 → null（显示 "—"）
  assert.equal(gapValue(env, "gap_levels"), null);
  assert.equal(gapValue(env, "gap_segments"), null);
  assert.equal(gapValue(env, "max_gap_width"), null);
});

test("malformed section nesting returns null not crash", () => {
  const base = envelope();
  const broken = {
    ...base,
    latest: {
      ...base.latest!,
      sections: {
        facts: null,
        ladder: { schema_version: "x", status: "normal" },
        gap: { schema_version: "x", status: "normal", metrics: "oops" },
      },
    },
  } as unknown as Bk11HistoryEnvelope;
  assert.equal(factValue(broken, "advance_count"), null);
  assert.equal(ladderValue(broken, "max_boards"), null);
  assert.equal(gapValue(broken, "gap_level_count"), null);
  assert.deepEqual(ladderRows(broken), []);
});

test("digestText extracts plain text only", () => {
  assert.equal(digestText(envelope()), "# 短线市场事实摘要（2 天）");
  assert.equal(digestText(envelope({ digest: null })), "");
  assert.equal(digestText(envelope({ digest: { digest_text: 42 } as never })), "");
});

test("delta helpers require comparable delta", () => {
  const env = envelope();
  assert.equal(hasComparableDelta(env), true);
  assert.equal(previousTradeDate(env), "2026-07-29");
  assert.equal(deltaValue(env, "limit_up_count"), 2);
  assert.equal(deltaValue(env, "decline_count"), null);

  const noDelta = envelope({ delta: null });
  assert.equal(hasComparableDelta(noDelta), false);
  assert.equal(previousTradeDate(noDelta), null);
  assert.equal(deltaValue(noDelta, "limit_up_count"), null);

  const empty = envelope({ status: "empty", latest: null, delta: null });
  assert.equal(hasComparableDelta(empty), false);
});

test("dataTimeText and limitations are stable", () => {
  assert.equal(dataTimeText("2026-07-30T15:10:00.000000Z"), "2026-07-30T15:10:00.000000Z");
  assert.equal(dataTimeText(null), "—");
  assert.deepEqual(limitationLines(envelope()), []);
  assert.deepEqual(
    limitationLines(envelope({ limitations: ["a", "b"] })),
    ["a", "b"],
  );
});
