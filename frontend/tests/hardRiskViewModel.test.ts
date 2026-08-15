/**
 * P0-HR1 Hard Risk view-model 契约测试。
 *
 * 以 backend/hard_risk_contract.py 的 LEGAL_STATE_EVALUATION_PAIRS 为唯一
 * authority（不测试自己发明的宽松 frontend contract）：
 *
 * A. CLEAR + EVALUATED + nonempty authority refs      → safe green
 * B. CONFIRMED + EVALUATED + refs + nonempty reasons  → danger
 * C. UNKNOWN + UNKNOWN + nonempty reasons             → unknown
 * D. UNKNOWN + ERROR + nonempty reasons               → evaluation error
 * E. NOT_EVALUATED + NOT_EVALUATED + nonempty reasons → not evaluated
 *
 * 其它全部（missing / null / illegal enum / illegal pair /
 * CLEAR 或 CONFIRMED 缺 evaluation / 缺 authority refs / 非 CLEAR 缺 reasons）
 * → fail closed unavailable，绝不 safe green、绝不声称已确认。
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  HARD_RISK_EVALUATIONS,
  HARD_RISK_STATES,
  LEGAL_STATE_EVALUATION_PAIRS,
  hardRiskDisplay,
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
  assert.equal(view.statusLabel, "Hard Risk 状态未知", `${label}: 必须 fail closed 为未知`);
}

// ---------------------------------------------------------------------------
// A. CLEAR 正证明门
// ---------------------------------------------------------------------------

test("A1：CLEAR only（无 evaluation）→ fail closed，绝不安全", () => {
  assertUnavailable(hardRiskDisplay({ hard_risk_state: "CLEAR" }), "CLEAR only");
});

test("A2：CLEAR + EVALUATED + refs → safe green", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:positive-clear"],
  });
  assert.equal(view.tone, "safe");
  assert.equal(view.showSafeGreen, true);
  assert.equal(view.statusLabel, "已确认无 Hard Risk");
});

test("A3：CLEAR + EVALUATED + no refs → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CLEAR",
      hard_risk_evaluation: "EVALUATED",
    }),
    "CLEAR+EVALUATED no refs",
  );
});

test("A4：CLEAR + missing evaluation + refs → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CLEAR",
      authority_refs: ["hard-risk:ref-without-evaluation"],
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
        authority_refs: ["hard-risk:ref"],
      }),
      `CLEAR + ${evaluation}`,
    );
  }
});

// ---------------------------------------------------------------------------
// B. CONFIRMED 正证明门
// ---------------------------------------------------------------------------

test("B1：CONFIRMED + EVALUATED + refs + reasons → danger 已确认", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:confirmed-authority"],
    reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  assert.equal(view.tone, "danger");
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "已确认 Hard Risk");
});

test("B2：CONFIRMED missing evaluation → fail closed（证据不足不声称已确认）", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      authority_refs: ["hard-risk:ref"],
      reason_codes: ["HARD_RISK_CONFIRMED"],
    }),
    "CONFIRMED missing evaluation",
  );
});

test("B3：CONFIRMED + EVALUATED + no refs → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      hard_risk_evaluation: "EVALUATED",
      reason_codes: ["HARD_RISK_CONFIRMED"],
    }),
    "CONFIRMED+EVALUATED no refs",
  );
});

test("B4：CONFIRMED + EVALUATED + refs + no reasons → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "CONFIRMED",
      hard_risk_evaluation: "EVALUATED",
      authority_refs: ["hard-risk:ref"],
    }),
    "CONFIRMED no reasons",
  );
});

test("B5：CONFIRMED 文案绝不包含自动交易指令词", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:confirmed-authority"],
    reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  assertNoAutoExitText(view.statusLabel);
  assertNoAutoExitText(view.description);
  assert.match(view.description, /重新审查/);
  assert.match(view.description, /Action Envelope/);
});

// ---------------------------------------------------------------------------
// C/D/E. UNKNOWN / ERROR / NOT_EVALUATED
// ---------------------------------------------------------------------------

test("C1：UNKNOWN + UNKNOWN + reasons → unknown 不绿", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
  });
  assert.equal(view.tone, "unknown");
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "Hard Risk 状态未知");
});

test("C2：UNKNOWN missing evaluation → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "UNKNOWN",
      reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
    }),
    "UNKNOWN missing evaluation",
  );
});

test("C3：UNKNOWN + UNKNOWN + no reasons → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "UNKNOWN",
      hard_risk_evaluation: "UNKNOWN",
    }),
    "UNKNOWN+UNKNOWN no reasons",
  );
});

test("D1：UNKNOWN + ERROR + reasons → 明确评估失败，不得 silently green", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "ERROR",
    reason_codes: ["HARD_RISK_EVALUATION_ERROR"],
  });
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.tone, "unknown");
  assert.equal(view.statusLabel, "Hard Risk 评估失败");
  assert.equal(view.evaluationLabel, "ERROR");
});

test("D2：UNKNOWN + ERROR + no reasons → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "UNKNOWN",
      hard_risk_evaluation: "ERROR",
    }),
    "UNKNOWN+ERROR no reasons",
  );
});

test("E1：NOT_EVALUATED + NOT_EVALUATED + reasons → 尚未评估 不绿", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "NOT_EVALUATED",
    hard_risk_evaluation: "NOT_EVALUATED",
    reason_codes: ["HARD_RISK_NOT_EVALUATED"],
  });
  assert.equal(view.tone, "muted");
  assert.equal(view.showSafeGreen, false);
  assert.equal(view.statusLabel, "尚未完成 Hard Risk 评估");
});

test("E2：NOT_EVALUATED missing evaluation → fail closed", () => {
  assertUnavailable(
    hardRiskDisplay({
      hard_risk_state: "NOT_EVALUATED",
      reason_codes: ["HARD_RISK_NOT_EVALUATED"],
    }),
    "NOT_EVALUATED missing evaluation",
  );
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
        reason_codes: ["SOME_REASON"],
        authority_refs: ["hard-risk:ref"],
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
      authority_refs: ["hard-risk:ref"],
      reason_codes: ["SOME_REASON"],
    });
    assert.equal(view.showSafeGreen, false);
    assert.equal(view.statusLabel, "Hard Risk 状态未知");
  }
  for (const evaluation of [undefined, null, "SOMETIMES"]) {
    const view = hardRiskDisplay({
      hard_risk_state: "CLEAR",
      hard_risk_evaluation: evaluation,
      authority_refs: ["hard-risk:ref"],
    });
    assert.equal(view.showSafeGreen, false);
    assert.equal(view.statusLabel, "Hard Risk 状态未知");
  }
});

// ---------------------------------------------------------------------------
// reason codes / provenance 透传（合法 pair 下）
// ---------------------------------------------------------------------------

test("reason codes：合法 pair 下原样透传，不解释不推断", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    reason_codes: ["HARD_RISK_INPUT_UNKNOWN", "REVIEW_BY_REACHED"],
  });
  assert.deepEqual(view.reasonCodes, ["HARD_RISK_INPUT_UNKNOWN", "REVIEW_BY_REACHED"]);
});

test("authority refs：顶层透传", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:lake-snapshot-1"],
  });
  assert.deepEqual(view.authorityRefs, ["hard-risk:lake-snapshot-1"]);
});

test("authority refs：顶层缺失时 fallback explainability", () => {
  const view = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    reason_codes: ["HARD_RISK_CONFIRMED"],
    explainability: { authority_refs: ["hard-risk:di1-authority"] },
  });
  assert.equal(view.tone, "danger");
  assert.deepEqual(view.authorityRefs, ["hard-risk:di1-authority"]);
});

// ---------------------------------------------------------------------------
// sibling 隔离 / payload-driven
// ---------------------------------------------------------------------------

test("sibling Campaign：同一 security 不同策略的 hard risk 互不污染", () => {
  const swing = hardRiskDisplay({
    hard_risk_state: "CONFIRMED",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:swing"],
    reason_codes: ["HARD_RISK_CONFIRMED"],
  });
  const short = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:short"],
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
    reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
  });
  const second = hardRiskDisplay({
    hard_risk_state: "UNKNOWN",
    hard_risk_evaluation: "UNKNOWN",
    reason_codes: ["HARD_RISK_INPUT_UNKNOWN"],
  });
  assert.deepEqual(second, first, "相同 payload 必须产生相同视图");

  const refreshed = hardRiskDisplay({
    hard_risk_state: "CLEAR",
    hard_risk_evaluation: "EVALUATED",
    authority_refs: ["hard-risk:now-clear"],
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
