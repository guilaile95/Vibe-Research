import type {
  DecisionRunRecord,
  DecisionTraceStatus,
  EvidenceItemRecord,
  EvidenceQualityStatus,
  EvidenceScope,
  ExplanationItemRecord,
} from "./api/types";

export interface DecisionEvidenceListFilters {
  symbol?: string;
  trade_date?: string;
  quality_status?: EvidenceQualityStatus | "";
  trace_status?: DecisionTraceStatus | "";
}

export function traceStatusLabel(status: DecisionTraceStatus | string | null | undefined): string {
  switch (status) {
    case "complete":
      return "完整追踪";
    case "archived":
      return "完整追踪";
    case "partial":
      return "部分追踪";
    case "failed":
      return "追踪失败";
    default:
      return status || "—";
  }
}

export function qualityStatusLabel(status: EvidenceQualityStatus | string | null | undefined): string {
  switch (status) {
    case "valid":
      return "高可靠数据";
    case "partial":
      return "部分可用";
    case "missing":
      return "关键缺失";
    case "stale":
      return "数据陈旧";
    case "unavailable":
      return "不可用";
    default:
      return status || "—";
  }
}

export function scopeLabel(scope: EvidenceScope | string | null | undefined): string {
  switch (scope) {
    case "market":
      return "大盘宏观";
    case "sector":
      return "行业板块";
    case "stock":
      return "个股基本面";
    case "portfolio":
      return "持仓组合";
    case "account":
      return "账户资金";
    case "risk":
      return "风控规则";
    default:
      return scope || "—";
  }
}

export function traceStatusBadgeClass(status: DecisionTraceStatus | string | null | undefined): string {
  switch (status) {
    case "complete":
    case "archived":
      return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
    case "partial":
      return "bg-amber-500/10 text-amber-400 border-amber-500/20";
    case "failed":
      return "bg-rose-500/10 text-rose-400 border-rose-500/20";
    default:
      return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
  }
}

export function qualityStatusBadgeClass(status: EvidenceQualityStatus | string | null | undefined): string {
  switch (status) {
    case "valid":
      return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
    case "partial":
      return "bg-amber-500/10 text-amber-400 border-amber-500/20";
    case "missing":
      return "bg-rose-500/10 text-rose-400 border-rose-500/20";
    case "stale":
      return "bg-orange-500/10 text-orange-400 border-orange-500/20";
    case "unavailable":
      return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
    default:
      return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
  }
}

export function scopeBadgeClass(scope: EvidenceScope | string | null | undefined): string {
  switch (scope) {
    case "market":
      return "bg-blue-500/10 text-blue-400 border-blue-500/20";
    case "sector":
      return "bg-purple-500/10 text-purple-400 border-purple-500/20";
    case "stock":
      return "bg-cyan-500/10 text-cyan-400 border-cyan-500/20";
    case "portfolio":
      return "bg-indigo-500/10 text-indigo-400 border-indigo-500/20";
    case "account":
      return "bg-teal-500/10 text-teal-400 border-teal-500/20";
    case "risk":
      return "bg-rose-500/10 text-rose-400 border-rose-500/20";
    default:
      return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
  }
}

export function formatEvidenceTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  try {
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return isoStr;
    return d.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return isoStr;
  }
}

/**
 * Escapes HTML characters to prevent XSS / render issues when displaying raw string content.
 */
export function escapeHtmlText(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Safely converts string or arbitrary object/node values into readable display string.
 */
export function safeRenderText(val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "string") return val;
  if (typeof val === "number" || typeof val === "boolean") return String(val);
  try {
    return JSON.stringify(val, null, 2);
  } catch {
    return String(val);
  }
}

/**
 * Filter decision runs in memory (pure function helper for UI).
 */
export function filterDecisionRuns(
  runs: DecisionRunRecord[],
  filters: DecisionEvidenceListFilters
): DecisionRunRecord[] {
  return runs.filter((run) => {
    if (filters.symbol) {
      const sym = filters.symbol.trim().toLowerCase();
      const runSym = (run.symbol || run.code || "").toLowerCase();
      if (!runSym.includes(sym)) return false;
    }
    if (filters.trade_date) {
      if (run.trade_date !== filters.trade_date) return false;
    }
    if (filters.quality_status) {
      if (run.quality_status !== filters.quality_status) return false;
    }
    if (filters.trace_status) {
      if (run.trace_status !== filters.trace_status) return false;
    }
    return true;
  });
}

/**
 * Finds evidence records supporting or limiting a specific explanation claim.
 */
export function getExplanationEvidences(
  explanation: ExplanationItemRecord,
  allEvidences: EvidenceItemRecord[]
): { supporting: EvidenceItemRecord[]; limiting: EvidenceItemRecord[] } {
  const evidenceMap = new Map<string, EvidenceItemRecord>();
  allEvidences.forEach((e) => {
    if (e.id) evidenceMap.set(e.id, e);
    if (e.evidence_id) evidenceMap.set(e.evidence_id, e);
  });
  const supporting = (explanation.supporting_evidence_ids || [])
    .map((id) => evidenceMap.get(id))
    .filter((e): e is EvidenceItemRecord => e !== undefined);
  const limiting = (explanation.limiting_evidence_ids || [])
    .map((id) => evidenceMap.get(id))
    .filter((e): e is EvidenceItemRecord => e !== undefined);
  return { supporting, limiting };
}
