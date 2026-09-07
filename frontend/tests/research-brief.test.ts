import assert from "node:assert/strict";
import test from "node:test";

import type {
  CampaignCurrentThesis,
  CampaignRecord,
  CurrentThesisDelta,
  EvidenceLink,
  ResearchContinuity,
} from "../src/lib/api/types.ts";
import { buildResearchBrief } from "../src/lib/researchBrief.ts";
import type { DecisionContextHydrationResult } from "../src/lib/decisionContextHydration.ts";

const campaign: CampaignRecord = {
  campaign_id: "campaign_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  security_code: "600519",
  strategy: "SWING",
  status: "PRE-ENTRY",
  created_at: "2026-08-01T00:00:00.000Z",
};

function evidence(partial: Partial<EvidenceLink> & Pick<EvidenceLink, "evidence_id" | "stance" | "claim">): EvidenceLink {
  return {
    evidence_type: "news",
    classification: "fact",
    confidence: "high",
    source_title: "来源",
    source_url: "https://example.com/e",
    source_date: "2026-08-01",
    accessed_at: "2026-08-01T00:00:00.000Z",
    ...partial,
  };
}

function delta(
  partial: Partial<CurrentThesisDelta> & Pick<CurrentThesisDelta, "delta_id" | "delta_state">,
): CurrentThesisDelta {
  return {
    thesis_id: "thesis_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    delta_sequence: 1,
    base_revision: 3,
    reason: "渠道调研发现动销走弱",
    confirmed_at: "2026-08-25T00:00:00.000Z",
    evidence_links: [],
    ...partial,
  };
}

function readyThesis(
  links: EvidenceLink[],
  invalidation: string[] = ["渠道崩塌"],
  opts: { deltas?: CurrentThesisDelta[]; effectiveState?: string } = {},
): CampaignCurrentThesis {
  return {
    campaign_id: campaign.campaign_id,
    thesis_id: "thesis_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    binding: {
      thesis_revision_at_bind: 3,
      campaign_strategy_at_bind: "SWING",
      bound_at: "2026-08-20T00:00:00.000Z",
    },
    frozen_revision: 3,
    original_snapshot: {
      thesis: {
        id: "thesis_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        subject_type: "stock",
        subject_id: "600519",
        market: "CN",
        title: "茅台波段研究",
        summary: "需求仍在，等待更好价格。",
        status: "active",
        core_claims: ["高端需求稳定", "库存可控", "估值回到可接受区间"],
        catalysts: [],
        risks: [],
        invalidation_conditions: invalidation,
        created_at: "2026-08-01T00:00:00.000Z",
        updated_at: "2026-08-20T00:00:00.000Z",
        current_revision: 3,
        formal_state: "frozen",
        formalization_started_at: "2026-08-10T00:00:00.000Z",
        confirmed_at: "2026-08-15T00:00:00.000Z",
        frozen_at: "2026-08-20T00:00:00.000Z",
        frozen_revision: 3,
        archived_at: null,
        strategy: "SWING",
        expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
        free_notes: null,
      },
      evidence_links: links,
      formal_state: "frozen",
      formalization_started_at: "2026-08-10T00:00:00.000Z",
      confirmed_at: "2026-08-15T00:00:00.000Z",
      frozen_at: "2026-08-20T00:00:00.000Z",
      frozen_revision: 3,
      archived_at: null,
      status: "active",
      current_revision: 3,
      updated_at: "2026-08-20T00:00:00.000Z",
    },
    deltas: opts.deltas ?? [],
    // 无 delta 时 backend 返回的真实 effective_state 是 STABLE。
    effective_state: opts.effectiveState ?? "STABLE",
    ready: true,
    formal_status: "READY",
  };
}

const hydrationReady: DecisionContextHydrationResult = {
  status: "READY",
  source: "CURRENT_THESIS",
  reason: null,
  expectedHorizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
  horizonText: "10–30 个交易日",
  frozenRevision: 3,
};

const hydrationUnavailable: DecisionContextHydrationResult = {
  status: "UNAVAILABLE",
  source: "NONE",
  reason: "Current Thesis identity 不一致",
  expectedHorizon: null,
  horizonText: null,
  frozenRevision: 3,
};

