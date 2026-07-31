/** 顶部风险分析展示纯函数（可单测，无 React，永不抛异常）。 */
import type { TopRiskAnalysis, TopRiskLimitation } from "@/lib/api/types";

export type TopRiskStatus = "normal" | "partial" | "unavailable";

export function topRiskStatusLabel(
  status: TopRiskStatus | string | null | undefined,
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

/** 风险等级：risk_score ∈ [0,100]，越大风险越高。 */
export function riskLevel(
  score: number | null | undefined,
): { text: string; cls: string } {
  if (typeof score !== "number" || !Number.isFinite(score)) {
    return { text: "—", cls: "text-muted-foreground" };
  }
  if (score >= 70) return { text: "高风险", cls: "text-destructive" };
  if (score >= 40) return { text: "中风险", cls: "text-amber-600 dark:text-amber-400" };
  return { text: "低风险", cls: "text-emerald-600 dark:text-emerald-400" };
}

export function riskScoreText(score: number | null | undefined): string {
  if (typeof score !== "number" || !Number.isFinite(score)) return "—";
  return String(Math.round(score));
}

export function confidenceText(confidence: number | null | undefined): string {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) return "—";
  return `${Math.round(confidence)}%`;
}

export function coverageText(
  coverage: { completed: number; total: number; ratio: number } | null | undefined,
): string {
  if (!coverage || typeof coverage.total !== "number") return "—";
  const ratioPct =
    typeof coverage.ratio === "number" && Number.isFinite(coverage.ratio)
      ? `${Math.round(coverage.ratio * 100)}%`
      : "—";
  return `${coverage.completed ?? 0}/${coverage.total}（${ratioPct}）`;
}

export function topRiskFreshnessText(
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
  env: { limitations?: TopRiskLimitation[] } | null | undefined,
): string[] {
  if (!env?.limitations || !Array.isArray(env.limitations)) return [];
  return env.limitations
    .map((lim) => {
      if (!lim) return "";
      const field = lim.field ?? "";
      const detail = lim.detail ?? "";
      if (field && detail) return `${field}: ${detail}`;
      return field || detail || "";
    })
    .filter(Boolean);
}

export function traceArchiveStatusText(
  status: string | null | undefined,
): { text: string; cls: string } {
  if (status === "archived") {
    return { text: "已归档", cls: "text-emerald-600 dark:text-emerald-400" };
  }
  if (status === "failed") {
    return { text: "归档失败", cls: "text-amber-600 dark:text-amber-400" };
  }
  if (status === "skipped") {
    return { text: "未归档（不可用）", cls: "text-muted-foreground" };
  }
  return { text: status || "—", cls: "text-muted-foreground" };
}

export function topRiskErrorMessage(status: number | undefined): string {
  if (status === 0) return "后端连接不可用";
  if (status === 501) return "依赖未就绪";
  return "顶部风险分析暂不可用";
}

export function topRiskDirectionLabel(
  direction: string | null | undefined,
): string {
  if (direction === "RISK") return "风险";
  if (direction === "SAFE") return "安全";
  if (direction === "NEUTRAL") return "中性";
  // unknown / null / other → 显示为"—"（影子模式下恒为 unknown）
  return "—";
}

export type { TopRiskAnalysis };
