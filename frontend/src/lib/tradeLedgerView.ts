import type {
  TradeCreateInput,
  TradeExecutionStatus,
  TradeOperation,
} from "./api/types";

export interface TradeDraft {
  code: string;
  name: string;
  operation: TradeOperation;
  execution_status: TradeExecutionStatus;

  planned_price?: number | string | null;
  planned_quantity?: number | string | null;

  actual_price?: number | string | null;
  actual_quantity?: number | string | null;
  executed_at?: string | null;

  fee?: number | string | null;
  other_cost?: number | string | null;
  unexecuted_reason?: string | null;
  note?: string | null;

  advice_ref?: {
    trade_date: string;
    generated_at: string;
  } | null;

  thesis_ref?: {
    thesis_id: string;
    revision_number: number;
  } | null;
}

export interface TradeListFilters {
  code?: string;
  operation?: TradeOperation | "";
  execution_status?: TradeExecutionStatus | "";
  date_from?: string;
  date_to?: string;
  include_voided?: boolean;
}

export interface TradeListQuery {
  code?: string;
  operation?: TradeOperation;
  execution_status?: TradeExecutionStatus;
  date_from?: string;
  date_to?: string;
  include_voided?: boolean;
  limit?: number;
  offset?: number;
}

export function operationLabel(op: TradeOperation | string): string {
  switch (op) {
    case "buy":
      return "买入";
    case "add":
      return "加仓";
    case "reduce":
      return "减仓";
    case "sell":
      return "卖出";
    default:
      return op || "—";
  }
}

export function executionStatusLabel(status: TradeExecutionStatus | string): string {
  switch (status) {
    case "full":
      return "已全部执行";
    case "partial":
      return "部分执行";
    case "not_executed":
      return "未执行";
    default:
      return status || "—";
  }
}

export function formatTradeMoney(val: number | null | undefined): string {
  if (val == null || !Number.isFinite(val)) {
    return "—";
  }
  const n = val;
  const formatted = Math.abs(n).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return n < 0 ? `-¥${formatted}` : `¥${formatted}`;
}

export function formatTradeQuantity(val: number | null | undefined): string {
  if (val == null || !Number.isFinite(val) || !Number.isInteger(val)) {
    return "—";
  }
  return val.toLocaleString("zh-CN");
}