function continuity(
  status: ResearchContinuity["changes"]["status"],
  items: ResearchContinuity["changes"]["items"] = [],
  overrides: Partial<ResearchContinuity> = {},
): ResearchContinuity {
  return {
    schema_version: "research_continuity.v0.1",
    status: "NORMAL",
    campaign_id: campaign.campaign_id,
    security_code: "600519",
    strategy: "SWING",
    fetched_at: "2026-08-22T00:00:00.000Z",
    baseline: {
      status: status === "NO_BASELINE" ? "NO_BASELINE" : "READY",
      authority_type: status === "NO_BASELINE" ? null : "CANDIDATE_RESEARCH_FORMAL_ORIGINAL",
    },
    changes: { status, items, observation_count: items.length },
    decision_calendar: {
      state: "NO_RECORD",
      next: null,
      latest_actual: null,
      fetched_at: "2026-08-22T00:00:00.000Z",
      source: "cninfo",
    },
    authority_refs: [],
    writes: { thesis: 0, decision: 0, campaign: 0, trade: 0 },
    ...overrides,
  };
}

function briefInput(overrides: Partial<Parameters<typeof buildResearchBrief>[0]> = {}) {
  return {
    campaignId: campaign.campaign_id,
    campaign,
    currentThesis: readyThesis([]) as CampaignCurrentThesis,
    hydration: hydrationReady,
    continuity: continuity("NO_BASELINE"),
    continuityError: null,
    contextState: "ready" as const,
    contextMessage: "",
    ...overrides,
  };
}

test("已确认快照映射标的、策略、周期与观点", () => {
  const brief = buildResearchBrief(briefInput({
    currentThesis: readyThesis([
      evidence({ evidence_id: "ev1", stance: "support", claim: "终端动销仍在", classification: "fact" }),
    ]),
  }));
  assert.equal(brief.securityCode, "600519");
  assert.equal(brief.strategyLabel, "波段");
  assert.equal(brief.horizonText, "10–30 个交易日");
  assert.equal(brief.horizonSource, "CURRENT_THESIS");
  assert.equal(brief.confirmed.status, "CONFIRMED");
  assert.equal(brief.confirmed.title, "茅台波段研究");
  assert.ok(brief.confirmed.claims.includes("高端需求稳定"));
  assert.match(brief.confirmed.note, /冻结快照 v3/);
  // 无 delta 时当前状态是 STABLE，且 ready 只代表投影可读取。
  assert.equal(brief.effectiveState.state, "STABLE");
  assert.equal(brief.effectiveState.label, "稳定");
  assert.equal(brief.effectiveState.terminal, false);
  assert.match(brief.effectiveState.note, /投影可读取/);
  assert.match(brief.updatesNote, /没有已确认变更记录/);
});

test("未确认 Thesis 不会把草稿当正式观点", () => {
  const brief = buildResearchBrief(briefInput({
    currentThesis: {
      campaign_id: campaign.campaign_id,
      thesis_id: "thesis_cccccccccccccccccccccccccccccccc",
      binding: {
        thesis_revision_at_bind: 1,
        campaign_strategy_at_bind: "SWING",
        bound_at: "2026-08-20T00:00:00.000Z",
      },
      formal_state: "confirmed",
      frozen_revision: null,
      ready: false,
      formal_status: "NOT_READY",
      reason: "NOT_FROZEN",
    },
    hydration: { status: "UNAVAILABLE", source: "NONE", reason: "NOT_FROZEN", expectedHorizon: null, horizonText: null, frozenRevision: null },
    continuity: null,
    contextState: "unavailable",
    contextMessage: "Current Thesis 尚未就绪：NOT_FROZEN",
  }));
  assert.equal(brief.confirmed.status, "UNAVAILABLE");
  assert.equal(brief.confirmed.claims.length, 0);
  assert.match(brief.confirmed.note, /未确认草稿/);
  assert.equal(brief.evidence.supporting.length, 0);
  assert.match(brief.invalidation.note, /不把任何失效条件当作已确认内容展示/);
});

