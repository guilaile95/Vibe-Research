/**
 * P0-HR1 Hard Risk Decision Inbox 展示层（纯 view-model，零 I/O、零业务判定）。
 *
 * 铁律（与 shared Hard Risk contract v0.1 对齐）：
 * - 展示层绝不推断新的 Hard Risk —— 状态只来自 runtime payload 的
 *   hard_risk_state / hard_risk_evaluation。
 * - 只有 backend 显式给出 positive-proof CLEAR（hard_risk_state === "CLEAR"
 *   且 evaluation 不是 ERROR / UNKNOWN / NOT_EVALUATED）才显示安全绿色。
 *   missing / null / unknown / not evaluated / error 一律不绿。
 * - CONFIRMED 文案绝不包含卖出 / 退出 / 清仓 / EXIT / SELL：Hard Risk 只触发
 *   「重新审查 Decision / Action Envelope」，不构成任何自动交易指令。
 * - reason_codes / authority_refs 原样透传（纯 presentation），不把 reason code
 *   转换成新 formal authority。
 */

import type { HardRiskEvaluation, HardRiskState } from "./api/types";

export const HARD_RISK_STATES: readonly HardRiskState[] = [
  "CLEAR",
  "CONFIRMED",
  "UNKNOWN",
  "NOT_EVALUATED",
] as const;

export const HARD_RISK_EVALUATIONS: readonly HardRiskEvaluation[] = [
  "EVALUATED",
  "UNKNOWN",
  "NOT_EVALUATED",
  "ERROR",
] as const;

export type HardRiskTone = "danger" | "safe" | "unknown" | "muted";

export interface HardRiskInput {
  hard_risk_state?: string | null;
  hard_risk_evaluation?: string | null;
  reason_codes?: readonly string[] | null;
  authority_refs?: readonly string[] | null;
  /** 当前 DI1 projection 的 provenance 位置；顶层 authority_refs 优先。 */
  explainability?: { authority_refs?: readonly string[] | null } | null;
}

export interface HardRiskViewModel {
  /** 展示 tone；"safe" 只允许 positive-proof CLEAR。 */
  tone: HardRiskTone;
  statusLabel: string;
  description: string;
  /** 唯一允许的绿色安全态：显式 CLEAR 且 evaluation 一致。 */
  showSafeGreen: boolean;
  /** evaluation === "ERROR" 时展示失败标识，其余为 null。 */
  evaluationLabel: string | null;
  reasonCodes: readonly string[];
  authorityRefs: readonly string[];
}

function isState(value: string | null | undefined): value is HardRiskState {
  return value !== null && value !== undefined
    && (HARD_RISK_STATES as readonly string[]).includes(value);
}

function isEvaluation(
  value: string | null | undefined,
): value is HardRiskEvaluation {
  return value !== null && value !== undefined
    && (HARD_RISK_EVALUATIONS as readonly string[]).includes(value);
}

function collectAuthorityRefs(input: HardRiskInput): readonly string[] {
  const top = input.authority_refs ?? [];
  if (top.length > 0) return top;
  return input.explainability?.authority_refs ?? [];
}

const REASON_CLEAR = "CLEAR";

function base(
  input: HardRiskInput,
  overrides: Partial<HardRiskViewModel>,
): HardRiskViewModel {
  return {
    tone: "muted",
    statusLabel: "",
    description: "",
    showSafeGreen: false,
    evaluationLabel: null,
    reasonCodes: input.reason_codes ?? [],
    authorityRefs: collectAuthorityRefs(input),
    ...overrides,
  };
}

/** 非法 / 缺失输入的统一 fail-closed 视图（绝不伪装成安全）。 */
function unavailableView(input: HardRiskInput, reason: string): HardRiskViewModel {
  return base(input, {
    tone: "muted",
    statusLabel: "Hard Risk 状态未知",
    description: `${reason}，不能视为安全。`,
  });
}

/** 评估失败（contract (UNKNOWN, ERROR) 或任何 ERROR evaluation）→ 不绿。 */
function errorView(input: HardRiskInput): HardRiskViewModel {
  return base(input, {
    tone: "unknown",
    statusLabel: "Hard Risk 评估失败",
    description: "Hard Risk 评估失败或不可用，风险状态无法确定。请修复数据后重新评估，不能视为安全。",
    evaluationLabel: "ERROR",
  });
}

export function hardRiskDisplay(input: HardRiskInput): HardRiskViewModel {
  const state = input.hard_risk_state;
  const evaluation = input.hard_risk_evaluation;
  const validState = isState(state) ? state : null;
  const validEvaluation = isEvaluation(evaluation) ? evaluation : null;

  // ERROR 优先于状态判定：评估失败必须明确呈现，绝不 silently green。
  if (validEvaluation === "ERROR") {
    return errorView(input);
  }

  switch (validState) {
    case "CLEAR": {
      // positive-proof CLEAR：contract 只允许 (CLEAR, EVALUATED)。
      // evaluation 缺失时信任 DI1 已归一化的 CLEAR（LEGAL pair 保证其来源）；
      // evaluation 存在但非 EVALUATED 是非法组合 → fail closed。
      if (validEvaluation !== null && validEvaluation !== "EVALUATED") {
        return unavailableView(input, "Hard Risk 评估结果自相矛盾");
      }
      return base(input, {
        tone: "safe",
        statusLabel: "已确认无 Hard Risk",
        description: "后端已给出 positive-proof CLEAR，当前无已确认的 Hard Risk。这不免除后续重新评估。",
        showSafeGreen: true,
        reasonCodes: input.reason_codes ?? [REASON_CLEAR],
      });
    }
    case "CONFIRMED": {
      // 高优先级风险提示：只要求重新审查 Decision / Action Envelope，
      // 绝不表达任何自动交易指令（禁止出现卖出 / 退出 / 清仓 / EXIT / SELL）。
      return base(input, {
        tone: "danger",
        statusLabel: "已确认 Hard Risk",
        description: "需要重新审查 Decision / Action Envelope。Hard Risk 只改变审查与决策边界，不构成任何自动交易动作。",
      });
    }
    case "UNKNOWN": {
      return base(input, {
        tone: "unknown",
        statusLabel: "Hard Risk 状态未知",
        description: "风险状态无法确定，不能视为安全。",
      });
    }
    case "NOT_EVALUATED": {
      return base(input, {
        tone: "muted",
        statusLabel: "尚未完成 Hard Risk 评估",
        description: "尚未完成 Hard Risk 评估，不能视为安全。",
      });
    }
    default: {
      return unavailableView(input, "未提供 Hard Risk 评估结果");
    }
  }
}