export function formatTradePercentage(val: number | null | undefined): string {
  if (val == null || !Number.isFinite(val)) {
    return "—";
  }
  return `${val.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

export interface TradeExecutionTimePreview {
  localValue: string;
  timeZone: string;
  utcOffset: string;
  canonicalUtcIso: string;
}

function parseTradeExecutionTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!match) return null;

  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = secondText ? Number(secondText) : 0;
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59) {
    return null;
  }

  const parsed = new Date(0);
  parsed.setFullYear(year, month - 1, day);
  parsed.setHours(hour, minute, second, 0);
  if (
    parsed.getFullYear() !== year
    || parsed.getMonth() !== month - 1
    || parsed.getDate() !== day
    || parsed.getHours() !== hour
    || parsed.getMinutes() !== minute
    || parsed.getSeconds() !== second
  ) {
    return null;
  }
  return parsed;
}

export function canonicalizeTradeExecutionTime(value: string | null | undefined): string | null {
  const parsed = parseTradeExecutionTime(value);
  return parsed ? parsed.toISOString() : null;
}

function formatUtcOffset(date: Date): string {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absoluteMinutes = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absoluteMinutes / 60)).padStart(2, "0");
  const minutes = String(absoluteMinutes % 60).padStart(2, "0");
  return `UTC${sign}${hours}:${minutes}`;
}

export function getTradeExecutionTimePreview(value: string | null | undefined): TradeExecutionTimePreview | null {
  const parsed = parseTradeExecutionTime(value);
  if (!parsed) return null;

  let timeZone = "浏览器本地时区";
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || timeZone;
  } catch {
    // Keep the explicit fallback when the runtime does not report an IANA zone.
  }

  return {
    localValue: value as string,
    timeZone,
    utcOffset: formatUtcOffset(parsed),
    canonicalUtcIso: parsed.toISOString(),
  };
}

export function formatTradeTime(isoStr: string | null | undefined): string {
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

export function validateTradeDraft(draft: TradeDraft): string | null {
  if (!draft.code || !/^\d{6}$/.test(draft.code.trim())) {
    return "股票代码必须是 6 位数字";
  }
  if (!draft.name || !draft.name.trim()) {
    return "股票名称不能为空";
  }
  if (!["buy", "add", "reduce", "sell"].includes(draft.operation)) {
    return "操作类型不合法";
  }
  if (!["full", "partial", "not_executed"].includes(draft.execution_status)) {
    return "执行状态不合法";
  }

  const plannedPrice = draft.planned_price != null && draft.planned_price !== "" ? Number(draft.planned_price) : null;
  const plannedQty = draft.planned_quantity != null && draft.planned_quantity !== "" ? Number(draft.planned_quantity) : null;
  const actualPrice = draft.actual_price != null && draft.actual_price !== "" ? Number(draft.actual_price) : null;
  const actualQty = draft.actual_quantity != null && draft.actual_quantity !== "" ? Number(draft.actual_quantity) : null;

  if (plannedPrice != null && (!Number.isFinite(plannedPrice) || plannedPrice <= 0)) {
    return "计划价格必须大于 0";
  }
  if (plannedQty != null && (!Number.isFinite(plannedQty) || plannedQty <= 0 || !Number.isInteger(plannedQty))) {
    return "计划数量必须是正整数";
  }

  if (draft.execution_status === "full") {
    if (actualPrice == null || !Number.isFinite(actualPrice) || actualPrice <= 0) {
      return "已全部执行状态下，实际价格必须大于 0";
    }
    if (actualQty == null || !Number.isFinite(actualQty) || actualQty <= 0 || !Number.isInteger(actualQty)) {
      return "已全部执行状态下，实际数量必须是正整数";
    }
    if (!draft.executed_at) {
      return "已全部执行状态下，成交时间不能为空";
    }
    if (!canonicalizeTradeExecutionTime(draft.executed_at)) {
      return "已全部执行状态下，成交时间不合法";
    }
    if (plannedQty != null && plannedQty > 0 && actualQty !== plannedQty) {
      return "已全部执行状态下，实际数量必须等于计划数量";
    }
    if (draft.unexecuted_reason?.trim()) {
      return "已全部执行状态下，不得填写未执行原因";
    }
  } else if (draft.execution_status === "partial") {
    if (plannedQty == null || !Number.isFinite(plannedQty) || plannedQty <= 0 || !Number.isInteger(plannedQty)) {
      return "部分执行状态下，计划数量必须是正整数";
    }
    if (actualPrice == null || !Number.isFinite(actualPrice) || actualPrice <= 0) {
      return "部分执行状态下，实际价格必须大于 0";
    }
    if (actualQty == null || !Number.isFinite(actualQty) || actualQty <= 0 || !Number.isInteger(actualQty)) {
      return "部分执行状态下，实际数量必须是正整数";
    }
    if (actualQty >= plannedQty) {
      return "部分执行状态下，实际数量必须小于计划数量";
    }
    if (!draft.executed_at) {
      return "部分执行状态下，成交时间不能为空";
    }
    if (!canonicalizeTradeExecutionTime(draft.executed_at)) {
      return "部分执行状态下，成交时间不合法";
    }
    if (!draft.unexecuted_reason || !draft.unexecuted_reason.trim()) {
      return "部分执行状态下，未执行原因不能为空";
    }
  } else if (draft.execution_status === "not_executed") {
    if (!draft.unexecuted_reason || !draft.unexecuted_reason.trim()) {
      return "未执行状态下，未执行原因不能为空";
    }
  }

  const fee = draft.fee != null && draft.fee !== "" ? Number(draft.fee) : 0;
  const otherCost = draft.other_cost != null && draft.other_cost !== "" ? Number(draft.other_cost) : 0;
  if (!Number.isFinite(fee) || fee < 0) {
    return "手续费不得小于 0";
  }
  if (!Number.isFinite(otherCost) || otherCost < 0) {
    return "其他费用不得小于 0";
  }

  if (draft.advice_ref) {
    if (!draft.advice_ref.trade_date.trim() || !draft.advice_ref.generated_at.trim()) {
      return "建议引用需同时填写交易日期和生成时间";
    }
  }

  if (draft.thesis_ref) {
    if (!draft.thesis_ref.thesis_id.trim() || !Number.isInteger(draft.thesis_ref.revision_number) || draft.thesis_ref.revision_number <= 0) {
      return "Thesis 引用需填写有效 ID 和正整数版本号";
    }
  }

  return null;
}

export function buildTradeCreateInput(draft: TradeDraft): TradeCreateInput {
  const isNotExecuted = draft.execution_status === "not_executed";

  const plannedPrice = draft.planned_price != null && draft.planned_price !== "" ? Number(draft.planned_price) : null;
  const plannedQty = draft.planned_quantity != null && draft.planned_quantity !== "" ? Number(draft.planned_quantity) : null;
  const actualPrice = isNotExecuted ? null : (draft.actual_price != null && draft.actual_price !== "" ? Number(draft.actual_price) : null);
  const actualQty = isNotExecuted ? 0 : (draft.actual_quantity != null && draft.actual_quantity !== "" ? Number(draft.actual_quantity) : 0);

  const executedAt = isNotExecuted
    ? null
    : canonicalizeTradeExecutionTime(draft.executed_at);

  const fee = isNotExecuted ? 0 : (draft.fee != null && draft.fee !== "" ? Number(draft.fee) : 0);
  const otherCost = isNotExecuted ? 0 : (draft.other_cost != null && draft.other_cost !== "" ? Number(draft.other_cost) : 0);

  const res: TradeCreateInput = {
    code: draft.code.trim(),
    name: draft.name.trim(),
    operation: draft.operation,
    execution_status: draft.execution_status,
    planned_price: plannedPrice,
    planned_quantity: plannedQty,
    unexecuted_reason: draft.unexecuted_reason?.trim() || null,
    note: draft.note?.trim() || null,
  };

  if (!isNotExecuted) {
    res.actual_price = actualPrice;
    res.actual_quantity = actualQty;
    res.executed_at = executedAt;
    res.fee = fee;
    res.other_cost = otherCost;
  }

  if (draft.advice_ref) {
    res.advice_ref = {
      trade_date: draft.advice_ref.trade_date,
      generated_at: draft.advice_ref.generated_at,
    };
  }

  if (draft.thesis_ref) {
    res.thesis_ref = {
      thesis_id: draft.thesis_ref.thesis_id.trim(),
      revision_number: draft.thesis_ref.revision_number,
    };
  }

  return res;
}

export function validateTradeListFilters(filters: TradeListFilters): string | null {
  if (filters.code?.trim() && !/^\d{6}$/.test(filters.code.trim())) {
    return "股票代码筛选必须是 6 位数字";
  }
  if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
    return "开始日期不得晚于结束日期";
  }
  return null;
}

export function buildTradeListQuery(
  filters: TradeListFilters,
  limit?: number,
  offset?: number,
): TradeListQuery {
  const query: TradeListQuery = {};
  if (filters.code?.trim()) query.code = filters.code.trim();
  if (filters.operation) query.operation = filters.operation;
  if (filters.execution_status) query.execution_status = filters.execution_status;
  if (filters.date_from) query.date_from = filters.date_from;
  if (filters.date_to) query.date_to = filters.date_to;
  if (filters.include_voided != null) query.include_voided = filters.include_voided;
  if (limit != null) query.limit = limit;
  if (offset != null) query.offset = offset;
  return query;
}