test("没有反对记录不等于没有反对证据；记录失效条件不等于已触发", () => {
  const brief = buildResearchBrief(briefInput({
    currentThesis: readyThesis([
      evidence({ evidence_id: "ev1", stance: "support", claim: "终端动销仍在", classification: "fact" }),
      evidence({ evidence_id: "ev2", stance: "support", claim: "可能补库存", classification: "inference" }),
    ], ["渠道崩塌"]),
    continuity: continuity("NOT_EVALUATED"),
  }));
  assert.equal(brief.evidence.opposingRecorded, false);
  assert.match(brief.evidence.note, /不等于没有反对证据/);
  assert.deepEqual(brief.invalidation.conditions, ["渠道崩塌"]);
  assert.match(brief.invalidation.note, /不是这些条件已经触发/);
  assert.equal(brief.evidence.supporting[0].classificationKind, "fact");
  assert.equal(brief.evidence.supporting[1].classificationKind, "inference");
});

test("NO_BASELINE 与读取失败都不能写成没有变化", () => {
  const noBaseline = buildResearchBrief(briefInput({
    currentThesis: readyThesis([]),
    continuity: continuity("NO_BASELINE"),
  }));
  assert.match(noBaseline.changes.note, /不能声称没有变化/);
  const failed = buildResearchBrief(briefInput({
    currentThesis: readyThesis([]),
    continuity: null,
    continuityError: "UNAVAILABLE",
  }));
  assert.equal(failed.changes.status, "UNAVAILABLE");
  assert.match(failed.changes.note, /不能声称没有变化/);
});

test("已证伪 delta 改变当前状态，其反对依据可见且不改变最初冻结原文", () => {
  const disproven = delta({
    delta_id: "delta_d1",
    delta_state: "DISPROVEN",
    delta_sequence: 2,
    reason: "7 月渠道动销数据证伪核心假设",
    confirmed_at: "2026-08-25T00:00:00.000Z",
    evidence_links: [
      evidence({ evidence_id: "evd1", stance: "oppose", claim: "7 月动销同比下滑", classification: "fact", source_title: "渠道调研周报" }),
    ],
  });
  const brief = buildResearchBrief(briefInput({
    currentThesis: readyThesis(
      [evidence({ evidence_id: "ev1", stance: "support", claim: "终端动销仍在", classification: "fact" })],
      ["渠道崩塌"],
      { deltas: [disproven], effectiveState: "DISPROVEN" },
    ),
  }));
  assert.equal(brief.confirmed.status, "CONFIRMED");
  assert.equal(brief.effectiveState.state, "DISPROVEN");
  assert.equal(brief.effectiveState.terminal, true);
  assert.equal(brief.effectiveState.label, "已证伪");
  assert.match(brief.effectiveState.note, /不再成立/);
  assert.equal(brief.confirmedUpdates.length, 1);
  assert.equal(brief.confirmedUpdates[0].stateLabel, "已证伪");
  assert.equal(brief.confirmedUpdates[0].reason, "7 月渠道动销数据证伪核心假设");
  assert.equal(brief.confirmedUpdates[0].confirmedAt, "2026-08-25T00:00:00.000Z");
  assert.equal(brief.confirmedUpdates[0].baseRevision, 3);
  assert.equal(brief.confirmedUpdates[0].evidence.length, 1);
  assert.equal(brief.confirmedUpdates[0].evidence[0].claim, "7 月动销同比下滑");
  assert.equal(brief.confirmedUpdates[0].evidence[0].classificationKind, "fact");
  assert.equal(brief.confirmedUpdates[0].evidence[0].sourceTitle, "渠道调研周报");
  // 反对依据来自已确认变更：opposingRecorded 必须为 true，而原始快照仍无反对记录。
  assert.equal(brief.evidence.opposing.length, 0);
  assert.equal(brief.evidence.opposingRecorded, true);
  assert.match(brief.updatesNote, /最新一条：已证伪/);
  // 最初冻结原文保持原样，不与 delta 合成。
  assert.equal(brief.confirmed.title, "茅台波段研究");
  assert.equal(brief.freshness.frozenAt, "2026-08-20T00:00:00.000Z");
  assert.equal(brief.freshness.gaps.includes("确认版本未记录反对证据"), false);
});

