import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { decisionActionLabel } from "../src/lib/decisionActionView.ts";
import { CAMPAIGN_STRATEGY_LABELS } from "../src/lib/decisionInbox.ts";
import {
  campaignStrategyLabel,
  committedDecisionIdentityTitle,
  committedDecisionNbaLabel,
  validityStatusAtCommitLabel,
} from "../src/lib/committedDecisionView.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(__dirname, "../src");
const DECISION_ID = "decision_" + "b".repeat(32);

test("identity title is security code, strategy label, and NBA label", () => {
  assert.equal(
    committedDecisionIdentityTitle({
      securityCode: "600519",
      strategy: "SWING",
      nextBestAction: "WAIT",
    }),
    "600519 · 波段 · 等待",
  );
  assert.equal(
    committedDecisionIdentityTitle({
      securityCode: "600519",
      strategy: "MEDIUM",
      nextBestAction: "HOLD",
    }),
    "600519 · 中线 · 继续持有",
  );
  assert.equal(
    committedDecisionIdentityTitle({
      securityCode: "000001",
      strategy: "SHORT",
      nextBestAction: "EXIT",
    }),
    "000001 · 短线 · 退出",
  );
  assert.equal(campaignStrategyLabel("SHORT"), CAMPAIGN_STRATEGY_LABELS.SHORT);
  assert.equal(campaignStrategyLabel("SWING"), CAMPAIGN_STRATEGY_LABELS.SWING);
  assert.equal(campaignStrategyLabel("MEDIUM"), CAMPAIGN_STRATEGY_LABELS.MEDIUM);
  assert.equal(committedDecisionNbaLabel("WAIT"), decisionActionLabel("WAIT"));
  assert.equal(committedDecisionNbaLabel("HOLD"), decisionActionLabel("HOLD"));
  assert.equal(committedDecisionNbaLabel("EXIT"), decisionActionLabel("EXIT"));
});

test("missing NBA stays 信息不足 and is never inferred as BUY or SELL", () => {
  for (const value of ["", "  ", null, undefined, 42, { action: "WAIT" }]) {
    const title = committedDecisionIdentityTitle({
      securityCode: "600519",
      strategy: "SWING",
      nextBestAction: value,
    });
    assert.equal(title, "600519 · 波段 · 信息不足");
    assert.equal(committedDecisionNbaLabel(value), "信息不足");
    assert.notEqual(committedDecisionNbaLabel(value), "立即买入");
    assert.notEqual(committedDecisionNbaLabel(value), "买入");
    assert.notEqual(committedDecisionNbaLabel(value), "BUY");
    assert.notEqual(committedDecisionNbaLabel(value), "SELL");
    assert.equal(title.includes("BUY"), false);
    assert.equal(title.includes("SELL"), false);
    assert.equal(title.includes("买入"), false);
    assert.equal(title.includes("卖出"), false);
  }
});

test("unmapped NBA uses the Decision Inbox unknown action label, never BUY/SELL", () => {
  assert.equal(committedDecisionNbaLabel("FUTURE_ACTION"), "无法识别的操作");
  assert.equal(committedDecisionNbaLabel("FUTURE_ACTION"), decisionActionLabel("FUTURE_ACTION"));
  const title = committedDecisionIdentityTitle({
    securityCode: "600519",
    strategy: "SWING",
    nextBestAction: "FUTURE_ACTION",
  });
  assert.equal(title, "600519 · 波段 · 无法识别的操作");
  assert.equal(title.includes("BUY"), false);
  assert.equal(title.includes("SELL"), false);
});

test("identity title does not use decision_id or invent a security name", () => {
  const title = committedDecisionIdentityTitle({
    securityCode: "600519",
    strategy: "SWING",
    nextBestAction: "WAIT",
  });
  assert.equal(title.includes(DECISION_ID), false);
  assert.equal(title.includes("decision_"), false);
  assert.equal(title.includes("茅台"), false);
  assert.equal(campaignStrategyLabel("UNKNOWN_HORIZON"), "UNKNOWN_HORIZON");
  assert.equal(
    committedDecisionIdentityTitle({
      securityCode: "",
      strategy: null,
      nextBestAction: "HOLD",
    }),
    "— · — · 继续持有",
  );
});

test("known validity_status_at_commit is labeled; unknown values stay as-is", () => {
  assert.equal(validityStatusAtCommitLabel("CURRENT"), "当前");
  assert.equal(validityStatusAtCommitLabel("EXPIRED"), "EXPIRED");
  assert.equal(validityStatusAtCommitLabel(""), null);
  assert.equal(validityStatusAtCommitLabel(null), null);
  assert.equal(validityStatusAtCommitLabel(undefined), null);
});

test("inbox committed card titles identity and keeps decision_id secondary", () => {
  const card = readFileSync(join(srcRoot, "components/campaign/CampaignCommittedDecisionsCard.tsx"), "utf8");
  const inbox = readFileSync(join(srcRoot, "pages/DecisionInbox.tsx"), "utf8");
  assert.match(card, /committedDecisionIdentityTitle/);
  assert.match(card, /validityStatusAtCommitLabel/);
  assert.match(card, /securityCode/);
  assert.match(card, /strategy/);
  assert.doesNotMatch(card, /<p className="font-mono">\{item\.decision_id\}<\/p>/);
  assert.match(card, /decision_id: \{item\.decision_id\}/);
  assert.doesNotMatch(card, /当时结论：\$\{item\.next_best_action\}/);
  assert.match(
    inbox,
    /<CampaignCommittedDecisionsCard[\s\S]*securityCode=\{campaign\.security_code\}[\s\S]*strategy=\{campaign\.strategy\}/,
  );
  assert.match(
    inbox,
    /<CampaignCommittedDecisionsCard[\s\S]*securityCode=\{item\.security_code\}[\s\S]*strategy=\{item\.strategy\}/,
  );
});
