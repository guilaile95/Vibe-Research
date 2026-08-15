import assert from "node:assert/strict";
import test from "node:test";

// P0-AB2 账户初始化纯契约测试（A–J，K/L 由 Playwright E2E 覆盖）：
// A 非 canonical + POSITION_LEDGER_NOT_BOOTSTRAPPED → 显示激活卡
// B 其它 noncanonical 原因 → 不显示 commit flow
// C legacy portfolio → 仅预填
// D ledger_start_at 空 → Preview 禁用
// E 未 Preview → commit 不可用（绝不越过 preview 调 commit）
// F Preview 后修改表单 → PREVIEW_INVALIDATED + commit 禁用
// G Preview + 显式确认 → commit 可用
// H Commit payload == 产生当前 Preview 的同一份 input payload
// I 不存在把 LEGACY_POSITION_OPENING 描述成 BUY 的文案
// J 409 → 无 overwrite/reset 动作

import {
  POSITION_LEDGER_NOT_BOOTSTRAPPED,
  PREFILL_NOTICE,
  ANTI_BUY_NOTICE,
  CONFIRM_CHECKBOX_LABEL,
  BOOTSTRAP_CONFLICT_MESSAGE,
  shouldShowBootstrapCard,
  prefillPositionsFromPortfolio,
  parseBootstrapInput,
  bootstrapInputsEqual,
  previewInvalidated,
  canCommitBootstrap,
  canPreviewBootstrap,
  commitPayload,
  describeBootstrapCommitError,
} from "../src/lib/positionBootstrap.ts";
import type {
  PortfolioData,
  PositionBootstrapInput,
  PositionBootstrapPreview,
} from "../src/lib/api/types.ts";

const FORM = {
  ledger_start_at: "2026-08-01",
  opening_cash: "100000",
  note: "",
  positions: [
    { code: "001896", name: "豫能控股", shares: "1000", cost_basis: "3.5" },
    { code: "002031", name: "", shares: "500", cost_basis: "" },
  ],
};

const INPUT: PositionBootstrapInput = {
  ledger_start_at: "2026-08-01",
  opening_cash: 100000,
  positions: [
    { code: "001896", name: "豫能控股", shares: 1000, cost_basis: 3.5 },
    { code: "002031", shares: 500 },
  ],
};

const PREVIEW: PositionBootstrapPreview = {
  preview: true,
  validation: "ok",
  opening: {
    event_id: "aev_open",
    event_type: "ACCOUNT_OPENING",
    opening_cash: 100000,
    ledger_start_at: "2026-07-31T16:00:00.000000+00:00",
    historical_trades: "UNKNOWN",
    provenance: "MANUAL",
    created_at: "2026-08-15T00:00:00.000000+00:00",
  },
  positions: [
    {
      event_id: "aev_p1",
      event_type: "LEGACY_POSITION_OPENING",
      code: "001896",
      name: "豫能控股",
      shares: 1000,
      cost_basis: 3.5,
      origin: "PRE_VIBE",
      acquired_before_vibe: 1,
      historical_trades: "UNKNOWN",
      provenance: "MANUAL",
      created_at: "2026-08-15T00:00:00.000000+00:00",
    },
    {
      event_id: "aev_p2",
      event_type: "LEGACY_POSITION_OPENING",
      code: "002031",
      name: null,
      shares: 500,
      cost_basis: null,
      origin: "PRE_VIBE",
      acquired_before_vibe: 1,
      historical_trades: "UNKNOWN",
      provenance: "MANUAL",
      created_at: "2026-08-15T00:00:00.000000+00:00",
    },
  ],
};

function gate(overrides: Record<string, unknown> = {}) {
  return {
    preview: PREVIEW,
    previewedInput: INPUT,
    currentInput: INPUT,
    confirmed: false,
    ...overrides,
  };
}

test("A: POSITION_LEDGER_NOT_BOOTSTRAPPED 显示 Bootstrap Card", () => {
  assert.equal(
    shouldShowBootstrapCard({
      canonical: false,
      reason_codes: ["POSITION_LEDGER_NOT_BOOTSTRAPPED"],
    }),
    true,
  );
  assert.equal(
    shouldShowBootstrapCard({
      canonical: false,
      reason_codes: ["OTHER_REASON", "POSITION_LEDGER_NOT_BOOTSTRAPPED"],
    }),
    true,
  );
});

test("B: 其它 noncanonical 原因不显示 Bootstrap commit flow", () => {
  assert.equal(
    shouldShowBootstrapCard({ canonical: false, reason_codes: ["OTHER_REASON"] }),
    false,
  );
  assert.equal(
    shouldShowBootstrapCard({ canonical: false, reason_codes: [] }),
    false,
  );
  assert.equal(
    shouldShowBootstrapCard({ canonical: true, reason_codes: [] }),
    false,
  );
});

