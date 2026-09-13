/** Display-only Chinese chrome. Canonical origin UNPLANNED and decision_id stay in data/API. */

export const TRADE_ORIGIN_UNPLANNED = "UNPLANNED" as const;

export const TRADE_CONTINUATION_BANNER = "从已冻结决策续接实际执行";
export const TRADE_CANONICAL_UTC_ISO_LABEL = "规范 UTC ISO：";
export const TRADE_RECONCILIATION_POLICY_COPY =
  "只接受明确归属到已冻结决策，或明确标记为非计划内；系统不会自动匹配。";
export const TRADE_FROZEN_DECISION_LABEL = "已冻结决策：";
export const TRADE_UNPLANNED_ORIGIN_COPY =
  "来源：明确非计划内（pre_trade_decision=NONE，pre_trade_thesis=NONE）";
export const TRADE_RECONCILIATION_REQUIRED_COPY =
  "需要对账：选择真实、已提交且时间有效的已冻结决策";
export const TRADE_WITNESS_INVALID_COPY =
  "发现已冻结决策，但见证校验失败，系统已拒绝归属；请修复决策数据或联系管理员。";
export const TRADE_NO_CANDIDATE_UNPLANNED_COPY =
  "没有可归属候选；若该交易确实非计划内，请明确标记为非计划内，系统不会猜测。";
export const TRADE_CONTINUATION_CANDIDATE_HINT = "来自己冻结决策续接；仍需你明确归属";
export const TRADE_MARK_UNPLANNED_BUTTON = "标记为非计划内";
export const TRADE_MARK_UNPLANNED_FAILED = "标记为非计划内失败";
export const TRADE_TECHNICAL_DETAILS_LABEL = "技术详情";
