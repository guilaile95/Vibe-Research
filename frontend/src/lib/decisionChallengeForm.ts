// Formal Decision Challenge 输入闸门（前端）。
// ANSWERED 仅在 trim 后非空时有效；UNKNOWN 允许空文本。
// Finalize HTTP 422 是输入校验失败，不是 Challenge 读取失败。

import { DECISION_CHALLENGE_DIMENSIONS } from "./api.ts";

export const CHALLENGE_DIMENSIONS_INPUT_MESSAGE =
  "决策挑战输入无效，挑战记录未写入。已回答的问题必须填写非空内容。";

export function challengeDimensionsReady(draft: unknown): boolean {
  if (!draft || typeof draft !== "object") return false;
  const record = draft as Record<string, unknown>;
  for (const name of DECISION_CHALLENGE_DIMENSIONS) {
    const row = record[name];
    if (!row || typeof row !== "object" || Array.isArray(row)) return false;
    const status = (row as { status?: unknown }).status;
    const rawText = (row as { text?: unknown }).text;
    const text = typeof rawText === "string" ? rawText : "";
    if (status === "ANSWERED") {
      if (!text.trim()) return false;
      continue;
    }
    if (status !== "UNKNOWN") return false;
  }
  return true;
}

/** Finalize 422 / DecisionChallengeInputError must not become Challenge ERROR. */
export function challengeFinalizeFailureReadState(error: unknown): "ABSENT" | "ERROR" {
  if (
    error
    && typeof error === "object"
    && "status" in error
    && (error as { status?: unknown }).status === 422
  ) {
    return "ABSENT";
  }
  return "ERROR";
}