test("C: legacy portfolio 只作为预填（纯映射，无副作用）", () => {
  const portfolio: PortfolioData = {
    holdings: [
      {
        code: "001896",
        name: "豫能控股",
        price: null,
        shares: 1000,
        cost: 3.5,
        market_value: null,
        pnl: null,
        pnl_pct: null,
      },
      {
        code: "002031",
        name: "巨轮智能",
        price: null,
        shares: 500,
        cost: 12,
        market_value: null,
        pnl: null,
        pnl_pct: null,
      },
    ],
    totals: { market_value: null, cost: 9500, pnl: null, pnl_pct: null },
    closed: [],
    realized_pnl: 0,
    updated: "",
    last_refresh: null,
  };
  const rows = prefillPositionsFromPortfolio(portfolio);
  assert.deepEqual(rows, [
    { code: "001896", name: "豫能控股", shares: "1000", cost_basis: "3.5" },
    { code: "002031", name: "巨轮智能", shares: "500", cost_basis: "12" },
  ]);
  assert.deepEqual(prefillPositionsFromPortfolio(null), []);
  assert.deepEqual(prefillPositionsFromPortfolio(undefined), []);
  assert.deepEqual(
    prefillPositionsFromPortfolio({ ...portfolio, holdings: [] }),
    [],
  );
});

test("D: ledger_start_at 空 → Preview 禁用", () => {
  const parsed = parseBootstrapInput({ ...FORM, ledger_start_at: "" });
  assert.equal(parsed, null);
  assert.equal(canPreviewBootstrap(parsed), false);
  // 非法日期同样拒绝
  assert.equal(
    canPreviewBootstrap(parseBootstrapInput({ ...FORM, ledger_start_at: "2026/08/01" })),
    false,
  );
  assert.equal(canPreviewBootstrap(parseBootstrapInput(FORM)), true);
});

test("E: 未 Preview 时 commit 门关闭（绝不越过 preview 直接 commit）", () => {
  const state = gate({ preview: null, previewedInput: null, confirmed: true });
  assert.equal(canCommitBootstrap(state), false);
  assert.equal(commitPayload(state), null);
});

test("F: Preview 后修改表单 → PREVIEW_INVALIDATED + commit 禁用", () => {
  const edited = {
    ...INPUT,
    positions: [{ ...INPUT.positions[0], shares: 999 }, INPUT.positions[1]],
  };
  const state = gate({ currentInput: edited, confirmed: true });
  assert.equal(previewInvalidated(state), true);
  assert.equal(canCommitBootstrap(state), false);
  assert.equal(commitPayload(state), null);
});

test("G: Preview + 输入一致 + 显式确认 → commit 可用", () => {
  assert.equal(canCommitBootstrap(gate({ confirmed: false })), false);
  assert.equal(canCommitBootstrap(gate({ confirmed: true })), true);
  // 输入不一致即使确认也禁用
  assert.equal(
    canCommitBootstrap(gate({
      confirmed: true,
      currentInput: { ...INPUT, opening_cash: 1 },
    })),
    false,
  );
});

test("H: Commit payload 必须等于产生当前 Preview 的同一份 input payload", () => {
  const state = gate({ confirmed: true });
  const payload = commitPayload(state);
  assert.equal(payload, INPUT, "commit 必须复用 previewed input 本体");
  // 表单被改成相等值但非同一份 → 仍以 previewed 为准（本实现直接返回 previewedInput）
  const equalButDifferent = parseBootstrapInput(FORM);
  assert.ok(equalButDifferent && bootstrapInputsEqual(equalButDifferent, INPUT));
  const payload2 = commitPayload(gate({
    confirmed: true,
    currentInput: equalButDifferent,
  }));
  assert.equal(payload2, INPUT);
});

test("I: 不存在把 LEGACY_POSITION_OPENING 描述成 BUY 的文案", () => {
  // 预填提示绝不声称这是买入记录
  assert.ok(!PREFILL_NOTICE.includes("买入"));
  // 显式否定声明存在（绝不伪造 BUY）
  assert.ok(ANTI_BUY_NOTICE.includes("不会把现有持仓伪造成 BUY"));
  assert.ok(CONFIRM_CHECKBOX_LABEL.includes("不重建为历史 BUY"));
  // 事实类型常量来自 backend（LEGACY_POSITION_OPENING），前端不造 BUY 文案
  assert.ok(!CONFIRM_CHECKBOX_LABEL.includes("历史买入"));
});

test("J: 409 → 用户可读提示且无 overwrite/reset 动作", () => {
  const desc = describeBootstrapCommitError(
    Object.assign(new Error("账本已初始化，禁止重复 bootstrap"), { status: 409 }),
  );
  assert.equal(desc.conflict, true);
  assert.equal(desc.message, BOOTSTRAP_CONFLICT_MESSAGE);
  for (const forbidden of ["覆盖", "重置", "overwrite", "reset"]) {
    assert.ok(
      !BOOTSTRAP_CONFLICT_MESSAGE.toLowerCase().includes(forbidden.toLowerCase()),
      `409 提示不得包含动作文案: ${forbidden}`,
    );
  }
  // 422 如实透传 backend detail
  const invalid = describeBootstrapCommitError(
    Object.assign(new Error("ledger_start_at 必须是非空字符串"), { status: 422 }),
  );
  assert.equal(invalid.conflict, false);
  assert.equal(invalid.message, "ledger_start_at 必须是非空字符串");
});
