import assert from "node:assert/strict";
import test from "node:test";

import {
  heatmapColor,
  formatAmount,
  transformBoardRankingToHeatmap,
  resolveHeatmapState,
} from "../src/lib/sectorHeatmap.ts";
import type { BoardRankingData, TimedComponentEnvelope } from "../src/lib/api/types.ts";

// ── 颜色映射 ──────────────────────────────────────────────────────────

test("heatmapColor: red for up, green for down, neutral for near-zero or null", () => {
  // 上涨 → 红色系（R 通道高）
  const red = heatmapColor(2.5);
  assert.ok(red.startsWith("#"));
  const redR = parseInt(red.slice(1, 3), 16);
  const redG = parseInt(red.slice(3, 5), 16);
  assert.ok(redR > redG, `up color should be red-ish, got ${red}`);

  // 下跌 → 绿色系（G 通道高）
  const green = heatmapColor(-2.5);
  const greenR = parseInt(green.slice(1, 3), 16);
  const greenG = parseInt(green.slice(3, 5), 16);
  assert.ok(greenG > greenR, `down color should be green-ish, got ${green}`);

  // 接近 0 → 中性灰
  assert.equal(heatmapColor(0.01), "#3f3f46");
  assert.equal(heatmapColor(-0.01), "#3f3f46");

  // null / 非有限 → 中性灰（不伪造颜色）
  assert.equal(heatmapColor(null), "#3f3f46");
  assert.equal(heatmapColor(undefined), "#3f3f46");
  assert.equal(heatmapColor(NaN), "#3f3f46");
});

test("heatmapColor: color depth increases with |change_pct|", () => {
  const light = heatmapColor(0.5);
  const deep = heatmapColor(5.0);
  // 更深的红色应该 R 通道更低（更暗）
  const lightR = parseInt(light.slice(1, 3), 16);
  const deepR = parseInt(deep.slice(1, 3), 16);
  assert.ok(deepR <= lightR, `deeper change should be darker red, light=${light} deep=${deep}`);
});

// ── 成交额格式化 ──────────────────────────────────────────────────────

test("formatAmount: human-readable with 亿/万, null stays explicit", () => {
  assert.equal(formatAmount(null), "—");
  assert.equal(formatAmount(undefined), "—");
  assert.equal(formatAmount(-1), "—");
  assert.equal(formatAmount(1.5e8), "1.5 亿");
  assert.equal(formatAmount(5e4), "5 万");
  assert.equal(formatAmount(100), "100 元");
});

// ── 数据转换 ──────────────────────────────────────────────────────────

function makeBoard(overrides: Partial<{ code: string; name: string; change_pct: number; amount: number | null; up_count: number; down_count: number }> = {}) {
  return {
    code: overrides.code ?? "BK001",
    name: overrides.name ?? "测试板块",
    change_pct: overrides.change_pct ?? 1.0,
    amount: "amount" in overrides ? overrides.amount : 1e8,
    turnover_pct: 1.0,
    market_cap: 1e10,
    up_count: overrides.up_count ?? 10,
    down_count: overrides.down_count ?? 5,
    up_ratio: 0.6667,
    leader: "领涨股",
    leader_change_pct: 5.0,
  };
}

test("transformBoardRankingToHeatmap: uses real amount for value, excludes null amount", () => {
  const data: BoardRankingData = {
    type: "industry",
    total: 3,
    ranked_count: 3,
    unknown_count: 0,
    top: [],
    bottom: [],
    amount_top: [
      makeBoard({ code: "A", name: "大成交额", amount: 5e8, change_pct: 2.0 }),
      makeBoard({ code: "B", name: "无成交额", amount: null, change_pct: 1.0 }),
      makeBoard({ code: "C", name: "小成交额", amount: 1e8, change_pct: -1.0 }),
    ],
  };

  const result = transformBoardRankingToHeatmap(data, { maxItems: 10 });
  assert.equal(result.items.length, 2, "null amount should be excluded");
  assert.equal(result.validAmountCount, 2);
  // 按成交额降序
  assert.equal(result.items[0].name, "大成交额");
  assert.equal(result.items[0].value, 5e8);
  assert.equal(result.items[1].name, "小成交额");
  assert.equal(result.items[1].value, 1e8);
});

