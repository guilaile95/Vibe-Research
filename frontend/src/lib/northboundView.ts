/** 北向资金展示纯函数（可单测，无 React，永不抛异常）。 */
import type { NorthboundLimitation } from "@/lib/api/types";

export function formatTurnoverMn(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const yiVal = v / 100;
  return `${yiVal.toFixed(2)} 亿`;
}

export function formatTurnoverYuan(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 100_000_000) {
    return `${(v / 100_000_000).toFixed(2)} 亿`;
  }
  if (abs >= 10_000) {
    return `${(v / 10_000).toFixed(2)} 万`;
  }
  return `${v.toFixed(0)} 元`;
}

export function formatCount(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

export function northboundStatusLabel(
  status: "normal" | "partial" | "unavailable" | string | null | undefined,
): { text: string; cls: string } {
  if (status === "normal") {
    return {
      text: "正常",
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border",
    };
  }
  if (status === "partial") {
    return {
      text: "部分缺失",
      cls: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400 border",
    };
  }
  return {
    text: "不可用",
    cls: "border-border/60 bg-muted/30 text-muted-foreground border",
  };
}

export function northboundFreshnessText(
  env: { trade_date?: string | null; is_stale?: boolean } | null | undefined,
): string {
  if (!env || !env.trade_date) {
    return env?.is_stale ? "交易日未知 · 数据陈旧" : "交易日未知";
  }
  const dateText = `交易日 ${env.trade_date}`;
  return env.is_stale ? `${dateText} · 数据陈旧` : dateText;
}

export function fetchedAtText(fetched_at: string | null | undefined): string {
  if (!fetched_at || typeof fetched_at !== "string") return "—";
  const sliced = fetched_at.slice(0, 19).replace("T", " ");
  if (sliced.length < 10) return "—";
  return sliced;
}

export function limitationLines(
  env: { limitations?: NorthboundLimitation[] } | null | undefined,
): string[] {
  if (!env?.limitations || !Array.isArray(env.limitations)) return [];
  return env.limitations.map((lim) => {
    if (!lim) return "";
    const field = lim.field ?? "";
    const detail = lim.detail ?? "";
    if (field && detail) return `${field}: ${detail}`;
    return field || detail || "";
  }).filter(Boolean);
}

export function northboundErrorMessage(status: number | undefined): string {
  if (status === 0) return "后端连接不可用";
  if (status === 501) return "依赖未就绪";
  return "北向资金暂不可用";
}
