/**
 * P0-HR1 Hard Risk Decision Inbox 展示层（纯 view-model，零 I/O、零业务判定）。
 *
 * 铁律（以 backend/hard_risk_contract.py 的 LEGAL_STATE_EVALUATION_PAIRS
 * 为 authority，不做宽松 frontend contract）：
 * - 只消费 Hard Risk 专属 payload 字段：
 *   hard_risk_state / hard_risk_evaluation / hard_risk_reason_codes /
 *   hard_risk_authority_refs。
 * - 绝不 fallback Decision Inbox generic 数据：item.reason_codes 是
 *   Campaign-level generic reason list；explainability.authority_refs 是
 *   整个 Campaign projection 的 generic authority refs（可能含 Critical
 *   Data / Thesis / Decision / Hard Risk）——都不得充当 Hard Risk 自己的
 *   evidence 或 positive proof。
 * - 只有合法 pair 且满足正证明要求才显示对应状态：
 *   A. CLEAR + EVALUATED + nonempty hard_risk_authority_refs → safe green
 *   B. CONFIRMED + EVALUATED + refs + nonempty hard_risk_reason_codes → danger
 *   C. UNKNOWN + UNKNOWN + nonempty hard_risk_reason_codes → unknown
 *   D. UNKNOWN + ERROR + nonempty hard_risk_reason_codes → evaluation error
 *   E. NOT_EVALUATED + NOT_EVALUATED + nonempty hard_risk_reason_codes
 *      → not evaluated
 * - 其它全部 → fail closed unavailable；绝不 safe green、绝不声称已确认。
 * - CONFIRMED 文案绝不包含卖出 / 退出 / 清仓 / EXIT / SELL。
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

/** shared contract LEGAL_STATE_EVALUATION_PAIRS 的精确镜像。 */
export const LEGAL_STATE_EVALUATION_PAIRS: ReadonlySet<string> = new Set([
  "CLEAR|EVALUATED",
  "CONFIRMED|EVALUATED",
  "UNKNOWN|UNKNOWN",
  "UNKNOWN|ERROR",
  "NOT_EVALUATED|NOT_EVALUATED",
]);

export type HardRiskTone = "danger" | "safe" | "unknown" | "muted";

/** Hard Risk 专属 payload（严禁从 generic Decision Inbox 数据 fallback）。 */
export interface HardRiskInput {
  hard_risk_state?: string | null;
  hard_risk_evaluation?: string | null;
  hard_risk_reason_codes?: readonly string[] | null;
  hard_risk_authority_refs?: readonly string[] | null;
}

export interface HardRiskViewModel {
  /** 展示 tone；"safe" 只允许 positive-proof CLEAR。 */
  tone: HardRiskTone;
  statusLabel: string;
  description: string;
  /** 唯一允许的绿色安全态：CLEAR + EVALUATED + nonempty hard_risk_authority_refs。 */
  showSafeGreen: boolean;
  /** evaluation === "ERROR" 时展示失败标识，其余为 null。 */
  evaluationLabel: string | null;
  /** 只承载 hard_risk_reason_codes（generic reason_codes 严禁混入）。 */
  reasonCodes: readonly string[];
  /** 只承载 hard_risk_authority_refs（generic refs 严禁混入）。 */
  authorityRefs: readonly string[];
}

function normalizeState(value: string | null | undefined): HardRiskState | null {
  return value !== null && value !== undefined
    && (HARD_RISK_STATES as readonly string[]).includes(value)
    ? (value as HardRiskState)
    : null;
}

function normalizeEvaluation(
  value: string | null | undefined,
): HardRiskEvaluation | null {
  return value !== null && value !== undefined
    && (HARD_RISK_EVALUATIONS as readonly string[]).includes(value)
    ? (value as HardRiskEvaluation)
    : null;
}

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
    reasonCodes: input.hard_risk_reason_codes ?? [],
    authorityRefs: input.hard_risk_authority_refs ?? [],
    ...overrides,
  };
}

/** 不合规输入的统一 fail-closed 视图（绝不伪装成安全或确认）。 */
function unavailableView(input: HardRiskInput): HardRiskViewModel {
  return base(input, {
    tone: "muted",
    statusLabel: "硬风险状态未知",
    description: "硬风险评估结果缺失或不一致，不能视为安全。",
  });
}

export function hardRiskDisplay(input: HardRiskInput): HardRiskViewModel {
  const state = normalizeState(input.hard_risk_state);
  const evaluation = normalizeEvaluation(input.hard_risk_evaluation);
  const reasonCodes = input.hard_risk_reason_codes ?? [];
  const authorityRefs = input.hard_risk_authority_refs ?? [];

  // 1) 合法 pair 校验（contract authority；任一 missing / illegal enum /
  //    illegal pair → fail closed）。
  if (state === null || evaluation === null) return unavailableView(input);
  if (!LEGAL_STATE_EVALUATION_PAIRS.has(`${state}|${evaluation}`)) {
    return unavailableView(input);
  }

  // 2) 正证明要求（只认 Hard Risk 专属 evidence，无任何 generic fallback）：
  //    - CLEAR / CONFIRMED（EVALUATED）必须具有 nonempty hard_risk_authority_refs
  //    - 非 CLEAR 必须具有 nonempty hard_risk_reason_codes（含 CONFIRMED）。
  if (
    (state === "CLEAR" || state === "CONFIRMED")
    && authorityRefs.length === 0
  ) {
    return unavailableView(input);
  }
  if (state !== "CLEAR" && reasonCodes.length === 0) {
    return unavailableView(input);
  }

  switch (state) {
    case "CLEAR": {
      return base(input, {
        tone: "safe",
        statusLabel: "已确认无硬风险",
        description: "当前没有已确认的硬风险，但后续仍需按新的事实重新评估。",
        showSafeGreen: true,
      });
    }
    case "CONFIRMED": {
      // 高优先级风险提示：只要求重新审查 Decision / Action Envelope，
      // 绝不表达任何自动交易指令（禁止出现卖出 / 退出 / 清仓 / EXIT / SELL）。
      return base(input, {
        tone: "danger",
        statusLabel: "已确认硬风险",
        description: "需要重新审查正式决策和可执行操作。硬风险只改变审查与决策边界，不构成任何自动交易动作。",
      });
    }
    case "UNKNOWN": {
      if (evaluation === "ERROR") {
        return base(input, {
          tone: "unknown",
          statusLabel: "硬风险读取失败",
          description: "硬风险评估失败或不可用，风险状态无法确定。请修复数据后重新评估，不能视为安全。",
          evaluationLabel: "读取失败",
        });
      }
      return base(input, {
        tone: "unknown",
        statusLabel: "硬风险状态未知",
        description: "风险状态无法确定，不能视为安全。",
      });
    }
    case "NOT_EVALUATED": {
      return base(input, {
        tone: "muted",
        statusLabel: "尚未完成硬风险评估",
        description: "尚未完成硬风险评估，不能视为安全。",
      });
    }
  }
}
