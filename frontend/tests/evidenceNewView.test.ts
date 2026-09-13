import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { evidenceReturnToLabel } from "../src/lib/internalReturnTo.ts";

test("candidate return_to uses 候选研究, not Candidate Workspace", () => {
  assert.equal(evidenceReturnToLabel("/candidates/600519"), "候选研究");
  assert.notEqual(evidenceReturnToLabel("/candidates/600519"), "Candidate Workspace");
});

test("thesis and stock-data return_to use Chinese labels instead of generic 返回", () => {
  assert.equal(evidenceReturnToLabel("/thesis"), "投资逻辑");
  assert.equal(evidenceReturnToLabel("/thesis/abc"), "投资逻辑");
  assert.equal(evidenceReturnToLabel("/stock-data"), "个股数据");
  assert.equal(evidenceReturnToLabel("/stock-data?code=600519"), "个股数据");
  assert.equal(evidenceReturnToLabel("/evidence"), "返回");
  assert.equal(evidenceReturnToLabel(""), "证据库");
});

test("ThesisNew and EvidenceNew source do not contain Candidate Workspace or （claim）", () => {
  const evidenceNew = readFileSync(new URL("../src/pages/EvidenceNew.tsx", import.meta.url), "utf8");
  const thesisNew = readFileSync(new URL("../src/pages/ThesisNew.tsx", import.meta.url), "utf8");
  for (const [name, source] of [["EvidenceNew", evidenceNew], ["ThesisNew", thesisNew]] as const) {
    assert.doesNotMatch(source, /Candidate Workspace/, `${name} must not show Candidate Workspace`);
    assert.doesNotMatch(source, /（claim）/, `${name} must not display （claim）`);
  }
  assert.match(evidenceNew, /from "@\/lib\/internalReturnTo"/);
  assert.match(evidenceNew, /evidenceReturnToLabel\(returnTo\)/);
  assert.match(evidenceNew, /请填写证据论断/);
  assert.match(evidenceNew, /claim:/);
});
