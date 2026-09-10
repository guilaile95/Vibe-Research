import type { FactorValidationAggregate, FactorValidationObservation } from "./api/types";

export function factorValidationStatusLabel(status: string): string {
  return {
    EVALUATED: "已评估",
    IMMATURE_FORWARD_WINDOW: "未来窗口未成熟",
    NOT_EVALUABLE: "不可计算",
  }[status] || status;
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
  return observation.factor_null_count > 0
    || observation.immature_outcome_count > 0
    || observation.invalid_outcome_count > 0;
}