test("身份或版本校验失败时，投影可读也不输出 CONFIRMED，且不展示其证据与失效条件", () => {
  const brief = buildResearchBrief(briefInput({
    currentThesis: readyThesis(
      [
        evidence({ evidence_id: "ev1", stance: "support", claim: "终端动销仍在", classification: "fact" }),
        evidence({ evidence_id: "ev2", stance: "oppose", claim: "竞品放量", classification: "fact" }),
      ],
      ["渠道崩塌"],
      { effectiveState: "STABLE" },
    ),
    hydration: hydrationUnavailable,
    continuity: continuity("NORMAL"),
    contextState: "unavailable",
    contextMessage: "Current Thesis identity 不一致",
  }));
  assert.equal(brief.confirmed.status, "UNAVAILABLE");
  assert.equal(brief.confirmed.title, null);
  assert.equal(brief.confirmed.claims.length, 0);
  assert.match(brief.confirmed.note, /Current Thesis identity 不一致/);
  assert.equal(brief.evidence.supporting.length, 0);
  assert.equal(brief.evidence.opposing.length, 0);
  assert.equal(brief.evidence.opposingRecorded, false);
  assert.equal(brief.invalidation.conditions.length, 0);
  assert.equal(brief.effectiveState.state, null);
  assert.equal(brief.confirmedUpdates.length, 0);
  assert.match(brief.updatesNote, /校验未通过/);
});

test("变化区保留中性标签与 classification，CHANGED 显示前后值而不只是字段名", () => {
  const cont = continuity("NORMAL", [
    {
      change_type: "ADDED",
      record_key: "k-added",
      after: {
        record_key: "k-added",
        claim_identity: "动销走弱",
        source: "渠道调研",
        field_states: { classification: "VALUE", confidence: "VALUE" },
        values: { claim: "动销走弱", classification: "inference", confidence: "medium", evidence_type: "field_report", source_title: "渠道调研" },
      },
    },
    {
      change_type: "CHANGED",
      record_key: "k-changed",
      changed_fields: ["confidence"],
      before: {
        record_key: "k-changed",
        claim_identity: "高端需求稳定",
        source: "券商纪要",
        field_states: { confidence: "VALUE" },
        values: { claim: "高端需求稳定", confidence: "high" },
      },
      after: {
        record_key: "k-changed",
        claim_identity: "高端需求稳定",
        source: "券商纪要",
        field_states: { confidence: "VALUE" },
        values: { claim: "高端需求稳定", confidence: "low" },
      },
    },
  ]);
  const brief = buildResearchBrief(briefInput({ currentThesis: readyThesis([]), continuity: cont }));
  assert.equal(brief.changes.status, "NORMAL");
  const added = brief.changes.items[0];
  assert.equal(added.label, "新增证据");
  assert.equal(added.classificationLabel, "推断");
  assert.match(added.detail ?? "", /分类：推断/);
  const changed = brief.changes.items[1];
  assert.equal(changed.label, "证据变化");
  assert.equal(changed.classificationLabel, null);
  assert.match(changed.detail ?? "", /high → low/);
  assert.match(changed.detail ?? "", /置信度/);
  assert.equal(brief.changes.baselineText, "基线 Candidate Research Formal Original（口径：Current Thesis 的不可变 Evidence 快照）");
  assert.equal(brief.changes.fetchedAt, "2026-08-22T00:00:00.000Z");
  assert.equal(brief.changes.observationCount, 2);
});

