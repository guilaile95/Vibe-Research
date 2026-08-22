import assert from "node:assert/strict";
import test from "node:test";

// P0-CS1(R1) Decision Inbox 纯状态/selector 契约：
// - 创建 payload 只含 security_code + strategy（frozen 枚举，不提交 status/id/时间）
// - transition payload = expected_status（CAS）+ to_status（backend 校验 graph）
// - 「正在建立的 Campaign」= frontend read-model 分类（DRAFT/RESEARCHING/PRE-ENTRY），
//   绝不宣称 current membership；current 只由 backend inbox campaign_items 决定
// - ACTIVE sibling 不隐藏同 Security 的 DRAFT sibling（universe 取并集）

import {
  CAMPAIGN_STRATEGIES,
  CAMPAIGN_STRATEGY_LABELS,
  CAMPAIGN_STATUS_LABELS,
  TRANSITION_ACTION_LABELS,
  SETUP_CAMPAIGN_STATUSES,
  TERMINAL_CAMPAIGN_STATUSES,
  isSetupCampaignStatus,
  isTerminalCampaignStatus,
  isDestructiveTransition,
  collectHoldingUniverseSecurityCodes,
  selectSetupCampaigns,
  renderableTransitionTargets,
  createCampaignPayload,
  transitionPayload,
  errorMessage,
  reasonCodeLabel,
  visibleStateLabel,
  presentReasonCodes,
  formatCampaignIdShort,
  formalDecisionNextSteps,
} from "../src/lib/decisionInbox.ts";
import type {
  CampaignRecord,
  DecisionInboxSnapshot,
} from "../src/lib/api/types.ts";

function campaign(
  overrides: Partial<CampaignRecord> & { campaign_id: string },
): CampaignRecord {
  return {
    security_code: "600519",
    strategy: "SWING",
    status: "DRAFT",
    created_at: "2026-08-14T00:00:00.000000Z",
    ...overrides,
  };
}

function snapshot(overrides: {
  holding_setup_items?: DecisionInboxSnapshot["holding_setup_items"];
  campaign_items?: DecisionInboxSnapshot["campaign_items"];
}): DecisionInboxSnapshot {
  return {
    schema_version: "decision_inbox_runtime.v0.1",
    as_of: "2026-08-14T04:00:00.000000Z",
    evaluation_status: "EVALUATED",
    canonical: true,
    reason_codes: [],
    holding_setup_items: [],
    campaign_items: [],
    total_holdings: 0,
    total_campaign_items: 0,
    ...overrides,
  };
}

function holdingItem(code: string): DecisionInboxSnapshot["holding_setup_items"][number] {
  return {
    item_kind: "UNASSIGNED_HOLDING",
    security_code: code,
    security_name: code,
    holding: {},
    reason_codes: ["UNASSIGNED_HOLDING"],
    next_workflow_action: "CREATE_CAMPAIGN",
    as_of: "2026-08-14T04:00:00.000000Z",
  };
}

function campaignItem(
  code: string,
  campaignId: string,
): DecisionInboxSnapshot["campaign_items"][number] {
  return {
    schema_version: "decision_inbox_projection.v0.1",
    visible_state: "SETUP_REQUIRED",
    reason_codes: ["THESIS_MISSING"],
    security_code: code,
    strategy: "SWING",
    campaign_id: campaignId,
    campaign_status: "ACTIVE",
    as_of: "2026-08-14T04:00:00.000000Z",
  };
}

// ---- frozen enum / label coverage ----

