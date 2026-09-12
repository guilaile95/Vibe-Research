import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CHALLENGE_DIMENSIONS_INPUT_MESSAGE,
  challengeDimensionsReady,
  challengeFinalizeFailureReadState,
} from "../src/lib/decisionChallengeForm.ts";
import { DECISION_CHALLENGE_DIMENSIONS } from "../src/lib/api.ts";

const reviewSource = readFileSync(
  new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url),
  "utf8",
);

function answered(text: string) {
  return { status: "ANSWERED" as const, text };
}

function unknown(text = "") {
  return { status: "UNKNOWN" as const, text };
}

function filledDraft(overrides: Record<string, { status: string; text: string }> = {}) {
  return {
    STRONGEST_SUPPORTING_EVIDENCE: answered("渠道与报表支持当前等待"),
    STRONGEST_OPPOSING_EVIDENCE: answered("估值不便宜"),
    PRE_MORTEM: unknown("还没有足够的失效路径样本"),
    INVALIDATION_FACTS: answered("连续两个季度毛利率下修则失效"),
    ...overrides,
  };
}

test("empty ANSWERED is not ready; UNKNOWN may stay empty", () => {
  assert.equal(challengeDimensionsReady(undefined), false);
  assert.equal(challengeDimensionsReady(null), false);
  assert.equal(challengeDimensionsReady({}), false);

  const emptyAnswered = {
    STRONGEST_SUPPORTING_EVIDENCE: answered(""),
    STRONGEST_OPPOSING_EVIDENCE: answered("  "),
    PRE_MORTEM: answered(""),
    INVALIDATION_FACTS: answered(""),
  };
  assert.equal(challengeDimensionsReady(emptyAnswered), false);
  assert.equal(
    challengeDimensionsReady({
      ...emptyAnswered,
      STRONGEST_SUPPORTING_EVIDENCE: answered("渠道支持"),
    }),
    false,
  );

  const allUnknownEmpty = Object.fromEntries(
    DECISION_CHALLENGE_DIMENSIONS.map((name) => [name, unknown("")]),
  );
  assert.equal(challengeDimensionsReady(allUnknownEmpty), true);
  assert.equal(challengeDimensionsReady(filledDraft()), true);
  assert.equal(
    challengeDimensionsReady(filledDraft({
      PRE_MORTEM: unknown(""),
    })),
    true,
  );
});

test("finalize 422 is ABSENT, not Challenge ERROR", () => {
  assert.equal(challengeFinalizeFailureReadState({ status: 422 }), "ABSENT");
  assert.notEqual(challengeFinalizeFailureReadState({ status: 422 }), "ERROR");
  assert.equal(challengeFinalizeFailureReadState({ status: 500 }), "ERROR");
  assert.equal(challengeFinalizeFailureReadState({ status: 409 }), "ERROR");
  assert.equal(challengeFinalizeFailureReadState(new Error("network")), "ERROR");
  assert.match(CHALLENGE_DIMENSIONS_INPUT_MESSAGE, /未写入/);
  assert.doesNotMatch(CHALLENGE_DIMENSIONS_INPUT_MESSAGE, /读取失败/);
});

test("DecisionProposalReview ships the gate and 422 ABSENT contract", () => {
  assert.match(reviewSource, /challengeDimensionsReady\(challengeDraft\)/);
  assert.match(reviewSource, /!challengeDraftReady/);
  assert.match(reviewSource, /challengeFinalizeFailureReadState\(err\)/);
  assert.match(reviewSource, /CHALLENGE_DIMENSIONS_INPUT_MESSAGE/);
  assert.match(reviewSource, /status: "ANSWERED", text: ""/);
  assert.doesNotMatch(reviewSource, /status: "UNKNOWN", text: ""/);
  assert.match(
    reviewSource,
    /disabled=\{!challengeConfirmed \|\| !challengeDraftReady \|\| busy !== null \|\| !draft \|\| challengeReadState !== "ABSENT"\}/,
  );
});
