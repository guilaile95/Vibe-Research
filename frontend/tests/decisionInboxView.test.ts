import assert from "node:assert/strict";
import test from "node:test";

// P0-CS1 Decision Inbox 纯展示逻辑契约：
// - 创建 payload 只含 security_code + strategy（frozen 枚举，不提交 status/id/时间）
// - transition payload = expected_status（CAS）+ to_status（backend 校验 graph）
// - 前端只在文案层映射 frozen 枚举，绝不定义合法性

import {
  CAMPAIGN_STRATEGIES,
  CAMPAIGN_STRATEGY_LABELS,
  CAMPAIGN_STATUS_LABELS,
  TRANSITION_ACTION_LABELS,
  createCampaignPayload,
  transitionPayload,
  errorMessage,
} from "../src/lib/decisionInbox.ts";

test("CAMPAIGN_STRATEGIES is the frozen enum SHORT/SWING/MEDIUM", () => {
  assert.deepEqual([...CAMPAIGN_STRATEGIES], ["SHORT", "SWING", "MEDIUM"]);
});

test("createCampaignPayload carries only security_code + strategy", () => {
  const payload = createCampaignPayload("600519", "SWING");
  assert.deepEqual(Object.keys(payload).sort(), ["security_code", "strategy"]);
  assert.equal(payload.security_code, "600519");
  assert.equal(payload.strategy, "SWING");
  // 绝不携带 status / campaign_id / created_at
  assert.equal((payload as any).status, undefined);
  assert.equal((payload as any).campaign_id, undefined);
  assert.equal((payload as any).created_at, undefined);
});

test("transitionPayload uses current status as expected_status (CAS, no local inference)", () => {
  const payload = transitionPayload("RESEARCHING", "PRE-ENTRY");
  assert.deepEqual(payload, { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" });
});

test("all frozen statuses have honest display labels", () => {
  for (const status of [
    "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE",
    "REDUCING", "CLOSED", "REJECTED", "EXPIRED",
  ] as const) {
    assert.ok(CAMPAIGN_STATUS_LABELS[status], `missing label for ${status}`);
  }
});

test("all frozen statuses have transition action labels (display-only)", () => {
  for (const status of [
    "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE",
    "REDUCING", "CLOSED", "REJECTED", "EXPIRED",
  ] as const) {
    assert.ok(TRANSITION_ACTION_LABELS[status], `missing action label for ${status}`);
  }
});

test("errorMessage surfaces backend detail (409 conflicts are never faked as success)", () => {
  assert.equal(errorMessage(new Error("Campaign 状态冲突")), "Campaign 状态冲突");
  assert.equal(errorMessage(new Error("")), "操作失败，请重试");
  assert.equal(errorMessage("raw"), "操作失败，请重试");
});

test("strategy labels cover the frozen enum", () => {
  assert.deepEqual(
    Object.keys(CAMPAIGN_STRATEGY_LABELS).sort(),
    ["MEDIUM", "SHORT", "SWING"],
  );
});