test("CAMPAIGN_STRATEGIES is the frozen enum SHORT/SWING/MEDIUM", () => {
  assert.deepEqual([...CAMPAIGN_STRATEGIES], ["SHORT", "SWING", "MEDIUM"]);
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

test("strategy labels cover the frozen enum", () => {
  assert.deepEqual(
    Object.keys(CAMPAIGN_STRATEGY_LABELS).sort(),
    ["MEDIUM", "SHORT", "SWING"],
  );
});

// ---- payload contracts ----

test("createCampaignPayload carries only security_code + strategy", () => {
  const payload = createCampaignPayload("600519", "SWING");
  assert.deepEqual(Object.keys(payload).sort(), ["security_code", "strategy"]);
  assert.equal((payload as any).status, undefined);
  assert.equal((payload as any).campaign_id, undefined);
  assert.equal((payload as any).created_at, undefined);
});

test("transitionPayload uses current status as expected_status (CAS, no local inference)", () => {
  assert.deepEqual(
    transitionPayload("RESEARCHING", "PRE-ENTRY"),
    { expected_status: "RESEARCHING", to_status: "PRE-ENTRY" },
  );
});

test("errorMessage surfaces backend detail (409 conflicts are never faked as success)", () => {
  assert.equal(errorMessage(new Error("Campaign 状态冲突")), "Campaign 状态冲突");
  assert.equal(errorMessage(new Error("")), "操作失败，请重试");
  assert.equal(errorMessage("raw"), "操作失败，请重试");
});

// ---- R1 setup/terminal classification (§4/§9) ----

test("SETUP_CAMPAIGN_STATUSES is exactly DRAFT/RESEARCHING/PRE-ENTRY (frontend read-model only)", () => {
  assert.deepEqual([...SETUP_CAMPAIGN_STATUSES], ["DRAFT", "RESEARCHING", "PRE-ENTRY"]);
});

test("TERMINAL_CAMPAIGN_STATUSES is exactly CLOSED/REJECTED/EXPIRED", () => {
  assert.deepEqual([...TERMINAL_CAMPAIGN_STATUSES], ["CLOSED", "REJECTED", "EXPIRED"]);
});

test("isSetupCampaignStatus: ACTIVE/REDUCING/terminal are NOT setup", () => {
  assert.equal(isSetupCampaignStatus("DRAFT"), true);
  assert.equal(isSetupCampaignStatus("RESEARCHING"), true);
  assert.equal(isSetupCampaignStatus("PRE-ENTRY"), true);
  assert.equal(isSetupCampaignStatus("ACTIVE"), false);
  assert.equal(isSetupCampaignStatus("REDUCING"), false);
  assert.equal(isSetupCampaignStatus("CLOSED"), false);
  assert.equal(isSetupCampaignStatus("REJECTED"), false);
  assert.equal(isSetupCampaignStatus("EXPIRED"), false);
});

test("isTerminalCampaignStatus: only CLOSED/REJECTED/EXPIRED", () => {
  assert.equal(isTerminalCampaignStatus("CLOSED"), true);
  assert.equal(isTerminalCampaignStatus("REJECTED"), true);
  assert.equal(isTerminalCampaignStatus("EXPIRED"), true);
  assert.equal(isTerminalCampaignStatus("DRAFT"), false);
  assert.equal(isTerminalCampaignStatus("ACTIVE"), false);
});

// ---- universe collection (§6) ----

test("universe = holding_setup_items ∪ campaign_items (ACTIVE sibling never hides DRAFT sibling)", () => {
  const snap = snapshot({
    holding_setup_items: [holdingItem("000001")],
    campaign_items: [campaignItem("600519", "campaign_" + "a".repeat(32))],
  });
  assert.deepEqual(
    collectHoldingUniverseSecurityCodes(snap),
    ["000001", "600519"],
  );
});

test("universe is empty when snapshot has neither kind of item", () => {
  assert.deepEqual(collectHoldingUniverseSecurityCodes(snapshot({})), []);
});

// ---- §11 A–H setup selection matrix ----

test("A: holding setup + no Campaign → universe covers holding, setup list empty (CREATE_CAMPAIGN still shown by holding item)", () => {
  const snap = snapshot({ holding_setup_items: [holdingItem("600519")] });
  const universe = collectHoldingUniverseSecurityCodes(snap);
  assert.deepEqual(universe, ["600519"]);
  assert.deepEqual(selectSetupCampaigns([], universe), []);
  assert.equal(snap.holding_setup_items[0].next_workflow_action, "CREATE_CAMPAIGN");
});

test("B: create returns DRAFT → DRAFT appears in setup campaigns", () => {
  const universe = ["600519"];
  const draft = campaign({ campaign_id: "campaign_" + "a".repeat(32) });
  const selected = selectSetupCampaigns([draft], universe);
  assert.equal(selected.length, 1);
  assert.equal(selected[0].campaign_id, draft.campaign_id);
});

test("C: DRAFT remains after refresh (pure selector is idempotent over same backend data)", () => {
  const universe = ["600519"];
  const rows = [campaign({ campaign_id: "campaign_" + "a".repeat(32) })];
  const first = selectSetupCampaigns(rows, universe);
  const second = selectSetupCampaigns(rows, universe);
  assert.deepEqual(first, second);
  assert.equal(second[0].status, "DRAFT");
});

test("D: DRAFT → RESEARCHING remains a setup campaign", () => {
  const rows = [campaign({ campaign_id: "campaign_" + "a".repeat(32), status: "RESEARCHING" })];
  const selected = selectSetupCampaigns(rows, ["600519"]);
  assert.equal(selected.length, 1);
  assert.equal(selected[0].status, "RESEARCHING");
});

test("E: RESEARCHING → PRE-ENTRY remains a setup campaign", () => {
  const rows = [campaign({ campaign_id: "campaign_" + "a".repeat(32), status: "PRE-ENTRY" })];
  const selected = selectSetupCampaigns(rows, ["600519"]);
  assert.equal(selected.length, 1);
  assert.equal(selected[0].status, "PRE-ENTRY");
});

test("F: PRE-ENTRY → ACTIVE is removed from setup campaigns (represented by inbox campaign item instead)", () => {
  const rows = [campaign({ campaign_id: "campaign_" + "a".repeat(32), status: "ACTIVE" })];
  assert.equal(selectSetupCampaigns(rows, ["600519"]).length, 0);
  // current 由 backend inbox campaign_items 呈现（契约：campaign_items 非空）
  const snap = snapshot({ campaign_items: [campaignItem("600519", "campaign_" + "a".repeat(32))] });
  assert.equal(snap.campaign_items.length, 1);
  assert.equal(snap.campaign_items[0].campaign_status, "ACTIVE");
});

test("G: 600519 SWING ACTIVE + 600519 MEDIUM DRAFT → DRAFT sibling remains reachable", () => {
  const activeId = "campaign_" + "a".repeat(32);
  const draftId = "campaign_" + "b".repeat(32);
  const snap = snapshot({
    holding_setup_items: [],
    campaign_items: [campaignItem("600519", activeId)],
  });
  const universe = collectHoldingUniverseSecurityCodes(snap);
  assert.deepEqual(universe, ["600519"]); // 600519 不在 holding_setup_items，仍进 universe
  const rows = [
    campaign({ campaign_id: activeId, strategy: "SWING", status: "ACTIVE" }),
    campaign({ campaign_id: draftId, strategy: "MEDIUM", status: "DRAFT" }),
  ];
  const setup = selectSetupCampaigns(rows, universe);
  assert.equal(setup.length, 1);
  assert.equal(setup[0].campaign_id, draftId);
  assert.equal(setup[0].strategy, "MEDIUM");
});

test("H: terminal campaigns are never shown as setup items", () => {
  const universe = ["600519"];
  for (const status of ["CLOSED", "REJECTED", "EXPIRED"] as const) {
    const rows = [campaign({ campaign_id: "campaign_" + status[0].repeat(32), status })];
    assert.equal(selectSetupCampaigns(rows, universe).length, 0, status);
  }
});

// ---- §11 J: next-actions failure → no fake buttons ----

test("J: next-actions missing/null → no transition targets rendered (no guessed graph)", () => {
  assert.deepEqual(renderableTransitionTargets(null), []);
  const nextActions = {
    campaign_id: "campaign_" + "a".repeat(32),
    security_code: "600519",
    strategy: "DRAFT" as const,
    status: "DRAFT" as const,
    next_actions: [],
  };
  assert.deepEqual(renderableTransitionTargets(nextActions), []);
});

test("J: next-actions present → exactly backend-declared targets (no extra edges)", () => {
  const nextActions = {
    campaign_id: "campaign_" + "a".repeat(32),
    security_code: "600519",
    strategy: "SWING" as const,
    status: "DRAFT" as const,
    next_actions: ["RESEARCHING", "REJECTED", "EXPIRED"] as const,
  };
  assert.deepEqual(
    renderableTransitionTargets(nextActions),
    ["RESEARCHING", "REJECTED", "EXPIRED"],
  );
});

// ---- deterministic ordering ----

test("ACTIVE display label does not say 已激活 / 买入 / 持有", () => {
  assert.equal(CAMPAIGN_STATUS_LABELS.ACTIVE, "进行中");
  assert.doesNotMatch(CAMPAIGN_STATUS_LABELS.ACTIVE, /买入|持有|已批准/);
});

test("reason codes stay semantic; labels are presentation-only", () => {
  assert.equal(reasonCodeLabel("THESIS_MISSING"), "尚未绑定正式投资逻辑");
  assert.equal(reasonCodeLabel("UNKNOWN_CODE_XYZ"), "UNKNOWN_CODE_XYZ");
  assert.equal(visibleStateLabel("SETUP_REQUIRED"), "设置尚未完成");
  assert.equal(visibleStateLabel("CUSTOM_STATE"), "CUSTOM_STATE");
});

test("presentReasonCodes keeps raw codes in details and surfaces readable primary", () => {
  const presented = presentReasonCodes([
    "THESIS_MISSING",
    "CRITICAL_DATA_NOT_EVALUATED",
    "COVERAGE_INCOMPLETE",
  ]);
  assert.deepEqual(presented.primary, [
    "尚未绑定正式投资逻辑",
    "关键数据尚未评估",
  ]);
  assert.equal(presented.extraCount, 1);
  assert.deepEqual(
    presented.details.map((item) => item.code),
    ["THESIS_MISSING", "CRITICAL_DATA_NOT_EVALUATED", "COVERAGE_INCOMPLETE"],
  );
});

test("formatCampaignIdShort keeps identity recognizable without the full UUID", () => {
  const id = "campaign_" + "a".repeat(32);
  assert.equal(formatCampaignIdShort(id), "campaign_aaaaaaaa…");
  assert.equal(formatCampaignIdShort("short"), "short");
});

test("destructive transition styling uses terminal classification, not a copied graph", () => {
  assert.equal(isDestructiveTransition("REJECTED"), true);
  assert.equal(isDestructiveTransition("EXPIRED"), true);
  assert.equal(isDestructiveTransition("CLOSED"), true);
  assert.equal(isDestructiveTransition("RESEARCHING"), false);
  assert.equal(isDestructiveTransition("ACTIVE"), false);
});

test("EVALUATED exposes review first and a separate explicit new-decision entry", () => {
  const steps = formalDecisionNextSteps("EVALUATED", "campaign_abc/unsafe");
  assert.deepEqual(steps, [
    {
      kind: "review",
      label: "打开决策复盘",
      href: "/decision-performance",
    },
    {
      kind: "new-decision",
      label: "形成新的 Formal Decision",
      href: "/campaigns/campaign_abc%2Funsafe/decision-proposal",
    },
  ]);
});

test("NOT_EVALUATED keeps only the existing proposal workflow", () => {
  for (const evaluation of ["NOT_EVALUATED", "UNKNOWN", "ERROR"]) {
    assert.deepEqual(formalDecisionNextSteps(evaluation, "campaign_demo"), [
      {
        kind: "proposal",
        label: "打开 Formal Decision Review",
        href: "/campaigns/campaign_demo/decision-proposal",
      },
    ]);
  }
  assert.deepEqual(formalDecisionNextSteps(null, "campaign_demo"), []);
  assert.deepEqual(formalDecisionNextSteps(undefined, "campaign_demo"), []);
});


test("setup campaigns sort deterministically by security_code → created_at → campaign_id", () => {
  const universe = ["000001", "600519"];
  const rows = [
    campaign({ campaign_id: "campaign_" + "b".repeat(32), security_code: "600519", created_at: "2026-08-10T00:00:00.000000Z" }),
    campaign({ campaign_id: "campaign_" + "a".repeat(32), security_code: "000001", created_at: "2026-08-12T00:00:00.000000Z" }),
    campaign({ campaign_id: "campaign_" + "c".repeat(32), security_code: "600519", created_at: "2026-08-09T00:00:00.000000Z" }),
  ];
  const ids = selectSetupCampaigns(rows, universe).map((c) => c.campaign_id);
  assert.deepEqual(ids, [
    "campaign_" + "a".repeat(32), // 000001
    "campaign_" + "c".repeat(32), // 600519, earlier created_at
    "campaign_" + "b".repeat(32),
  ]);
});
