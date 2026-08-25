import type {
  DecisionInboxCampaignItem,
  DecisionInboxFrozenDecision,
  DecisionInboxSellEngine,
} from "./api/types";
import { buildEvaluatedTradeContinuationHref } from "./tradeContinuation.ts";

const DECISION_ID_RE = /^decision_[0-9a-f]{32}$/;
const THESIS_ID_RE = /^[0-9a-f]{32}$/;
const SELL_ENGINE_SCHEMA_VERSION = "sell_engine.projection.vnext.v0.1";
const SELL_ENGINE_AUTHORITY_REF = "sell_engine:projection:vnext.v0.1";
const SELL_STATES = new Set([
  "HOLD",
  "WATCH_TO_REDUCE",
  "REDUCE",
  "EXIT",
  "THESIS_INVALIDATED",
]);
const EVALUATIONS = new Set(["EVALUATED", "UNKNOWN", "NOT_EVALUATED", "ERROR"]);

const ACTION_LABELS: Record<string, string> = {
  "BUY NOW": "立即买入",
  "BUY SMALL": "小仓位买入",
  "SCALE IN": "逐步加仓",
  WAIT: "等待",
  HOLD: "继续持有",
  "WATCH TO REDUCE": "观察并准备减仓",
  REDUCE: "减仓",
  EXIT: "退出",
  AVOID: "回避",
  "RESEARCH MORE": "继续研究",
};

const SELL_LABELS: Record<string, string> = {
  HOLD: "持有",
  WATCH_TO_REDUCE: "观察并准备减仓",
  REDUCE: "减仓",
  EXIT: "退出",
  THESIS_INVALIDATED: "投资逻辑已失效",
};

const REASON_LABELS: Record<string, string> = {
  THESIS_INVALIDATION: "投资逻辑失效",
  RISK_EXIT: "风险退出压力",
  EXPECTATION_PRICE_IN: "预期已计价",
  RISK_REWARD_DETERIORATION: "风险收益比恶化",
  CATALYST_FAILURE: "催化剂未兑现",
  PORTFOLIO_REBALANCE: "组合再平衡",
  OPPORTUNITY_COST: "机会成本",
  TECHNICAL_EXECUTION: "技术执行条件",
};

export interface FrozenDecisionPresentation {
  state: "MISSING" | "APPLICABLE" | "HISTORICAL" | "INVALID";
  title: string;
  decisionId: string | null;
  action: string | null;
  actionLabel: string;
  committedAt: string | null;
  reviewBy: string | null;
  reviewState: "DUE" | "UPCOMING" | "UNKNOWN";
  tradeHref: string | null;
}

export interface SellEnginePresentation {
  state: "AVAILABLE" | "INCOMPLETE" | "ERROR" | "UNAVAILABLE";
  evaluation: string;
  sellState: string | null;
  sellLabel: string;
  primaryReason: string | null;
  primaryReasonLabel: string;
  reviewPressure: boolean;
  holdPositiveProof: boolean;
  uncertainties: string[];
  asOf: string | null;
}

function validIso(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "" && Number.isFinite(Date.parse(value));
}

function validFrozenDecision(value: unknown): value is DecisionInboxFrozenDecision {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.decision_id === "string"
    && DECISION_ID_RE.test(record.decision_id)
    && validIso(record.committed_at)
    && validIso(record.review_by)
    && typeof record.previous_next_best_action === "string"
    && record.previous_next_best_action.trim() !== ""
  );
}

export function presentFrozenDecision(
  item: DecisionInboxCampaignItem,
): FrozenDecisionPresentation {
  const frozen = item.last_frozen_decision;
  if (frozen === null || frozen === undefined) {
    return {
      state: "MISSING",
      title: "尚无 Frozen Decision",
      decisionId: null,
      action: null,
      actionLabel: "尚未形成用户冻结决策",
      committedAt: null,
      reviewBy: null,
      reviewState: "UNKNOWN",
      tradeHref: null,
    };
  }
  if (!validFrozenDecision(frozen)) {
    return {
      state: "INVALID",
      title: "Frozen Decision 当前不可读",
      decisionId: null,
      action: null,
      actionLabel: "不会从不完整数据推断历史动作",
      committedAt: null,
      reviewBy: null,
      reviewState: "UNKNOWN",
      tradeHref: null,
    };
  }
  const applicable = item.formal_decision_evaluation === "EVALUATED";
  const executable = new Set(["BUY NOW", "BUY SMALL", "SCALE IN", "REDUCE", "EXIT"]).has(
    frozen.previous_next_best_action,
  );
  const asOf = validIso(item.as_of) ? Date.parse(item.as_of) : null;
  const reviewAt = Date.parse(frozen.review_by);
  const reviewState = asOf === null
    ? "UNKNOWN"
    : asOf >= reviewAt ? "DUE" : "UPCOMING";
  return {
    state: applicable ? "APPLICABLE" : "HISTORICAL",
    title: applicable
      ? "本次快照适用的 Frozen Decision"
      : "上一份 Frozen Decision（历史）",
    decisionId: frozen.decision_id,
    action: frozen.previous_next_best_action,
    actionLabel: ACTION_LABELS[frozen.previous_next_best_action]
      ?? frozen.previous_next_best_action,
    committedAt: frozen.committed_at,
    reviewBy: frozen.review_by,
    reviewState,
    tradeHref: executable
      ? buildEvaluatedTradeContinuationHref({
          securityCode: item.security_code,
          continuationRef: item.trade_continuation_ref,
          formalDecisionEvaluation: item.formal_decision_evaluation,
        })
      : null,
  };
}

