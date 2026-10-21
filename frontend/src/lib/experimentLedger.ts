export type ExperimentRecord = {
  schema_version?: string; metric_protocol?: string;
  id: string; created_at: string; kind: string; subject: unknown; rules_version: string;
  sample: unknown; window: unknown; benchmark: unknown; request_identity: string;
  input_identity: string | null; snapshot: string | null; receipt: string; status: string;
  report_status: string | null; scope: string | null; currency: string | null;
};
export type ExperimentComparison = {
  left: ExperimentRecord; right: ExperimentRecord; changes: string[]; reasons: string[]; same_input: boolean;
  metrics: { name: string; dimension?: { currency: string; method: string; name: string; unit: string; status: string } | null; left: number | null; right: number | null; status: string; delta: number | null; left_unit: string; right_unit: string }[];
};
export function experimentEndpoint(kind: string) {
  if (kind === "rolling-signal") return "/signals/validation/rolling";
  if (kind === "signal") return "/signals/validation/evaluate";
  if (kind === "factor") return "/signals/factor-validation/evaluate";
  if (["simulation", "scenario", "performance", "ledger-performance", "cost-comparison"].includes(kind)) return `/research-analytics/${kind}`;
  throw new Error("未知研究类型");
}
/** Tokens invalidate stale async display; persisted history is never silently removed. */
export class ExperimentGeneration {
  private value = 0;
  next() { return ++this.value; }
  current(token: number) { return token === this.value; }
}

export function experimentReason(reason: string) {
  if (reason === "LEGACY_METRICS_NOT_RETAINED") return "旧版未保留指标，无法比较；原始记录保持不变";
  if (reason === "METRICS_UNAVAILABLE") return "没有可用指标，不能判定结果一致";
  if (reason === "metric_protocol") return "指标协议版本不同";
  if (reason === "metric_dimensions") return "币种、成本法或指标状态不同";
  return reason;
}
