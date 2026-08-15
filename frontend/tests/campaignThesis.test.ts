/**
 * P0-CT1：campaignThesis 纯逻辑单测（无 I/O，不 import api.ts）。
 *
 * 覆盖：
 * - STRATEGY_HORIZON_RANGES 与 backend 逐字一致
 * - defaultHorizonForStrategy 默认区间
 * - canConfirmFormalThesis 确认门（formal_state / status / core_claims 3-5 /
 *   strategy / expected_horizon 结构与存在性）
 * - selectCampaignThesisCandidates 过滤（stock+code 精确、非 archived）与排序（新到旧）、
 *   不自动选唯一权威
 */
import assert from "node:assert/strict";
import test from "node:test";

import type { ExpectedHorizon, InvestmentThesis, ThesisStrategy } from "../src/lib/api/types.ts";
import {
  STRATEGY_HORIZON_RANGES,
  canConfirmFormalThesis,
  defaultHorizonForStrategy,
  selectCampaignThesisCandidates,
} from "../src/lib/campaignThesis.ts";

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

let seq = 0;

function makeThesis(overrides: Partial<InvestmentThesis> = {}): InvestmentThesis {
  seq += 1;
  return {
    id: `thesis_${seq}`,
    subject_type: "stock",
    subject_id: "600519",
    market: "CN",
    title: "测试逻辑",
    summary: "摘要",
    status: "active",
    core_claims: ["c1", "c2", "c3", "c4"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    created_at: "2026-08-01T00:00:00.000Z",
    updated_at: "2026-08-10T00:00:00.000Z",
    current_revision: 1,
    formal_state: "draft",
    formalization_started_at: "2026-08-05T00:00:00.000Z",
    confirmed_at: null,
    frozen_at: null,
    frozen_revision: null,
    archived_at: null,
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 5, max: 45, anchor: "FREEZE_AT" },
    free_notes: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// STRATEGY_HORIZON_RANGES
// ---------------------------------------------------------------------------

test("STRATEGY_HORIZON_RANGES 与 backend 逐字一致", () => {
  assert.deepEqual(STRATEGY_HORIZON_RANGES, {
    SHORT: [1, 10],
    SWING: [5, 45],
    MEDIUM: [40, 252],
  });
});

// ---------------------------------------------------------------------------
// defaultHorizonForStrategy
// ---------------------------------------------------------------------------

test("defaultHorizonForStrategy 返回策略完整允许范围 + 固定 unit/anchor", () => {
  const cases: Array<[ThesisStrategy, number, number]> = [
    ["SHORT", 1, 10],
    ["SWING", 5, 45],
    ["MEDIUM", 40, 252],
  ];
  for (const [strategy, min, max] of cases) {
    const horizon = defaultHorizonForStrategy(strategy);
    assert.deepEqual(horizon, { unit: "TRADING_DAY", min, max, anchor: "FREEZE_AT" });
  }
});

// ---------------------------------------------------------------------------
// canConfirmFormalThesis：确认门
// ---------------------------------------------------------------------------

test("确认门：draft + active + 3-5 claims + strategy + 合法 horizon → true", () => {
  assert.equal(canConfirmFormalThesis(makeThesis()), true);
});

test("确认门：formal_state 非 draft（null/confirmed/frozen）→ false", () => {
  assert.equal(canConfirmFormalThesis(makeThesis({ formal_state: null })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({ formal_state: "confirmed" })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({ formal_state: "frozen" })), false);
});

test("确认门：legacy 行缺失 formal 字段（undefined）→ false", () => {
  const legacy = makeThesis({
    formal_state: undefined as unknown as null,
    strategy: undefined as unknown as null,
    expected_horizon: undefined as unknown as null,
  });
  assert.equal(canConfirmFormalThesis(legacy), false);
});

test("确认门：status 非 active → false", () => {
  assert.equal(canConfirmFormalThesis(makeThesis({ status: "weakened" })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({ status: "invalidated" })), false);
});

test("确认门：core_claims 数量边界（2/6 拒绝，3/5 通过）", () => {
  assert.equal(canConfirmFormalThesis(makeThesis({ core_claims: ["a", "b"] })), false);
  assert.equal(
    canConfirmFormalThesis(makeThesis({ core_claims: ["a", "b", "c", "d", "e", "f"] })),
    false,
  );
  assert.equal(canConfirmFormalThesis(makeThesis({ core_claims: ["a", "b", "c"] })), true);
  assert.equal(
    canConfirmFormalThesis(makeThesis({ core_claims: ["a", "b", "c", "d", "e"] })),
    true,
  );
});

test("确认门：strategy 缺失（null）→ false", () => {
  assert.equal(canConfirmFormalThesis(makeThesis({ strategy: null })), false);
});

test("确认门：expected_horizon 缺失（null）→ false", () => {
  assert.equal(canConfirmFormalThesis(makeThesis({ expected_horizon: null })), false);
});

test("确认门：expected_horizon 结构非法 → false", () => {
  const base = makeThesis();
  const withUnit = (unit: string, anchor?: string, min?: number, max?: number): ExpectedHorizon => ({
    unit: unit as ExpectedHorizon["unit"],
    anchor: (anchor ?? "FREEZE_AT") as ExpectedHorizon["anchor"],
    min: min ?? 1,
    max: max ?? 2,
  });
  assert.equal(canConfirmFormalThesis(makeThesis({ expected_horizon: withUnit("CALENDAR_DAY") })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({ expected_horizon: withUnit("TRADING_DAY", "NOW") })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({ expected_horizon: withUnit("TRADING_DAY", "FREEZE_AT", 0) })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({ expected_horizon: withUnit("TRADING_DAY", "FREEZE_AT", 5, 4) })), false);
});

test("确认门：expected_horizon 必须落在对应策略范围内", () => {
  assert.equal(canConfirmFormalThesis(makeThesis({
    strategy: "SHORT",
    expected_horizon: { unit: "TRADING_DAY", min: 1, max: 11, anchor: "FREEZE_AT" },
  })), false);
  assert.equal(canConfirmFormalThesis(makeThesis({
    strategy: "MEDIUM",
    expected_horizon: { unit: "TRADING_DAY", min: 39, max: 252, anchor: "FREEZE_AT" },
  })), false);
});

test("确认门：多个条件同时缺失 → false", () => {
  assert.equal(
    canConfirmFormalThesis(
      makeThesis({ formal_state: null, status: "weakened", strategy: null, expected_horizon: null }),
    ),
    false,
  );
});

// ---------------------------------------------------------------------------
// selectCampaignThesisCandidates：候选过滤 / 排序 / 不自动选
// ---------------------------------------------------------------------------

test("候选：只保留 stock 且 subject_id 与 code 精确一致", () => {
  const hit = makeThesis({ subject_type: "stock", subject_id: "600519" });
  const prefix = makeThesis({ subject_type: "stock", subject_id: "6005190" });
  const sector = makeThesis({ subject_type: "sector", subject_id: "600519" });
  const result = selectCampaignThesisCandidates([sector, prefix, hit], "600519");
  assert.deepEqual(result.map((t) => t.id), [hit.id]);
});

test("候选：排除 archived", () => {
  const live = makeThesis({ id: "live", status: "active" });
  const archived = makeThesis({ id: "archived", status: "archived" });
  const result = selectCampaignThesisCandidates([archived, live], "600519");
  assert.deepEqual(result.map((t) => t.id), ["live"]);
});

test("候选：按 updated_at 新到旧排序", () => {
  const old = makeThesis({ id: "old", updated_at: "2026-08-01T00:00:00.000Z" });
  const mid = makeThesis({ id: "mid", updated_at: "2026-08-05T00:00:00.000Z" });
  const newest = makeThesis({ id: "new", updated_at: "2026-08-10T00:00:00.000Z" });
  const result = selectCampaignThesisCandidates([old, newest, mid], "600519");
  assert.deepEqual(result.map((t) => t.id), ["new", "mid", "old"]);
});

test("候选：唯一候选仍返回数组，不自动选权威", () => {
  const only = makeThesis({ id: "only" });
  const result = selectCampaignThesisCandidates([only], "600519");
  assert.ok(Array.isArray(result));
  assert.equal(result.length, 1);
  assert.equal(result[0].id, "only");
});

test("候选：无匹配 / 空输入 → 空数组", () => {
  assert.deepEqual(selectCampaignThesisCandidates([makeThesis({ subject_id: "000001" })], "600519"), []);
  assert.deepEqual(selectCampaignThesisCandidates([], "600519"), []);
});

test("候选：不修改输入数组顺序（纯函数）", () => {
  const old = makeThesis({ id: "old", updated_at: "2026-08-01T00:00:00.000Z" });
  const newest = makeThesis({ id: "new", updated_at: "2026-08-10T00:00:00.000Z" });
  const input = [old, newest];
  selectCampaignThesisCandidates(input, "600519");
  assert.deepEqual(input.map((t) => t.id), ["old", "new"]);
});
