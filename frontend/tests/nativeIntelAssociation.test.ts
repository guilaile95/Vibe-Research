import assert from "node:assert/strict";
import test from "node:test";
import { articleAssociationDetail, articleAssociationText } from "../src/lib/nativeIntelAssociation.ts";
import type { NativeIntelItemEntity } from "../src/lib/api/types.ts";

const industry: NativeIntelItemEntity = {
  security_code: "600519", term_kind: "industry", term: "白酒",
  matched_in: "title", source_ref: "industry-directory",
};

test("shared industry matches collapse to one readable word while details preserve each security and source", () => {
  const entities = [industry, ...Array.from({ length: 30 }, (_, i) => ({ ...industry, security_code: String(i).padStart(6, "0") }))];
  assert.equal(articleAssociationText(entities), "关联词：行业词「白酒」。词面关联不代表公司直接事件。");
  assert.equal(articleAssociationDetail(entities[1]), "标题命中 000000 映射的行业词「白酒」（当前映射来源：industry-directory）");
  assert.equal(articleAssociationDetail(industry), "标题命中 600519 映射的行业词「白酒」（当前映射来源：industry-directory）");
});

test("summary deduplicates words across locations and sources, preserving different kinds", () => {
  const entities = [industry,
    { ...industry, matched_in: "summary", source_ref: "other-source" },
    { ...industry, term_kind: "concept" },
  ];
  assert.equal(articleAssociationText(entities), "关联词：行业词「白酒」、概念词「白酒」。词面关联不代表公司直接事件。");
  assert.match(articleAssociationDetail(entities[1]), /摘要命中.*当前映射来源：other-source/);
});

test("code and company name remain lexical evidence", () => {
  const text = articleAssociationText([
    { ...industry, term_kind: "security_code", term: "600519" },
    { ...industry, term_kind: "company_name", term: "贵州茅台" },
  ]);
  assert.equal(text, "关联词：证券代码词「600519」、公司名称词「贵州茅台」。词面关联不代表公司直接事件。");
});

test("summary bounds distinct and long words; details keep the complete match", () => {
  const entities = [industry, ...["消费升级", "内需", "渠道", "长".repeat(80)].map((term) => ({ ...industry, term_kind: "concept", term }))];
  const summary = articleAssociationText(entities);
  assert.match(summary, /行业词「白酒」、概念词「消费升级」、概念词「内需」等 5 项/);
  assert.ok(!summary.includes("渠道"));
  const long = entities[4];
  assert.ok(articleAssociationText([long]).includes(`${"长".repeat(24)}…`));
  assert.ok(articleAssociationDetail(long).includes(long.term));
});

test("missing associations and unknown fields stay explicit", () => {
  for (const entities of [undefined, []]) {
    assert.equal(articleAssociationText(entities), "文章关联依据：暂无已保存的词面关联，相关性未知。");
  }
  const entity = { ...industry, security_code: null, term_kind: "other", matched_in: "other", source_ref: null };
  assert.equal(articleAssociationDetail(entity), "命中位置未知 证券未知 映射的未知类型词「白酒」（当前映射来源：未知）");
  assert.match(articleAssociationText([entity]), /未知类型词「白酒」.*不代表公司直接事件/);
});
