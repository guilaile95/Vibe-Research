/**
 * P0-HR1 Hard Risk Decision Inbox 展示层（纯 view-model，零 I/O、零业务判定）。
 *
 * 铁律（以 backend/hard_risk_contract.py 的 LEGAL_STATE_EVALUATION_PAIRS
 * 为 authority，不做宽松 frontend contract）：
 * - 只有合法 pair 且满足正证明要求才显示对应状态：
 *   A. CLEAR + EVALUATED + nonempty authority_refs      → safe green
 *   B. CONFIRMED + EVALUATED + refs + nonempty reasons  → danger
 *   C. UNKNOWN + UNKNOWN + nonempty reasons             → unknown
 *   D. UNKNOWN + ERROR + nonempty reasons               → evaluation error
 *   E. NOT_EVALUATED + NOT_EVALUATED + nonempty reasons → not evaluated
 * - 其它全部（missing / null / illegal enum / illegal pair /
 *   CLEAR 或 CONFIRMED 缺 evaluation / 缺 authority_refs /
 *   非 CLEAR 缺 reason_codes）→ fail closed unavailable。
 * - 绝不 safe green、绝不声称「已确认无 Hard Risk」、绝不在证据不足时
 *   声称「已确认 Hard Risk」。
 * - CONFIRMED 文案绝不包含卖出 / 退出 / 清仓 / EXIT / SELL。
 * - reason_codes / authority_refs 原样透传（纯 presentation）。
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
  /** 唯一允许的绿色安全态：CLEAR + EVALUATED + nonempty authority refs。 */
  showSafeGreen: boolean;
  /** evaluation === "ERROR" 时展示失败标识，其余为 null。 */
  evaluationLabel: string | null;
  reasonCodes: readonly string[];
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

function collectAuthorityRefs(input: HardRiskInput): readonly string[] {
  const top = input.authority_refs ?? [];
  if (top.length > 0) return top;
  return input.explainability?.authority_refs ?? [];
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
    reasonCodes: input.reason_codes ?? [],
    authorityRefs: collectAuthorityRefs(input),
    ...overrides,
  };
}

/** 不合规输入的统一 fail-closed 视图（绝不伪装成安全或确认）。 */
function unavailableView(input: HardRiskInput): HardRiskViewModel {
  return base(input, {
    tone: "muted",
    statusLabel: "Hard Risk 状态未知",
    description: "Hard Risk 评估结果缺失或不一致（缺少评估状态 / 权威引用 / 原因码），不能视为安全。",
  });
}

export function hardRiskDisplay(input: HardRiskInput): HardRiskViewModel {
  const state = normalizeState(input.hard_risk_state);
  const evaluation = normalizeEvaluation(input.hard_risk_evaluation);
  const reasonCodes = input.reason_codes ?? [];
  const authorityRefs = collectAuthorityRefs(input);

  // 1) 合法 pair 校验（contract authority；任一 missing / illegal enum /
  //    illegal pair → fail closed）。
  if (state === null || evaluation === null) return unavailableView(input);
  if (!LEGAL_STATE_EVALUATION_PAIRS.has(`${state}|${evaluation}`)) {
    return unavailableView(input);
  }

  // 2) 正证明要求：
  //    - CLEAR / CONFIRMED（EVALUATED）必须具有 nonempty authority_refs
  //    - 非 CLEAR 必须具有 nonempty reason_codes（含 CONFIRMED，contract
  //      「non-CLEAR results require reason_codes」）。
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
        statusLabel: "已确认无 Hard Risk",
        description: "后端已给出 positive-proof CLEAR，当前无已确认的 Hard Risk。这不免除后续重新评估。",
        showSafeGreen: true,
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
      if (evaluation === "ERROR") {
        return base(input, {
          tone: "unknown",
          statusLabel: "Hard Risk 评估失败",
          description: "Hard Risk 评估失败或不可用，风险状态无法确定。请修复数据后重新评估，不能视为安全。",
          evaluationLabel: "ERROR",
        });
      }
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
  }
}
