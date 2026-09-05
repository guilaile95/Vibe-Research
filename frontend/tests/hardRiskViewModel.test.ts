/**
 * P0-HR1 Hard Risk view-model 契约测试。
 *
 * 以 backend/hard_risk_contract.py 的 LEGAL_STATE_EVALUATION_PAIRS 为唯一
 * authority（不测试自己发明的宽松 frontend contract），且只消费 Hard Risk
 * 专属 payload 字段：
 *
 *   hard_risk_state / hard_risk_evaluation /
 *   hard_risk_reason_codes / hard_risk_authority_refs
 *
 * 严禁 generic fallback：
 *   - Decision Inbox item.reason_codes（Campaign-level generic）
 *   - item.authority_refs / explainability.authority_refs
 *     （generic projection provenance，可能含 Critical Data / Thesis /
 *     Decision / Hard Risk）
 *
 * A. CLEAR + EVALUATED + nonempty hard_risk_authority_refs      → safe green
 * B. CONFIRMED + EVALUATED + refs + nonempty hard_risk_reason_codes → danger
 * C. UNKNOWN + UNKNOWN + nonempty hard_risk_reason_codes        → unknown
 * D. UNKNOWN + ERROR + nonempty hard_risk_reason_codes          → evaluation error
 * E. NOT_EVALUATED + NOT_EVALUATED + nonempty hard_risk_reason_codes
 *                                                               → not evaluated
 * 其它全部 → fail closed unavailable。
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  HARD_RISK_EVALUATIONS,
  HARD_RISK_STATES,
  LEGAL_STATE_EVALUATION_PAIRS,
  hardRiskDisplay,
  type HardRiskInput,
} from "../src/lib/hardRiskViewModel.ts";

const FORBIDDEN = ["卖出", "退出", "清仓", "EXIT", "SELL"];

function assertNoAutoExitText(text: string) {
  for (const token of FORBIDDEN) {
    assert.equal(text.includes(token), false, `CONFIRMED 文案不得包含「${token}」`);
  }
}

function assertUnavailable(view: ReturnType<typeof hardRiskDisplay>, label: string) {
  assert.equal(view.showSafeGreen, false, `${label}: 不得显示安全绿色`);
  assert.notEqual(view.tone, "safe", `${label}: tone 不得为 safe`);
  assert.equal(view.statusLabel, "硬风险状态未知", `${label}: 必须 fail closed 为未知`);
}

// ---------------------------------------------------------------------------
// A. CLEAR 正证明门（只认 hard_risk_authority_refs）
// ---------------------------------------------------------------------------

test("A1：CLEAR only（无 evaluation）→ fail closed，绝不安全", () => {
  assertUnavailable(hardRiskDisplay({ hard_risk_state: "CLEAR" }), "CLEAR only");
});

test("A2：CLEAR + EVALUATED + 专属 refs → safe green", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:positive-clear"],
  });
  assert.equal(view.tone, "safe");
  assert.equal(view.showSafeGreen, true);
  assert.equal(view.statusLabel, "已确认无硬风险");
});

test("A3：CLEAR + EVALUATED + 无专属 refs → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CLEAR",
      hard_risk_evaluation: "EVALUATED",
    }),
    "CLEAR+EVALUATED no refs",
  );
});

test("A4：CLEAR + missing evaluation + 专属 refs → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CLEAR",
      hard_risk_authority_refs: ["hard-risk:ref-without-evaluation"],
    }),
    "CLEAR missing evaluation",
  );
});

test("A5：CLEAR + 非法 evaluation pair → fail closed", () => {
  for (const evaluation of ["UNKNOWN", "NOT_EVALUATED", "ERROR"]) {
    assertUnavailable(
      hardRiskDisplay({
        hard_risk_state: "CLEAR",
        hard_risk_evaluation: evaluation,
        hard_risk_authority_refs: ["hard-risk:ref"],
      }),
      `CLEAR + ${evaluation}`,
    );
  }
});

// ---------------------------------------------------------------------------
// B. CONFIRMED 正证明门
// ---------------------------------------------------------------------------

test("B1：CONFIRMED + EVALUATED + 专属 refs + 专属 reasons → danger 已确认", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:confirmed-authority"],
    hard_risk_reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  assert.equal(view.tone, "danger");
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "已确认硬风险");
});

test("B2：CONFIRMED missing evaluation → fail closed（证据不足不声称已确认）", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      hard_risk_authority_refs: ["hard-risk:ref"],
      hard_risk_reason_codes: ["HARD_RISK_CONFIRMED"],
    }),
    "CONFIRMED missing evaluation",
  );
});

test("B3：CONFIRMED + EVALUATED + 无专属 refs → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      hard_risk_evaluation: "EVALUATED",
      hard_risk_reason_codes: ["HARD_RISK_CONFIRMED"],
    }),
    "CONFIRMED+EVALUATED no refs",
  );
});

test("B4：CONFIRMED + EVALUATED + 专属 refs + 无专属 reasons → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      hard_risk_evaluation: "EVALUATED",
      hard_risk_authority_refs: ["hard-risk:ref"],
    }),
    "CONFIRMED no reasons",
  );
});

test("B5：CONFIRMED 文案绝不包含自动交易指令词", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:confirmed-authority"],
    hard_risk_reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  assertNoAutoExitText(view.statusLabel);
  assertNoAutoExitText(view.description);
  assert.match(view.description, /重新审查/);
  assert.match(view.description, /正式决策和可执行操作/);
});

// ---------------------------------------------------------------------------
// C/D/E. UNKNOWN / ERROR / NOT_EVALUATED
// ---------------------------------------------------------------------------

test("C1：UNKNOWN + UNKNOWN + 专属 reasons → unknown 不绿", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    hard_risk_reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
  });
  assert.equal(view.tone, "unknown");
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "硬风险状态未知");
});

test("C2：UNKNOWN missing evaluation → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "UNKNOWN",
      hard_risk_reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
    }),
    "UNKNOWN missing evaluation",
  );
});

test("C3：UNKNOWN + UNKNOWN + 无专属 reasons → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "UNKNOWN",
      hard_risk_evaluation: "UNKNOWN",
    }),
    "UNKNOWN+UNKNOWN no reasons",
  );
});

test("D1：UNKNOWN + ERROR + 专属 reasons → 明确评估失败，不得 silently green", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "ERROR",
    hard_risk_reason_codes: ["HARD_RISK_EVALUATION_ERROR"],
  });
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.tone, "unknown");
  assert.equal(view.statusLabel, "硬风险读取失败");
  assert.equal(view.evaluationLabel, "读取失败");
});

test("D2：UNKNOWN + ERROR + 无专属 reasons → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "UNKNOWN",
      hard_risk_evaluation: "ERROR",
    }),
    "UNKNOWN+ERROR no reasons",
  );
});

test("E1：NOT_EVALUATED + NOT_EVALUATED + 专属 reasons → 尚未评估 不绿", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "NOT_EVALUATED",
    hard_risk_evaluation: "NOT_EVALUATED",
    hard_risk_reason_codes: ["HARD_RISK_NOT_EVALUATED"],
  });
  assert.equal(view.tone, "muted");
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "尚未完成硬风险评估");
});

test("E2：NOT_EVALUATED missing evaluation → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "NOT_EVALUATED",
      hard_risk_reason_codes: ["HARD_RISK_NOT_EVALUATED"],
    }),
    "NOT_EVALUATED missing evaluation",
  );
});

// ---------------------------------------------------------------------------
// 关键 anti-contamination：generic Decision Inbox 数据严禁充当 Hard Risk
// 专属 evidence（工作单 §5 A-E）
// ---------------------------------------------------------------------------

test("anti-A：generic authority 不得证明 CLEAR（explainability refs 不绿）", () => {
  // hard_risk_authority_refs = []，generic explainability 有 refs →
  // view-model 根本收不到 generic refs（输入形状不允许），必须 fail closed。
  const view = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: [],
    // @ts-expect-error 输入形状不允许 generic 字段——防止误传的编译期护栏
    explainability: { authority_refs: ["critical-data:proof"] },
  });
  assertUnavailable(view, "generic ref cannot prove CLEAR");
  assert.deepEqual(view.authorityRefs, []);
});

test("anti-B：generic reason 不得证明 CONFIRMED（item.reason_codes 不生效）", () => {
  // hard_risk_reason_codes = []，generic reason_codes 有 HARD_RISK_CONFIRMED →
  // 不得显示 confirmed authority state，必须 fail closed。
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:proof"],
    hard_risk_reason_codes: [],
    // @ts-expect-error 输入形状不允许 generic 字段——防止误传的编译期护栏
    reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  assertUnavailable(view, "generic reason cannot prove CONFIRMED");
  assert.notEqual(view.statusLabel, "已确认硬风险");
  assert.deepEqual(view.reasonCodes, []);
});

test("anti-C：专属 evidence 正常显示（prefixed payload）", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:proof"],
    hard_risk_reason_codes: ["DELISTING_RISK_CONFIRMED"],
  });
  assert.equal(view.tone, "danger");
  assert.equal(view.statusLabel, "已确认硬风险");
  assert.deepEqual(view.reasonCodes, ["DELISTING_RISK_CONFIRMED"]);
  assert.deepEqual(view.authorityRefs, ["hard-risk:proof"]);
});

test("anti-D：reason list 只承载 hard_risk_reason_codes", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    hard_risk_reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
    // @ts-expect-error 输入形状不允许 generic 字段
    reason_codes: ["CRITICAL_DATA_BLOCKED", "THESIS_MISSING"],
  });
  assert.deepEqual(view.reasonCodes, ["HARD_RISK_INPUT_UNKNOWN"]);
});

test("anti-E：Authority 引用只承载 hard_risk_authority_refs", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:only"],
    // @ts-expect-error 输入形状不允许 generic 字段
    authority_refs: ["critical-data:ref", "thesis:ref"],
    // @ts-expect-error 输入形状不允许 generic 字段
    explainability: { authority_refs: ["critical-data:proof"] },
  });
  assert.deepEqual(view.authorityRefs, ["hard-risk:only"]);
});

// ---------------------------------------------------------------------------
// illegal pair / illegal enum / missing → fail closed
// ---------------------------------------------------------------------------

test("非法 pair：legal pairs 之外全部 fail closed", () => {
  const illegal: Array<[string, string]> = [
    ["CLEAR", "UNKNOWN"],
    ["CLEAR", "NOT_EVALUATED"],
    ["CONFIRMED", "ERROR"],
    ["CONFIRMED", "UNKNOWN"],
    ["NOT_EVALUATED", "EVALUATED"],
    ["NOT_EVALUATED", "UNKNOWN"],
    ["UNKNOWN", "EVALUATED"],
    ["UNKNOWN", "NOT_EVALUATED"],
  ];
  for (const [state, evaluation] of illegal) {
    assertUnavailable(
      hardRiskDisplay({
        hard_risk_state: state,
        hard_risk_evaluation: evaluation,
        hard_risk_reason_codes: ["SOME_REASON"],
        hard_risk_authority_refs: ["hard-risk:ref"],
      }),
      `${state} + ${evaluation}`,
    );
  }
});

test("missing：state / evaluation 缺失或非法枚举 → fail closed 不绿", () => {
  for (const state of [undefined, null, "MAYBE_RISK"]) {
    const view = hardRiskDisplay({
      hard_risk_state: state,
      hard_risk_evaluation: "EVALUATED",
      hard_risk_authority_refs: ["hard-risk:ref"],
      hard_risk_reason_codes: ["SOME_REASON"],
    });
    assert.equal(view.showSafeGreen, false);
    assert.equal(view.statusLabel, "硬风险状态未知");
  }
  for (const evaluation of [undefined, null, "SOMETIMES"]) {
    const view = hardRiskDisplay({
      hard_risk_state: "CLEAR",
      hard_risk_evaluation: evaluation,
      hard_risk_authority_refs: ["hard-risk:ref"],
    });
    assert.equal(view.showSafeGreen, false);
    assert.equal(view.statusLabel, "硬风险状态未知");
  }
});

// ---------------------------------------------------------------------------
// sibling 隔离 / payload-driven
// ---------------------------------------------------------------------------

test("sibling Campaign：同一 security 不同策略的 hard risk 互不污染", () => {
  const swing = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:swing"],
    hard_risk_reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  const short = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:short"],
  });
  assert.equal(swing.tone, "danger");
  assert.equal(short.tone, "safe");
  assert.equal(short.showSafeGreen, true);
  assert.deepEqual(swing.authorityRefs, ["hard-risk:swing"]);
  assert.deepEqual(short.authorityRefs, ["hard-risk:short"]);
});

test("payload-driven：相同 payload 稳定，输入变化输出变化（refresh 语义）", () => {
  const first = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    hard_risk_reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
  });
  const second = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    hard_risk_reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
  });
  assert.deepEqual(second, first, "相同 payload 必须产生相同视图");

  const refreshed = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    hard_risk_authority_refs: ["hard-risk:now-clear"],
  });
  assert.notEqual(refreshed.statusLabel, first.statusLabel);
  assert.equal(refreshed.showSafeGreen, true);
});

// ---------------------------------------------------------------------------
// 常量冻结：与 shared contract 逐字一致
// ---------------------------------------------------------------------------

test("状态常量与 shared contract 一致", () => {
  assert.deepEqual(HARD_RISK_STATES, ["CLEAR", "CONFIRMED", "UNKNOWN", "NOT_EVALUATED"]);
  assert.deepEqual(HARD_RISK_EVALUATIONS, ["EVALUATED", "UNKNOWN", "NOT_EVALUATED", "ERROR"]);
  assert.deepEqual(
    [...LEGAL_STATE_EVALUATION_PAIRS].sort(),
    [
      "CLEAR|EVALUATED",
      "CONFIRMED|EVALUATED",
      "NOT_EVALUATED|NOT_EVALUATED",
      "UNKNOWN|ERROR",
      "UNKNOWN|UNKNOWN",
    ],
  );
});
