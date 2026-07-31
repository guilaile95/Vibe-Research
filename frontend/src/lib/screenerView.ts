/**
 * Pure helpers for candidate signal screener v0.1 UI.
 * No React; no network.
 */

import type {
  ScreenerCondition,
  ScreenerConditionId,
  ScreenerEvaluateResult,
  ScreenerStockResult,
} from "./api/types.ts";

export const MAX_CODES = 30;
export const MAX_CONDITIONS = 20;

export const CONDITION_CATALOG: {
  id: ScreenerConditionId;
  label: string;
  needsParams?: "rsi" | "threshold";
}[] = [
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
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return tokens.filter((t) => /^\d{6}$/.test(t));
}

/**
 * Direct-input normalization: 6-digit filter + dedupe + ascending sort.
 * Never silently truncates — overflow is a validation error.
 */
export function normalizeCodes(codes: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of codes) {
    const code = String(c || "").trim();
    if (!/^\d{6}$/.test(code) || seen.has(code)) continue;
    seen.add(code);
    out.push(code);
  }
  out.sort();
  return out;
}

/**
 * Source-load path (watchlist / holdings / sector reps):
 * allow deterministic take of first `limit` after normalize, with explicit truncation meta.
 */
export function loadSourceCodes(
  incoming: string[],
  limit: number = MAX_CODES,
): { codes: string[]; sourceTotal: number; truncated: boolean; hint: string } {
  const full = normalizeCodes(incoming);
  if (full.length <= limit) {
    return {
      codes: full,
      sourceTotal: full.length,
      truncated: false,
      hint: `已载入 ${full.length} 个代码（草稿，未运行）`,
    };
  }
  return {
    codes: full.slice(0, limit),
    sourceTotal: full.length,
    truncated: true,
    hint: `来源共有 ${full.length} 个代码，本次载入前 ${limit} 个`,
  };
}

export function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function validateConditionDraft(c: ScreenerCondition): string | null {
  if (!c || !c.id) return "缺少条件 id";
  const meta = CONDITION_CATALOG.find((x) => x.id === c.id);
  if (!meta) return `未知条件: ${c.id}`;
  if (meta.needsParams === "rsi") {
    const min = c.params?.min;
    const max = c.params?.max;
    if (!isFiniteNumber(min) || !isFiniteNumber(max)) return "RSI 需要有限 min/max";
    if (min > max) return "RSI min 不能大于 max";
  }
  if (meta.needsParams === "threshold") {
    const t = c.params?.threshold;
    if (!isFiniteNumber(t)) return "量比需要有限 threshold";
    if (t <= 0) return "threshold 必须 > 0";
  }
  return null;
}

/**
 * Validate full deduped code list (no silent slice).
 * 0 → error; 1–30 → ok; ≥31 → error mentioning 最多 30 个代码.
 */
export function validateScreenerDraft(
  codes: string[],
  conditions: ScreenerCondition[],
): string | null {
  const norm = normalizeCodes(codes);
  if (norm.length === 0) return "请至少输入 1 个六位股票代码";
  if (norm.length > MAX_CODES) {
    return `最多 30 个代码（当前去重后 ${norm.length} 个，请删减后再运行）`;
  }
  if (!conditions.length) return "请至少添加 1 个筛选条件";
  if (conditions.length > MAX_CONDITIONS) return `最多 ${MAX_CONDITIONS} 个条件`;
  const ids = conditions.map((c) => c.id);
  if (new Set(ids).size !== ids.length) return "条件 id 不能重复";
  for (const c of conditions) {
    const err = validateConditionDraft(c);
    if (err) return err;
  }
  return null;
}

/**
 * Build request body only after draft validation.
 * Does not truncate codes.
 */
export function buildEvaluatePayload(codes: string[], conditions: ScreenerCondition[]) {
  const err = validateScreenerDraft(codes, conditions);
  if (err) {
    throw new Error(err);
  }
  return {
    codes: normalizeCodes(codes),
    conditions: conditions.map((c) => {
      const meta = CONDITION_CATALOG.find((x) => x.id === c.id);
      if (meta?.needsParams === "rsi") {
        return { id: c.id, params: { min: c.params!.min!, max: c.params!.max! } };
      }
      if (meta?.needsParams === "threshold") {
        return { id: c.id, params: { threshold: c.params!.threshold! } };
      }
      return { id: c.id };
    }),
  };
}

export function groupResults(result: ScreenerEvaluateResult | null): {
  matched: ScreenerStockResult[];
  rejected: ScreenerStockResult[];
  unavailable: ScreenerStockResult[];
} {
  if (!result) return { matched: [], rejected: [], unavailable: [] };
  return {
    matched: result.matched || [],
    rejected: result.rejected || [],
    unavailable: result.unavailable || [],
  };
}

/** Hard rule: no code appears in both rejected and unavailable. */
export function bucketsAreDisjoint(result: ScreenerEvaluateResult): boolean {
  const r = new Set((result.rejected || []).map((s) => s.code));
  const u = new Set((result.unavailable || []).map((s) => s.code));
  for (const c of r) if (u.has(c)) return false;
  return true;
}

export type ScreenerUiPhase = "idle" | "loading" | "success" | "error";

/**
 * Request lifecycle helpers for single-flight + stale response discard.
 */
export class ScreenerRequestGate {
  private generation = 0;
  private controller: AbortController | null = null;
  /** Synchronous in-flight flag (does not depend on React re-render). */
  private inFlight = false;

  begin(): { generation: number; signal: AbortSignal } {
    if (this.controller) {
      this.controller.abort();
    }
    this.generation += 1;
    this.controller = new AbortController();
    this.inFlight = true;
    return { generation: this.generation, signal: this.controller.signal };
  }

  /**
   * Single-flight: ignore second click while a request is in flight.
   * Uses an internal flag so double-click before React re-renders still works.
   */
  beginIfIdle(_phase?: ScreenerUiPhase): { generation: number; signal: AbortSignal } | null {
    if (this.inFlight) return null;
    return this.begin();
  }

  isCurrent(generation: number): boolean {
    return generation === this.generation;
  }

  /** Mark request finished (success/error); keeps generation for stale checks. */
  end(generation: number): void {
    if (generation === this.generation) {
      this.inFlight = false;
      this.controller = null;
    }
  }

  abort(): void {
    this.controller?.abort();
    this.controller = null;
    this.inFlight = false;
    this.generation += 1;
  }
}

export function defaultCondition(id: ScreenerConditionId): ScreenerCondition {
  if (id === "rsi_between") return { id, params: { min: 30, max: 70 } };
  if (id === "volume_ratio_gte" || id === "volume_ratio_lte") {
    return { id, params: { threshold: 1.5 } };
  }
  return { id };
}

export function conditionLabel(id: string): string {
  return CONDITION_CATALOG.find((c) => c.id === id)?.label || id;
}