test("transformBoardRankingToHeatmap: aggregates overflow as '其他 N 个'", () => {
  const items = Array.from({ length: 35 }, (_, i) =>
    makeBoard({ code: `B${i}`, name: `板块${i}`, amount: (35 - i) * 1e7 }),
  );
  const data: BoardRankingData = {
    type: "concept",
    total: 35,
    ranked_count: 35,
    unknown_count: 0,
    top: [],
    bottom: [],
    amount_top: items,
  };

  const result = transformBoardRankingToHeatmap(data, { maxItems: 30 });
  assert.equal(result.items.length, 31, "30 main + 1 aggregate");
  assert.equal(result.aggregateCount, 5);
  const agg = result.items[30];
  assert.ok(agg.name.startsWith("其他 5 个"), `aggregate name should be '其他 5 个', got ${agg.name}`);
  assert.equal(agg.data.isAggregate, true);
  // 聚合面积 = 剩余 5 个成交额之和
  const expectedAggAmount = items.slice(30).reduce((s, b) => s + b.amount, 0);
  assert.equal(agg.value, expectedAggAmount);
});

test("transformBoardRankingToHeatmap: null data returns empty, not fake zeros", () => {
  const result = transformBoardRankingToHeatmap(null);
  assert.equal(result.items.length, 0);
  assert.equal(result.validAmountCount, 0);
  assert.equal(result.aggregateCount, 0);
});

// ── fail-closed 状态语义 ──────────────────────────────────────────────

function makeEnvelope(overrides: Partial<TimedComponentEnvelope<BoardRankingData>> = {}): TimedComponentEnvelope<BoardRankingData> {
  return {
    status: "normal",
    source: "eastmoney_push2",
    trade_date: null,
    data_time: null,
    fetched_at: "2026-08-28T10:00:00Z",
    is_stale: false,
    warnings: [],
    data: {
      type: "industry",
      total: 2,
      ranked_count: 2,
      unknown_count: 0,
      top: [],
      bottom: [],
      amount_top: [
        makeBoard({ code: "A", name: "板块A", amount: 2e8, change_pct: 1.5 }),
        makeBoard({ code: "B", name: "板块B", amount: 1e8, change_pct: -0.5 }),
      ],
    },
    ...overrides,
  };
}

test("resolveHeatmapState: normal with valid data", () => {
  const state = resolveHeatmapState(makeEnvelope(), false, false);
  assert.equal(state.status, "normal");
  assert.equal(state.items.length, 2);
  assert.equal(state.validAmountCount, 2);
  assert.equal(state.totalCount, 2);
});

test("resolveHeatmapState: loading state", () => {
  const state = resolveHeatmapState(null, true, false);
  assert.equal(state.status, "loading");
  assert.equal(state.items.length, 0);
});

test("resolveHeatmapState: error → unavailable, not fake zeros", () => {
  const state = resolveHeatmapState(null, false, true);
  assert.equal(state.status, "unavailable");
  assert.equal(state.items.length, 0);
  assert.ok(state.warnings.length > 0);
});

test("resolveHeatmapState: stale data → stale status", () => {
  const state = resolveHeatmapState(makeEnvelope({ is_stale: true }), false, false);
  assert.equal(state.status, "stale");
  assert.equal(state.items.length, 2, "stale still shows data, but with stale badge");
});

test("resolveHeatmapState: partial from backend status", () => {
  const state = resolveHeatmapState(makeEnvelope({ status: "partial" }), false, false);
  assert.equal(state.status, "partial");
});

test("resolveHeatmapState: all amounts missing → unavailable (no fake 0 area)", () => {
  const env = makeEnvelope({
    data: {
      type: "industry",
      total: 2,
      ranked_count: 2,
      unknown_count: 0,
      top: [],
      bottom: [],
      amount_top: [
        makeBoard({ code: "A", name: "无成交额A", amount: null }),
        makeBoard({ code: "B", name: "无成交额B", amount: null }),
      ],
    },
  });
  const state = resolveHeatmapState(env, false, false);
  assert.equal(state.status, "unavailable");
  assert.equal(state.items.length, 0);
  assert.ok(state.warnings.some((w) => w.includes("成交额")), "should warn about missing amount");
});

test("resolveHeatmapState: partial amount coverage → partial status", () => {
  const env = makeEnvelope({
    data: {
      type: "industry",
      total: 3,
      ranked_count: 3,
      unknown_count: 0,
      top: [],
      bottom: [],
      amount_top: [
        makeBoard({ code: "A", name: "有成交额", amount: 2e8 }),
        makeBoard({ code: "B", name: "无成交额", amount: null }),
      ],
    },
  });
  const state = resolveHeatmapState(env, false, false);
  assert.equal(state.status, "partial");
  assert.equal(state.items.length, 1, "only boards with valid amount shown");
  assert.equal(state.validAmountCount, 1);
});
