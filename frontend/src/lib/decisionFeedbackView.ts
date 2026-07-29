import type {
  DecisionFeedbackAdoptionStatus,
  DecisionFeedbackCreateInput,
  DecisionFeedbackOutcomeStatus,
} from "./api/types";

export interface DecisionFeedbackDraft {
  code: string;
  advice_trade_date: string;
  advice_generated_at: string;
  trade_id?: string | null;
  adoption_status: DecisionFeedbackAdoptionStatus;
  outcome_status: DecisionFeedbackOutcomeStatus;
  note?: string | null;
}

export interface DecisionFeedbackListFilters {
  code?: string;
  adoption_status?: DecisionFeedbackAdoptionStatus | "";
  outcome_status?: DecisionFeedbackOutcomeStatus | "";
  date_from?: string;
  date_to?: string;
  include_voided?: boolean;
}

export interface DecisionFeedbackListQuery {
  code?: string;
  adoption_status?: DecisionFeedbackAdoptionStatus;
  outcome_status?: DecisionFeedbackOutcomeStatus;
  date_from?: string;
  date_to?: string;
  include_voided?: boolean;
  limit?: number;
  offset?: number;
}

export function adoptionStatusLabel(
  status: DecisionFeedbackAdoptionStatus | string,
): string {
  switch (status) {
    case "followed":
      return "按照建议执行";
    case "partially_followed":
      return "部分执行建议";
    case "not_followed":
      return "明确未执行";
    case "not_applicable":
      return "不适用/未达成条件";
    default:
      return status || "—";
  }
}

export function outcomeStatusLabel(
  status: DecisionFeedbackOutcomeStatus | string,
): string {
  switch (status) {
    case "better_than_expected":
      return "超出预期";
    case "as_expected":
      return "符合预期";
    case "worse_than_expected":
      return "低于预期";
    case "not_evaluated":
      return "暂未评估";
    default:
      return status || "—";
  }
}

export function formatFeedbackTime(isoStr: string | null | undefined): string {
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

const VALID_ADOPTION_STATUSES: Set<DecisionFeedbackAdoptionStatus> = new Set([
  "followed",
  "partially_followed",
  "not_followed",
  "not_applicable",
]);

const VALID_OUTCOME_STATUSES: Set<DecisionFeedbackOutcomeStatus> = new Set([
  "better_than_expected",
  "as_expected",
  "worse_than_expected",
  "not_evaluated",
]);

export function validateFeedbackDraft(draft: DecisionFeedbackDraft): string | null {
  if (!draft.code || !/^\d{6}$/.test(draft.code.trim())) {
    return "股票代码必须是 6 位数字";
  }
  if (!draft.advice_trade_date || !/^\d{4}-\d{2}-\d{2}$/.test(draft.advice_trade_date.trim())) {
    return "建议交易日期格式须为 YYYY-MM-DD";
  }
  if (!draft.advice_generated_at || !draft.advice_generated_at.trim()) {
    return "建议生成时间不能为空";
  }
  if (!VALID_ADOPTION_STATUSES.has(draft.adoption_status)) {
    return "采纳执行状态无效";
  }
  if (!VALID_OUTCOME_STATUSES.has(draft.outcome_status)) {
    return "事后评估结果无效";
  }
  if (draft.note && draft.note.length > 2000) {
    return "备注长度不能超过 2000 字符";
  }
  return null;
}

export function buildFeedbackCreateInput(
  draft: DecisionFeedbackDraft,
): DecisionFeedbackCreateInput {
  const code = draft.code.trim();
  const advice_trade_date = draft.advice_trade_date.trim();
  const advice_generated_at = draft.advice_generated_at.trim();
  const trade_id = draft.trade_id?.trim() || null;
  const note = draft.note?.trim() || null;

  return {
    code,
    advice_trade_date,
    advice_generated_at,
    trade_id,
    adoption_status: draft.adoption_status,
    outcome_status: draft.outcome_status,
    note,
    advice_ref: {
      trade_date: advice_trade_date,
      generated_at: advice_generated_at,
    },
  };
}

export function validateFeedbackListFilters(
  filters: DecisionFeedbackListFilters,
): string | null {
  if (filters.code?.trim() && !/^\d{6}$/.test(filters.code.trim())) {
    return "股票代码筛选必须是 6 位数字";
  }
  if (filters.date_from && !/^\d{4}-\d{2}-\d{2}$/.test(filters.date_from)) {
    return "开始日期格式须为 YYYY-MM-DD";
  }
  if (filters.date_to && !/^\d{4}-\d{2}-\d{2}$/.test(filters.date_to)) {
    return "结束日期格式须为 YYYY-MM-DD";
  }
  if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
    return "开始日期不得晚于结束日期";
  }
  return null;
}

export function buildFeedbackListQuery(
  filters: DecisionFeedbackListFilters,
  limit?: number,
  offset?: number,
): DecisionFeedbackListQuery {
  const query: DecisionFeedbackListQuery = {};
  if (filters.code?.trim()) query.code = filters.code.trim();
  if (filters.adoption_status) query.adoption_status = filters.adoption_status;
  if (filters.outcome_status) query.outcome_status = filters.outcome_status;
  if (filters.date_from) query.date_from = filters.date_from;
  if (filters.date_to) query.date_to = filters.date_to;
  if (filters.include_voided != null) query.include_voided = filters.include_voided;
  if (limit != null) query.limit = limit;
  if (offset != null) query.offset = offset;
  return query;
}
