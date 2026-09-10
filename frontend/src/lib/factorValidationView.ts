import type { FactorValidationAggregate, FactorValidationObservation } from "./api/types";

export function factorValidationStatusLabel(status: string): string {
  return {
    EVALUATED: "已评估",
    IMMATURE_FORWARD_WINDOW: "未来窗口未成熟",
    NOT_EVALUABLE: "不可计算",
  }[status] || status;
}

export function factorValidationReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "";
  const labels: Record<string, string> = {
    STALE_AT_FACTOR_DATE: "因子日期当天没有 RDP 记录，仅有更早的最后已知数据，未参与当日横截面",
    PARTIAL_FORWARD_COVERAGE: "部分证券的未来窗口不可用",
    FACTOR_VALUES_UNAVAILABLE: "因子值不可用",
    IMMATURE_FORWARD_WINDOW: "未来窗口未成熟",
    INSUFFICIENT_PAIRS: "有效配对不足",
    CONSTANT_FACTOR: "因子值没有横截面变化",
    CONSTANT_FORWARD_RETURN: "未来收益没有横截面变化",
    EMPTY_BUCKET: "高低分桶不可用",
    RANK_IC_UNAVAILABLE: "Rank IC 不可用",
  };
  return reason.split(";").map((item) => labels[item] || item).join("；");
}

/** IC is a unitless value; null is intentionally different from a real 0. */
export function factorIcText(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(4);
}

/** Returns and spreads are stored as decimal ratios and displayed as percentages. */
export function factorReturnText(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(4)}%`;
}

/** Ratios such as positive-date ratio are stored in [0, 1]. */
export function factorRatioText(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(2)}%`;
}

export function factorAggregateLabel(aggregate: FactorValidationAggregate): string {
  return `${aggregate.forward_window} 条已存储观测`;
}

export function factorObservationHasCoverageLimitation(observation: FactorValidationObservation): boolean {
  return observation.stale_source_row_count > 0
    || observation.factor_null_count > 0
    || observation.immature_outcome_count > 0
    || observation.invalid_outcome_count > 0;
}
