// P0-CT1：Campaign ↔ Formal Thesis 激活纯逻辑（无 I/O、无 DOM 依赖，可直接单测）。
// 规则镜像 backend stable 权威：
// - STRATEGY_HORIZON_RANGES 与 backend evidence_thesis_store.STRATEGY_HORIZON_RANGES 逐字一致
// - canConfirmFormalThesis 镜像 backend confirm_formalization 的 hard gate
// - selectCampaignThesisCandidates 只做过滤 + 排序，绝不自动选唯一权威
import type {
  ExpectedHorizon,
  InvestmentThesis,
  ThesisStrategy,
} from "./api/types.ts";

// 策略 ↔ 预期周期硬兼容（backend evidence_thesis_store.STRATEGY_HORIZON_RANGES 同一权威表）。
export const STRATEGY_HORIZON_RANGES: Record<ThesisStrategy, [number, number]> = {
  SHORT: [1, 10],
  SWING: [5, 45],
  MEDIUM: [40, 252],
};

/** 策略的默认预期周期：完整允许范围（anchor 恒为 FREEZE_AT）；未知策略 → null。 */
export function defaultHorizonForStrategy(
  strategy: ThesisStrategy,
): ExpectedHorizon | null {
  const range = STRATEGY_HORIZON_RANGES[strategy];
  if (!range) return null;
  const [min, max] = range;
  return { unit: "TRADING_DAY", min, max, anchor: "FREEZE_AT" };
}

/**
 * 确认门（镜像 backend confirm_formalization hard gate）：
 * formal_state=draft + status=active + core_claims 3-5 条 + strategy + 合法 expected_horizon。
 * legacy 行缺失 formal 字段（undefined）一律视为不满足。
 */
export function canConfirmFormalThesis(thesis: InvestmentThesis): boolean {
  if (thesis.formal_state !== "draft") return false;
  if (thesis.status !== "active") return false;
  const claimCount = Array.isArray(thesis.core_claims) ? thesis.core_claims.length : 0;
  if (claimCount < 3 || claimCount > 5) return false;
  if (!thesis.strategy) return false;
  const horizon = thesis.expected_horizon;
  if (!horizon || typeof horizon !== "object") return false;
  if (horizon.unit !== "TRADING_DAY" || horizon.anchor !== "FREEZE_AT") return false;
  if (
    !Number.isInteger(horizon.min)
    || !Number.isInteger(horizon.max)
    || horizon.min < 1
    || horizon.max < horizon.min
  ) {
    return false;
  }
  // Runtime API payloads are untrusted even though the TypeScript contract is
  // a closed union.  An unknown truthy strategy must fail closed rather than
  // throwing while the detail page renders.
  const range = Object.prototype.hasOwnProperty.call(STRATEGY_HORIZON_RANGES, thesis.strategy)
    ? STRATEGY_HORIZON_RANGES[thesis.strategy]
    : undefined;
  if (!range) return false;
  const [rangeMin, rangeMax] = range;
  if (horizon.min < rangeMin || horizon.max > rangeMax) return false;
  return true;
}

/**
 * 候选选择：stock 且 subject_id 与 security_code 精确一致、非 archived，
 * 按 updated_at 新到旧排序。返回整个候选列表——即使只剩一个也不自动选为权威，
 * 是否「唯一权威」由调用方结合 binding 现状决定。
 */
export function selectCampaignThesisCandidates(
  theses: InvestmentThesis[],
  securityCode: string,
): InvestmentThesis[] {
  return theses
    .filter(
      (t) =>
        t.subject_type === "stock"
        && t.subject_id === securityCode
        && t.status !== "archived",
    )
    .slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}
