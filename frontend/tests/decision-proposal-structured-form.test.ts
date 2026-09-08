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
  assert.match(source, /aria-label="对这只股票的判断"/);
  assert.match(source, /aria-label="当前操作倾向"/);
  assert.match(source, /aria-label="股票判断说明"/);
  assert.match(source, /aria-label="操作倾向说明"/);
  assert.match(source, /aria-label="组合层面的限制"/);
  // payload 仍由纯模块生成，Preview → Confirm → Freeze 流程不变
  assert.match(source, /buildJudgedView\("ASSET", assetStance, assetNote\)/);
  assert.match(source, /buildJudgedView\("TRADE", tradeStance, tradeNote\)/);
  assert.match(source, /buildPortfolioView\(portfolioConstraint\)/);
  assert.match(source, /预览决策草案/);
  assert.match(source, /确认并冻结正式决策/);
});

test("PRE-ENTRY 使用结构化 Candidate Opportunity 表单且不暴露 JSON 输入", () => {
  const source = readFileSync(
    new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /CANDIDATE_SCENARIOS\.map/);
  assert.match(source, /aria-label=\{`\$\{CANDIDATE_SCENARIO_LABELS\[scenario\]\} price low`\}/);
  for (const label of ["Candidate entry low", "Candidate invalidation price"]) {
    assert.match(source, new RegExp(`aria-label="${label}"`));
  }
  for (const key of ["data_quality", "evidence_confidence", "inference_confidence", "decision_confidence"]) {
    assert.match(source, new RegExp(`${key}:`));
  }
  assert.match(source, /assetView\.candidate_valuation = candidateValuation\.cases/);
  assert.match(source, /Object\.assign\(tradeView, candidateTradeTerms\)/);
  assert.match(source, /信息不足.*继续研究/);
  assert.doesNotMatch(source, /Candidate Opportunity（JSON/);
});
