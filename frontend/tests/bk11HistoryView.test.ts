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
  hasComparableDelta,
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
          advance_count: 100,
          decline_count: 50,
          limit_up_count: 10,
          failed_limit_up_count: 2,
        },
        ladder: {
          schema_version: "short-term-limit-up-ladder-v0.1",
          status: "normal",
          max_boards: 6,
          lianban_count: 3,
        },
        gap: {
          schema_version: "short-term-ladder-gap-v0.1",
          status: "normal",
          gap_levels: 1,
          gap_segments: 1,
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
  assert.equal(factValue(env, "limit_up_count"), 10);
  assert.equal(factValue(env, "missing_field"), null);
  assert.equal(factValue(envelope({ status: "empty", latest: null }), "limit_up_count"), null);
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