test("研究连续性与当前 Campaign 不一致时不混入其内容", () => {
  const brief = buildResearchBrief(briefInput({
    currentThesis: readyThesis([]),
    continuity: continuity("NORMAL", [], {
      campaign_id: "campaign_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    }),
  }));
  assert.equal(brief.changes.status, "UNAVAILABLE");
  assert.match(brief.changes.note, /与当前 Campaign 不一致/);
  assert.equal(brief.changes.items.length, 0);
  assert.ok(brief.freshness.gaps.includes("研究连续性与当前 Campaign 不一致"));
  assert.match(brief.freshness.calendarText, /未读取/);
});

test("来源冲突保留双方立场与来源时间，立场交换产生可辨识差异", () => {
  const conflict = (stanceA: string, stanceB: string) =>
    buildResearchBrief(briefInput({
      currentThesis: readyThesis([]),
      continuity: continuity("NORMAL", [
        {
          change_type: "SOURCE_CONFLICT",
          record_key: "k-conflict",
          records: [
            {
              record_key: "src-a",
              claim_identity: "竞品正在放量",
              source: "https://example.com/a",
              field_states: {},
              values: {
                claim: "竞品正在放量", classification: "fact", confidence: "high",
                stance: stanceA, source_title: "来源A", source_url: "https://example.com/a",
                source_date: "2026-08-01", accessed_at: "2026-08-02T00:00:00.000Z",
              },
            },
            {
              record_key: "src-b",
              claim_identity: "竞品正在放量",
              source: "https://example.com/b",
              field_states: {},
              values: {
                claim: "竞品正在放量", classification: "inference", confidence: "medium",
                stance: stanceB, source_title: "来源B", source_url: "https://example.com/b",
                source_date: "2026-08-03", accessed_at: "2026-08-04T00:00:00.000Z",
              },
            },
          ],
        },
      ]),
    }));
  const ab = conflict("support", "oppose");
  const ba = conflict("oppose", "support");
  const records = ab.changes.items[0].conflictRecords;
  assert.ok(records, "SOURCE_CONFLICT item must carry structured conflict records");
  assert.equal(records.length, 2);
  assert.equal(records[0].stanceLabel, "支持");
  assert.equal(records[0].sourceTitle, "来源A");
  assert.equal(records[0].sourceUrl, "https://example.com/a");
  assert.equal(records[0].sourceDate, "2026-08-01");
  assert.equal(records[0].recordedAt, "2026-08-02T00:00:00.000Z");
  assert.equal(records[0].confidence, "high");
  assert.equal(records[1].stanceLabel, "反对");
  assert.equal(records[1].classificationLabel, "推断");
  // 立场交换后输出必须可辨识，不允许只有相同来源名的两份输出。
  assert.notDeepEqual(ab.changes.items[0].conflictRecords, ba.changes.items[0].conflictRecords);
  assert.notEqual(ab.changes.items[0].detail, ba.changes.items[0].detail);
  assert.match(ab.changes.items[0].detail ?? "", /来源A：立场 支持 \/ 来源B：立场 反对/);
  // 不推断赢家：摘要不出现任何"正确/更可信"判定。
  assert.equal((ab.changes.items[0].detail ?? "").includes("正确"), false);
});

test("ADDED 与 CHANGED 保留来源时间，不把读取时间当发布日期", () => {
  const brief = buildResearchBrief(briefInput({
    currentThesis: readyThesis([]),
    continuity: continuity("NORMAL", [
      {
        change_type: "ADDED",
        record_key: "k-added",
        after: {
          record_key: "k-added",
          claim_identity: "动销走弱",
          source: "渠道调研",
          field_states: {},
          values: {
            claim: "动销走弱", classification: "inference", confidence: "medium",
            evidence_type: "field_report", source_date: "2026-08-20",
            accessed_at: "2026-08-22T00:00:00.000Z",
          },
        },
      },
      {
        change_type: "CHANGED",
        record_key: "k-changed",
        changed_fields: ["confidence"],
        before: {
          record_key: "k-changed", claim_identity: "高端需求稳定", source: "券商纪要",
          field_states: {}, values: { claim: "高端需求稳定", confidence: "high", source_date: "2026-08-10", accessed_at: "2026-08-11T00:00:00.000Z" },
        },
        after: {
          record_key: "k-changed", claim_identity: "高端需求稳定", source: "券商纪要",
          field_states: {}, values: { claim: "高端需求稳定", confidence: "low", source_date: "2026-08-20", accessed_at: "2026-08-22T00:00:00.000Z" },
        },
      },
    ]),
  }));
  const added = brief.changes.items[0];
  assert.match(added.detail ?? "", /来源日期：2026-08-20/);
  assert.match(added.detail ?? "", /记录时间：2026-08-22T00:00:00.000Z/);
  const changed = brief.changes.items[1];
  assert.match(changed.detail ?? "", /置信度：high → low/);
  assert.match(changed.detail ?? "", /来源日期：2026-08-20/);
});
