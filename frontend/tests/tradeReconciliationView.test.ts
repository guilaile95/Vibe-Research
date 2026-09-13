import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  TRADE_CANONICAL_UTC_ISO_LABEL,
  TRADE_CONTINUATION_BANNER,
  TRADE_CONTINUATION_CANDIDATE_HINT,
  TRADE_FROZEN_DECISION_LABEL,
  TRADE_MARK_UNPLANNED_BUTTON,
  TRADE_MARK_UNPLANNED_FAILED,
  TRADE_NO_CANDIDATE_UNPLANNED_COPY,
  TRADE_ORIGIN_UNPLANNED,
  TRADE_RECONCILIATION_POLICY_COPY,
  TRADE_RECONCILIATION_REQUIRED_COPY,
  TRADE_TECHNICAL_DETAILS_LABEL,
  TRADE_UNPLANNED_ORIGIN_COPY,
  TRADE_WITNESS_INVALID_COPY,
} from "../src/lib/tradeReconciliationView.ts";

test("trades reconciliation chrome is Chinese while canonical origin stays UNPLANNED", () => {
  assert.equal(TRADE_ORIGIN_UNPLANNED, "UNPLANNED");
  assert.equal(TRADE_CONTINUATION_BANNER, "从已冻结决策续接实际执行");
  assert.equal(TRADE_CANONICAL_UTC_ISO_LABEL, "规范 UTC ISO：");
  assert.equal(
    TRADE_RECONCILIATION_POLICY_COPY,
    "只接受明确归属到已冻结决策，或明确标记为非计划内；系统不会自动匹配。",
  );
  assert.equal(TRADE_FROZEN_DECISION_LABEL, "已冻结决策：");
  assert.equal(
    TRADE_UNPLANNED_ORIGIN_COPY,
    "来源：明确非计划内（pre_trade_decision=NONE，pre_trade_thesis=NONE）",
  );
  assert.match(TRADE_UNPLANNED_ORIGIN_COPY, /pre_trade_decision=NONE/);
  assert.match(TRADE_UNPLANNED_ORIGIN_COPY, /pre_trade_thesis=NONE/);
  assert.doesNotMatch(TRADE_UNPLANNED_ORIGIN_COPY, /明确 UNPLANNED/);
  assert.equal(TRADE_RECONCILIATION_REQUIRED_COPY, "需要对账：选择真实、已提交且时间有效的已冻结决策");
  assert.equal(
    TRADE_WITNESS_INVALID_COPY,
    "发现已冻结决策，但见证校验失败，系统已拒绝归属；请修复决策数据或联系管理员。",
  );
  assert.equal(
    TRADE_NO_CANDIDATE_UNPLANNED_COPY,
    "没有可归属候选；若该交易确实非计划内，请明确标记为非计划内，系统不会猜测。",
  );
  assert.equal(TRADE_CONTINUATION_CANDIDATE_HINT, "来自己冻结决策续接；仍需你明确归属");
  assert.equal(TRADE_MARK_UNPLANNED_BUTTON, "标记为非计划内");
  assert.equal(TRADE_MARK_UNPLANNED_FAILED, "标记为非计划内失败");
  assert.equal(TRADE_TECHNICAL_DETAILS_LABEL, "技术详情");
});

test("Trades wires reconciliation chrome from the view lib without changing write contracts", () => {
  const source = readFileSync(new URL("../src/pages/Trades.tsx", import.meta.url), "utf8");
  assert.match(source, /from "@\/lib\/tradeReconciliationView"/);
  assert.match(source, /TRADE_CONTINUATION_BANNER/);
  assert.match(source, /TRADE_CANONICAL_UTC_ISO_LABEL/);
  assert.match(source, /TRADE_RECONCILIATION_POLICY_COPY/);
  assert.match(source, /TRADE_FROZEN_DECISION_LABEL/);
  assert.match(source, /TRADE_UNPLANNED_ORIGIN_COPY/);
  assert.match(source, /TRADE_RECONCILIATION_REQUIRED_COPY/);
  assert.match(source, /TRADE_WITNESS_INVALID_COPY/);
  assert.match(source, /TRADE_NO_CANDIDATE_UNPLANNED_COPY/);
  assert.match(source, /TRADE_CONTINUATION_CANDIDATE_HINT/);
  assert.match(source, /TRADE_MARK_UNPLANNED_BUTTON/);
  assert.match(source, /TRADE_MARK_UNPLANNED_FAILED/);
  assert.match(source, /TRADE_TECHNICAL_DETAILS_LABEL/);
  assert.match(source, /data-origin=\{TRADE_ORIGIN_UNPLANNED\}/);
  assert.match(source, /origin=\{reconciliation\.origin\}/);
  assert.match(source, /decision_id=\{reconciliation\.decision_id\}/);
  assert.match(source, /api\.markTradeUnplanned\(tradeId\)/);
  assert.match(source, /api\.attributeTrade\(tradeId, decisionId\)/);
  assert.doesNotMatch(source, /从 Frozen Decision 续接实际执行/);
  assert.doesNotMatch(source, /Canonical UTC ISO/);
  assert.doesNotMatch(source, /仅接受明确 Frozen Decision 归属或明确 UNPLANNED/);
  assert.doesNotMatch(source, /Frozen Decision：/);
  assert.doesNotMatch(source, /来源：明确 UNPLANNED/);
  assert.doesNotMatch(source, /RECONCILIATION REQUIRED/);
  assert.doesNotMatch(source, /发现 Frozen Decision，但见证校验失败/);
  assert.doesNotMatch(source, /请明确标记 UNPLANNED/);
  assert.doesNotMatch(source, /来自 Frozen Decision 续接/);
  assert.doesNotMatch(source, /标记为 UNPLANNED/);
  assert.doesNotMatch(source, /标记 UNPLANNED 失败/);
  assert.doesNotMatch(source, /\bBUY\b|\bSELL\b/);
});
