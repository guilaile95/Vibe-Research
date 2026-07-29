import type { SignalSeverity, SignalStage } from "./api/types";

export interface SignalLedgerFilters {
  decision_run_id?: string;
  stage?: SignalStage | "";
  code?: string;
  severity?: SignalSeverity | "";
}

export function stageLabel(stage: SignalStage | string): string {
  switch (stage) {
    case "schema":
      return "模式校验 (Schema)";
    case "compatibility":
      return "兼容核验 (Compatibility)";
    case "fact_reconciliation":
      return "事实对账 (Fact Reconciliation)";
    case "policy_audit":
      return "策略风控 (Policy Audit)";
    case "execution":
      return "执行裁决 (Execution)";
    case "narrative_audit":
      return "叙事审核 (Narrative Audit)";
    case "account_constraint":
      return "资金约束 (Account Constraint)";
    default:
      return stage || "—";
  }
}

export function stageBadgeColor(stage: SignalStage | string): string {
  switch (stage) {
    case "schema":
      return "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 border-purple-200 dark:border-purple-800";
    case "compatibility":
      return "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300 border-sky-200 dark:border-sky-800";
    case "fact_reconciliation":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-800";
    case "policy_audit":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800";
    case "execution":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800";
    case "narrative_audit":
      return "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800";
    case "account_constraint":
      return "bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-300 border-teal-200 dark:border-teal-800";
    default:
      return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300 border-gray-200 dark:border-gray-700";
  }
}

export function severityLabel(severity: SignalSeverity | string): string {
  switch (severity) {
    case "info":
      return "正常 (Info)";
    case "warning":
      return "预警 (Warning)";
    case "error":
      return "错误 (Error)";
    default:
      return severity || "—";
  }
}

export function severityBadgeColor(severity: SignalSeverity | string): string {
  switch (severity) {
    case "info":
      return "bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 border-blue-200 dark:border-blue-800";
    case "warning":
      return "bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-800";
    case "error":
      return "bg-rose-50 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300 border-rose-200 dark:border-rose-800";
    default:
      return "bg-gray-50 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border-gray-200 dark:border-gray-700";
  }
}

export function actionLabel(action: string): string {
  switch (action.toLowerCase()) {
    case "buy":
      return "买入";
    case "add":
      return "加仓";
    case "hold":
      return "持有";
    case "reduce":
      return "减仓";
    case "sell":
      return "卖出";
    default:
      return action || "—";
  }
}

export function actionBadgeColor(action: string): string {
  switch (action.toLowerCase()) {
    case "buy":
    case "add":
      return "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300 border-rose-200 dark:border-rose-800";
    case "hold":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-800";
    case "reduce":
    case "sell":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800";
    default:
      return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300 border-gray-200 dark:border-gray-700";
  }
}

export function formatSignalTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  try {
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return "—";
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

export function validateSignalFilters(filters: SignalLedgerFilters): string | null {
  if (filters.code?.trim() && !/^\d{6}$/.test(filters.code.trim())) {
    return "股票代码必须是 6 位数字";
  }
  return null;
}
