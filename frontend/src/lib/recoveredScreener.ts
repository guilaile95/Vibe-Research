import type {
  ScreenerCondition,
  ScreenerConditionId,
  ScreenerEvaluateResult,
  ScreenerStockResult,
} from "@/lib/recoveredMarketTypes";

export const MAX_CODES = 30;
export const MAX_CONDITIONS = 20;

export const CONDITION_CATALOG: Array<{
  id: ScreenerConditionId;
  label: string;
  needsParams?: "rsi" | "threshold";
}> = [
  { id: "price_gt_sma20", label: "价格 > SMA20" },
  { id: "price_lt_sma20", label: "价格 < SMA20" },
  { id: "price_gt_sma60", label: "价格 > SMA60" },
  { id: "price_lt_sma60", label: "价格 < SMA60" },
  { id: "sma20_gt_sma60", label: "SMA20 > SMA60" },
  { id: "sma20_lt_sma60", label: "SMA20 < SMA60" },
  { id: "macd_hist_positive", label: "MACD 柱 > 0" },
  { id: "macd_hist_negative", label: "MACD 柱 < 0" },
  { id: "breakout_20d_high", label: "突破 20 日高" },
  { id: "breakdown_20d_low", label: "跌破 20 日低" },
  { id: "rsi_between", label: "RSI 区间", needsParams: "rsi" },
  { id: "volume_ratio_gte", label: "量比 ≥ 阈值", needsParams: "threshold" },
  { id: "volume_ratio_lte", label: "量比 ≤ 阈值", needsParams: "threshold" },
];

export function parseCodeDraft(raw: string): string[] {
  return raw.split(/[^\d]+/).filter((token) => /^\d{6}$/.test(token));
}

export function normalizeCodes(codes: string[]): string[] {
  return [...new Set(codes.map((code) => String(code || "").trim()).filter((code) => /^\d{6}$/.test(code)))].sort();
}

export function loadSourceCodes(incoming: string[]) {
  const all = normalizeCodes(incoming);
  return {
    codes: all.slice(0, MAX_CODES),
    sourceTotal: all.length,
    truncated: all.length > MAX_CODES,
    hint: all.length > MAX_CODES
      ? `来源共有 ${all.length} 个代码，本次载入前 ${MAX_CODES} 个`
      : `已载入 ${all.length} 个代码（草稿，未运行）`,
  };
}

export function defaultCondition(id: ScreenerConditionId): ScreenerCondition {
  if (id === "rsi_between") return { id, params: { min: 30, max: 70 } };
  if (id === "volume_ratio_gte" || id === "volume_ratio_lte") {
    return { id, params: { threshold: 1.5 } };
  }
  return { id };
}

export function validateScreenerDraft(codes: string[], conditions: ScreenerCondition[]): string | null {
  const normalized = normalizeCodes(codes);
  if (normalized.length === 0) return "请至少输入 1 个六位股票代码";
  if (normalized.length > MAX_CODES) return `最多 ${MAX_CODES} 个代码（当前去重后 ${normalized.length} 个）`;
  if (conditions.length === 0) return "请至少添加 1 个筛选条件";
  if (conditions.length > MAX_CONDITIONS) return `最多 ${MAX_CONDITIONS} 个条件`;
  const ids = conditions.map((item) => item.id);
  if (new Set(ids).size !== ids.length) return "条件 id 不能重复";
  for (const item of conditions) {
    if (item.id === "rsi_between") {
      const min = item.params?.min;
      const max = item.params?.max;
      if (!Number.isFinite(min) || !Number.isFinite(max) || (min as number) > (max as number)) {
        return "RSI 区间参数无效";
      }
    }
    if (item.id === "volume_ratio_gte" || item.id === "volume_ratio_lte") {
      const threshold = item.params?.threshold;
      if (!Number.isFinite(threshold) || (threshold as number) <= 0) return "量比阈值必须 > 0";
    }
  }
  return null;
}

export function buildEvaluatePayload(codes: string[], conditions: ScreenerCondition[]) {
  const error = validateScreenerDraft(codes, conditions);
  if (error) throw new Error(error);
  return { codes: normalizeCodes(codes), conditions };
}

export function groupResults(result: ScreenerEvaluateResult | null): {
  matched: ScreenerStockResult[];
  rejected: ScreenerStockResult[];
  unavailable: ScreenerStockResult[];
} {
  return {
    matched: result?.matched || [],
    rejected: result?.rejected || [],
    unavailable: result?.unavailable || [],
  };
}
