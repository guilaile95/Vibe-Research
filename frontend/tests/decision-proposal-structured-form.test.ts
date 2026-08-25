// P1-DF1：Formal Decision 三视图结构化输入的行为测试（真实函数断言）。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  VIEW_STANCE_LABELS,
  VIEW_STANCE_OPTIONS,
  buildJudgedView,
  buildPortfolioView,
  joinDraftLines,
} from "../src/lib/decisionProposalForm.ts";

test("stance 枚举封闭且含中文标签", () => {
  assert.deepEqual(VIEW_STANCE_OPTIONS, ["WAIT", "SUPPORT", "OPPOSE"]);
  for (const option of VIEW_STANCE_OPTIONS) {
    assert.equal(typeof VIEW_STANCE_LABELS[option], "string");
  }
});

test("buildJudgedView 生成既有模板骨架 {view, stance[, note]}", () => {
  assert.deepEqual(buildJudgedView("ASSET", "WAIT", ""), { view: "ASSET", stance: "WAIT" });
  assert.deepEqual(buildJudgedView("TRADE", "SUPPORT", ""), { view: "TRADE", stance: "SUPPORT" });
  assert.deepEqual(buildJudgedView("ASSET", "OPPOSE", "  需求走弱  "), {
    view: "ASSET",
    stance: "OPPOSE",
    note: "需求走弱",
  });
});

test("buildPortfolioView 生成 {view[, constraint]}，留空不伪造约束", () => {
  assert.deepEqual(buildPortfolioView(""), { view: "PORTFOLIO" });
  assert.deepEqual(buildPortfolioView(" 单笔风险不超过组合 2% "), {
    view: "PORTFOLIO",
    constraint: "单笔风险不超过组合 2%",
  });
});

test("Apply AI Draft 将 assumptions 与 invalidations 保留为真实多行文本", () => {
  assert.equal(joinDraftLines(["估值维持合理", "现金流不恶化"]), "估值维持合理\n现金流不恶化");
  assert.equal(joinDraftLines(["业绩低于预期", "核心产品降价"]), "业绩低于预期\n核心产品降价");
});

test("页面使用真实换行写入 AI Draft 数组", () => {
  const source = readFileSync(
    new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /joinDraftLines\(fields\.key_assumptions\)/);
  assert.match(source, /joinDraftLines\(fields\.event_invalidation_conditions\)/);
  assert.doesNotMatch(source, /join\("\\\\n"\)/);
});

test("页面不再要求手写三份 JSON object，改用结构化控件", () => {
  const source = readFileSync(
    new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url),
    "utf8",
  );
  // 旧的 JSON textarea 输入路径必须移除
  assert.doesNotMatch(source, /Asset View（JSON object）/);
  assert.doesNotMatch(source, /Trade View（JSON object）/);
  assert.doesNotMatch(source, /Portfolio View（JSON object）/);
  assert.doesNotMatch(source, /parseObject/);
  assert.doesNotMatch(source, /JSON\.stringify\(\{ view:/);
  // 新结构化控件存在
  assert.match(source, /aria-label="Asset stance"/);
  assert.match(source, /aria-label="Trade stance"/);
  assert.match(source, /aria-label="Asset note"/);
  assert.match(source, /aria-label="Trade note"/);
  assert.match(source, /aria-label="Portfolio constraint"/);
  // payload 仍由纯模块生成，Preview → Confirm → Freeze 流程不变
  assert.match(source, /buildJudgedView\("ASSET", assetStance, assetNote\)/);
  assert.match(source, /buildJudgedView\("TRADE", tradeStance, tradeNote\)/);
  assert.match(source, /buildPortfolioView\(portfolioConstraint\)/);
  assert.match(source, /Preview Proposal/);
  assert.match(source, /Freeze Formal Decision/);
});
