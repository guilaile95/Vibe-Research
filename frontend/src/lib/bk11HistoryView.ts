import type {
  Bk11DailyFactsEnvelope,
  Bk11HistoryEnvelope,
  Bk11HistoryStatus,
} from "@/lib/api/types";

export type Bk11HealthStatus = "normal" | "partial" | "unavailable";

export const BK11_STATUS_LABEL: Record<Bk11HistoryStatus, string> = {
  normal: "正常",
  partial: "部分缺失",
  unavailable: "不可用",
  empty: "暂无历史",
  error: "读取失败",
};

export const BK11_STATUS_BADGE: Record<Bk11HistoryStatus, string> = {
  normal: "bg-muted/40 text-muted-foreground/70",
  partial: "bg-warning/15 text-warning",
  unavailable: "bg-destructive/15 text-destructive",
  empty: "bg-muted/30 text-muted-foreground/60",
  error: "bg-destructive/15 text-destructive",
};

/** null / undefined / NaN / Infinity → "—"，其余原样（不产生 NaN 展示）。 */
export function formatNullableNumber(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    return String(value);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "" || trimmed.toLowerCase() === "nan") return "—";
    return trimmed;
  }
  return "—";
}

/** 数字 delta：null / 非法 → "—"；正数带 +。 */
export function formatDeltaNumber(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    return value > 0 ? `+${value}` : String(value);
  }
  return "—";
}

export function statusLabel(status: Bk11HistoryStatus | undefined | null): string {
  if (!status || !(status in BK11_STATUS_LABEL)) return "未知";
  return BK11_STATUS_LABEL[status];
}

export function statusBadgeCls(status: Bk11HistoryStatus | undefined | null): string {
  if (!status || !(status in BK11_STATUS_BADGE)) {
    return "bg-muted/30 text-muted-foreground/60";
  }
  return BK11_STATUS_BADGE[status];
}

export function latestEnvelope(
  env: Bk11HistoryEnvelope | null,
): Bk11DailyFactsEnvelope | null {
  if (!env || !env.latest) return null;
  if (env.status === "empty" || env.status === "error") return null;
  return env.latest;
}

export function digestText(env: Bk11HistoryEnvelope | null): string {
  const digest = env?.digest;
  if (!digest || typeof digest !== "object") return "";
  const text = (digest as Record<string, unknown>).digest_text;
  if (typeof text !== "string") return "";
  return text.trim();
}

export function factValue(
  env: Bk11HistoryEnvelope | null,
  field: string,
): unknown {
  const latest = latestEnvelope(env);
  const facts = latest?.sections?.facts;
  if (!facts || typeof facts !== "object") return null;
  return (facts as Record<string, unknown>)[field] ?? null;
}

export function ladderValue(
  env: Bk11HistoryEnvelope | null,
  field: string,
): unknown {
  const latest = latestEnvelope(env);
  const ladder = latest?.sections?.ladder;
  if (!ladder || typeof ladder !== "object") return null;
  return (ladder as Record<string, unknown>)[field] ?? null;
}

export function gapValue(
  env: Bk11HistoryEnvelope | null,
  field: string,
): unknown {
  const latest = latestEnvelope(env);
  const gap = latest?.sections?.gap;
  if (!gap || typeof gap !== "object") return null;
  return (gap as Record<string, unknown>)[field] ?? null;
}

export function hasComparableDelta(env: Bk11HistoryEnvelope | null): boolean {
  if (!env || env.status === "empty" || env.status === "error") return false;
  const delta = env.delta;
  if (!delta || typeof delta !== "object") return false;
  const status = (delta as Record<string, unknown>).status;
  return status === "normal" || status === "partial";
}

export function deltaValue(
  env: Bk11HistoryEnvelope | null,
  field: string,
): unknown {
  if (!env || !hasComparableDelta(env)) return null;
  const deltas = (env.delta as Record<string, unknown>).deltas;
  if (!deltas || typeof deltas !== "object") return null;
  const facts = (deltas as Record<string, unknown>).facts;
  if (!facts || typeof facts !== "object") return null;
  return (facts as Record<string, unknown>)[field] ?? null;
}

export function previousTradeDate(env: Bk11HistoryEnvelope | null): string | null {
  if (!env || !hasComparableDelta(env)) return null;
  const prev = (env.delta as Record<string, unknown>).previous_trade_date;
  return typeof prev === "string" ? prev : null;
}

export function dataTimeText(dataTime: string | null | undefined): string {
  if (!dataTime) return "—";
  return dataTime;
}

export function limitationLines(env: Bk11HistoryEnvelope | null): string[] {
  const lines = env?.limitations ?? [];
  return lines.filter((l): l is string => typeof l === "string");
}

export function isHealthyStatus(
  status: Bk11HistoryStatus | undefined | null,
): boolean {
  return status === "normal" || status === "partial";
}

export function latestSectionStatus(
  env: Bk11HistoryEnvelope | null,
  section: "facts" | "ladder" | "gap",
): Bk11HealthStatus | null {
  const latest = latestEnvelope(env);
  const sec = latest?.sections?.[section];
  if (!sec || typeof sec !== "object") return null;
  const status = (sec as Record<string, unknown>).status;
  if (status === "normal" || status === "partial" || status === "unavailable") {
    return status;
  }
  return null;
}