function stringArray(value: unknown, allowEmpty = true): value is string[] {
  return (
    Array.isArray(value)
    && (allowEmpty || value.length > 0)
    && value.every((entry) => typeof entry === "string" && entry.trim() !== "")
  );
}

function validSellEngine(
  value: unknown,
  item: DecisionInboxCampaignItem,
): value is DecisionInboxSellEngine {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    record.schema_version === SELL_ENGINE_SCHEMA_VERSION
    && record.authority_ref === SELL_ENGINE_AUTHORITY_REF
    && record.security_code === item.security_code
    && record.strategy === item.strategy
    && record.campaign_id === item.campaign_id
    && record.as_of === item.as_of
    && validIso(record.as_of)
    && typeof record.sell_evaluation === "string"
    && EVALUATIONS.has(record.sell_evaluation)
    && (record.sell_state === null || (typeof record.sell_state === "string" && SELL_STATES.has(record.sell_state)))
    && typeof record.review_pressure === "boolean"
    && typeof record.hold_positive_proof === "boolean"
    && stringArray(record.reason_codes)
    && stringArray(record.supporting_reasons)
    && stringArray(record.opposing_reasons)
    && stringArray(record.uncertainties)
    && stringArray(record.authority_refs, false)
    && (record.primary_reason === null || (
      typeof record.primary_reason === "string"
      && Object.prototype.hasOwnProperty.call(REASON_LABELS, record.primary_reason)
    ))
    && (record.thesis_id === null || (typeof record.thesis_id === "string" && THESIS_ID_RE.test(record.thesis_id)))
    && (record.thesis_revision === null || (Number.isInteger(record.thesis_revision) && Number(record.thesis_revision) >= 1))
    && Boolean(record.dimensions)
    && typeof record.dimensions === "object"
    && !Array.isArray(record.dimensions)
  );
}

export function presentSellEngine(
  item: DecisionInboxCampaignItem,
): SellEnginePresentation {
  const value = item.sell_engine;
  if (!validSellEngine(value, item)) {
    return {
      state: "UNAVAILABLE",
      evaluation: "NOT_EVALUATED",
      sellState: null,
      sellLabel: "当前没有可验证的 Sell Review",
      primaryReason: null,
      primaryReasonLabel: "—",
      reviewPressure: false,
      holdPositiveProof: false,
      uncertainties: [],
      asOf: null,
    };
  }
  if (value.sell_state === "HOLD" && !value.hold_positive_proof) {
    return {
      state: "ERROR",
      evaluation: "ERROR",
      sellState: null,
      sellLabel: "HOLD 缺少正面证明，已停止展示结论",
      primaryReason: value.primary_reason,
      primaryReasonLabel: value.primary_reason
        ? REASON_LABELS[value.primary_reason] ?? value.primary_reason
        : "—",
      reviewPressure: value.review_pressure,
      holdPositiveProof: false,
      uncertainties: value.uncertainties,
      asOf: value.as_of,
    };
  }
  const state = value.sell_evaluation === "ERROR"
    ? "ERROR"
    : value.sell_evaluation === "EVALUATED" ? "AVAILABLE" : "INCOMPLETE";
  return {
    state,
    evaluation: value.sell_evaluation,
    sellState: value.sell_state,
    sellLabel: value.sell_state
      ? SELL_LABELS[value.sell_state] ?? value.sell_state
      : "尚未形成卖出结论",
    primaryReason: value.primary_reason,
    primaryReasonLabel: value.primary_reason
      ? REASON_LABELS[value.primary_reason] ?? value.primary_reason
      : "—",
    reviewPressure: value.review_pressure,
    holdPositiveProof: value.hold_positive_proof,
    uncertainties: value.uncertainties,
    asOf: value.as_of,
  };
}
