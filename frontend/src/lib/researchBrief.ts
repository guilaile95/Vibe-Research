/** 决策复核页「研究摘要 v0.1」只读映射。无 I/O，不写入 Formal 记录。 */
import type {
  CampaignCurrentThesis,
  CampaignRecord,
  EvidenceLink,
  ResearchContinuity,
  ThesisAggregate,
} from "./api/types.ts";
import { CAMPAIGN_STRATEGY_LABELS } from "./decisionInbox.ts";
import type { DecisionContextHydrationResult } from "./decisionContextHydration.ts";

export type ResearchBriefContextState = "loading" | "ready" | "unavailable";

export type ResearchBriefStateKind = "positive" | "caution" | "terminal" | "unknown";

export interface ResearchBriefEvidenceItem {
  claim: string;
  stance: EvidenceLink["stance"];
  classification: string;
  classificationKind: "fact" | "inference" | "unknown" | "other";
  confidence: string;
  sourceTitle: string;
  sourceUrl: string | null;
  sourceDate: string | null;
  evidenceId: string;
}

export interface ResearchBriefEffectiveState {
  state: string | null;
  label: string;
  kind: ResearchBriefStateKind;
  terminal: boolean;
  note: string;
}

export interface ResearchBriefConfirmedUpdate {
  deltaId: string;
  sequence: number;
  stateLabel: string;
  stateKind: ResearchBriefStateKind;
  reason: string;
  confirmedAt: string | null;
  baseRevision: number | null;
  evidence: ResearchBriefEvidenceItem[];
}

export interface ResearchBriefConflictRecord {
  source: string;
  claim: string;
  stance: string | null;
  stanceLabel: string | null;
  classificationLabel: string | null;
  confidence: string | null;
  sourceTitle: string | null;
  sourceUrl: string | null;
  sourceDate: string | null;
  recordedAt: string | null;
}

export interface ResearchBriefChangeItem {
  kind: "ADDED" | "CHANGED" | "SOURCE_CONFLICT";
  label: string;
  recordKey: string;
  claim: string;
  source: string;
  classificationLabel: string | null;
  detail: string | null;
  conflictRecords?: ResearchBriefConflictRecord[];
}

export interface ResearchBriefModel {
  campaignId: string;
  securityCode: string;
  strategyCode: string;
  strategyLabel: string;
  horizonText: string;
  thesisVersionText: string;
  horizonSource: "CURRENT_THESIS" | "MANUAL_FALLBACK" | "LOADING";
  contextState: ResearchBriefContextState;
  effectiveState: ResearchBriefEffectiveState;
  confirmed: {
    status: "CONFIRMED" | "NOT_CONFIRMED" | "UNAVAILABLE";
    title: string | null;
    summary: string | null;
    claims: string[];
    note: string;
  };
  confirmedUpdates: ResearchBriefConfirmedUpdate[];
  updatesNote: string;
  changes: {
    status: string;
    note: string;
    items: ResearchBriefChangeItem[];
    baselineText: string | null;
    fetchedAt: string | null;
    observationCount: number | null;
  };
  evidence: {
    supporting: ResearchBriefEvidenceItem[];
    opposing: ResearchBriefEvidenceItem[];
    opposingRecorded: boolean;
    note: string;
  };
  invalidation: {
    conditions: string[];
    note: string;
  };
  freshness: {
    frozenAt: string | null;
    calendarText: string;
    gaps: string[];
  };
}

const CHANGE_LABEL = {
  ADDED: "新增证据",
  CHANGED: "证据变化",
  SOURCE_CONFLICT: "来源冲突",
} as const;

const STATE_META: Record<string, { label: string; kind: ResearchBriefStateKind }> = {
  STABLE: { label: "稳定", kind: "positive" },
  STRENGTHENED: { label: "增强", kind: "positive" },
  WEAKENED: { label: "削弱", kind: "caution" },
  DISPROVEN: { label: "已证伪", kind: "terminal" },
  INVALIDATED: { label: "已失效", kind: "terminal" },
  UNKNOWN: { label: "未知", kind: "unknown" },
};

const TERMINAL_STATES = new Set(["DISPROVEN", "INVALIDATED"]);

const CLASSIFICATION_LABEL: Record<string, string> = {
  fact: "事实",
  inference: "推断",
  unknown: "未知",
};

const FIELD_LABELS: Record<string, string> = {
  claim: "陈述",
  evidence_type: "类型",
  classification: "分类",
  confidence: "置信度",
  stance: "立场",
  source_title: "来源标题",
  source_url: "来源 URL",
  source_date: "来源日期",
  accessed_at: "记录时间",
};

function shown(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "未知" : value;
}

function classificationLabel(value: unknown): string | null {
  if (typeof value !== "string" || value === "") return null;
  return CLASSIFICATION_LABEL[value] || value;
}

function classificationKind(value: string): ResearchBriefEvidenceItem["classificationKind"] {
  if (value === "fact" || value === "inference" || value === "unknown") return value;
  return "other";
}

function mapEvidence(link: EvidenceLink): ResearchBriefEvidenceItem {
  return {
    claim: link.claim,
    stance: link.stance,
    classification: CLASSIFICATION_LABEL[link.classification] || link.classification,
    classificationKind: classificationKind(link.classification),
    confidence: link.confidence,
    sourceTitle: link.source_title,
    sourceUrl: link.source_url,
    sourceDate: link.source_date,
    evidenceId: link.evidence_id,
  };
}

function isEvidenceLinkLike(value: unknown): value is EvidenceLink {
  return Boolean(
    value
    && typeof value === "object"
    && typeof (value as EvidenceLink).evidence_id === "string"
    && typeof (value as EvidenceLink).claim === "string",
  );
}

/** 上下文校验通过（contextState=ready）才允许把冻结快照当作已确认内容展示。 */
function confirmedSnapshot(
  current: CampaignCurrentThesis | null,
  contextState: ResearchBriefContextState,
): ThesisAggregate | null {
  if (contextState !== "ready") return null;
  if (!current?.ready) return null;
  const snapshot = current.original_snapshot;
  if (!snapshot?.thesis || !Array.isArray(snapshot.evidence_links)) return null;
  return snapshot;
}

function mapEffectiveState(
  current: CampaignCurrentThesis | null,
  contextState: ResearchBriefContextState,
): ResearchBriefEffectiveState {
  if (contextState === "loading") {
    return {
      state: null,
      label: "未知",
      kind: "unknown",
      terminal: false,
      note: "正在读取当前确认状态。",
    };
  }
  if (contextState === "unavailable") {
    return {
      state: null,
      label: "未知",
      kind: "unknown",
      terminal: false,
      note: "上下文校验未通过，不能声称当前确认状态。",
    };
  }
  if (!current?.ready) {
    return {
      state: null,
      label: "未知",
      kind: "unknown",
      terminal: false,
      note: "Current Thesis 投影未就绪，没有当前确认状态。",
    };
  }
  const meta = STATE_META[current.effective_state]
    || { label: String(current.effective_state), kind: "unknown" as const };
  const terminal = TERMINAL_STATES.has(current.effective_state);
  return {
    state: current.effective_state,
    label: meta.label,
    kind: meta.kind,
    terminal,
    note: terminal
      ? "backend 投影已把该研究标记为终态。最初冻结观点不再成立，不能作为当前研究结论引用。"
      : "ready=true 只代表投影可读取；当前结论以上方确认状态与下方已确认变更为准。",
  };
}

function mapDeltas(
  current: CampaignCurrentThesis | null,
  contextState: ResearchBriefContextState,
): { updates: ResearchBriefConfirmedUpdate[]; malformedCount: number } {
  if (contextState !== "ready" || !current?.ready || !Array.isArray(current.deltas)) {
    return { updates: [], malformedCount: 0 };
  }
  const updates: ResearchBriefConfirmedUpdate[] = [];
  let malformedCount = 0;
  for (const item of current.deltas) {
    const state = (item as { delta_state?: unknown } | null)?.delta_state;
    const deltaId = (item as { delta_id?: unknown } | null)?.delta_id;
    const meta = typeof state === "string" ? STATE_META[state] : undefined;
    if (!item || typeof item !== "object" || !meta || typeof deltaId !== "string") {
      malformedCount += 1;
      continue;
    }
    const record = item as {
      delta_sequence?: unknown;
      reason?: unknown;
      confirmed_at?: unknown;
      base_revision?: unknown;
      evidence_links?: unknown;
    };
    const links = Array.isArray(record.evidence_links) ? record.evidence_links : [];
    updates.push({
      deltaId,
      sequence: typeof record.delta_sequence === "number" ? record.delta_sequence : 0,
      stateLabel: meta.label,
      stateKind: meta.kind,
      reason: typeof record.reason === "string" && record.reason ? record.reason : "未知原因",
      confirmedAt: typeof record.confirmed_at === "string" ? record.confirmed_at : null,
      baseRevision: typeof record.base_revision === "number" ? record.base_revision : null,
      evidence: links.filter(isEvidenceLinkLike).map(mapEvidence),
    });
  }
  return { updates, malformedCount };
}

function calendarText(value: ResearchContinuity["decision_calendar"] | undefined): string {
  if (!value) return "披露日历未读取；不能据此声称没有待核验节点。";
  if (value.state === "ERROR") return "ERROR · 披露日历暂不可用";
  if (value.state === "UNAVAILABLE") return "UNAVAILABLE · 披露日期无法可靠解析";
  if (value.state === "NO_RECORD") return "NO_RECORD · 暂无可核验的定期报告日程";
  if (value.state === "DELAYED_SIGNAL" && value.next?.appointment_date) {
    return `DELAYED_SIGNAL · 预约日 ${value.next.appointment_date} 已过，尚未见实际披露`;
  }
  if (value.state === "EXPECTED" && value.next?.appointment_date) {
    return `EXPECTED · 预约披露日 ${value.next.appointment_date}（不是公司保证日期）`;
  }
  return value.latest_actual?.actual_date
    ? `CONFIRMED · 最近实际披露 ${value.latest_actual.actual_date}`
    : String(value.state);
}

function baselineText(continuity: ResearchContinuity): string | null {
  const baseline = continuity.baseline;
  if (!baseline || baseline.status !== "READY") return null;
  const authority = baseline.authority_type === "FROZEN_DECISION"
    ? "Frozen Decision"
    : baseline.authority_type === "CANDIDATE_RESEARCH_FORMAL_ORIGINAL"
      ? "Candidate Research Formal Original"
      : shown(baseline.authority_type);
  return `基线 ${authority}${baseline.as_of ? ` · as_of ${baseline.as_of}` : ""}（口径：Current Thesis 的不可变 Evidence 快照）`;
}

const STANCE_LABELS: Record<string, string> = {
  support: "支持",
  oppose: "反对",
  neutral: "中立",
};

function changeDetail(item: ResearchContinuity["changes"]["items"][number]): string | null {
  const before = item.before?.values ?? null;
  const after = item.after?.values ?? null;
  if (item.change_type === "CHANGED") {
    const fields = item.changed_fields?.length
      ? item.changed_fields
      : Object.keys(after ?? {});
    const parts = fields.map(
      (field) =>
        `${FIELD_LABELS[field] || field}：${shown(before?.[field] ?? null)} → ${shown(after?.[field] ?? null)}`,
    );
    // 资料自身时间来自记录字段；读取时间（fetched_at）单独展示，不混作发布日期。
    if (after?.source_date) parts.push(`来源日期：${after.source_date}`);
    if (after?.accessed_at) parts.push(`记录时间：${after.accessed_at}`);
    return parts.length ? parts.join("；") : null;
  }
  if (item.change_type === "ADDED" && after) {
    const bits: string[] = [];
    const classification = classificationLabel(after.classification);
    if (classification) bits.push(`分类：${classification}`);
    if (after.confidence) bits.push(`置信度：${after.confidence}`);
    if (after.evidence_type) bits.push(`类型：${after.evidence_type}`);
    // 资料自身的时间来自记录字段；读取时间（fetched_at）单独展示，不混作发布日期。
    if (after.source_date) bits.push(`来源日期：${after.source_date}`);
    if (after.accessed_at) bits.push(`记录时间：${after.accessed_at}`);
    return bits.length ? bits.join(" · ") : null;
  }
  if (item.change_type === "SOURCE_CONFLICT" && item.records?.length) {
    // 默认摘要只保留关键差异（来源与立场）；完整原文与溯源在 conflictRecords 展开区。
    return item.records
      .map((record) => {
        const stance = typeof record.values?.stance === "string"
          ? STANCE_LABELS[record.values.stance] || record.values.stance
          : null;
        const sourceName = (typeof record.values?.source_title === "string" && record.values.source_title)
          || shown(record.source);
        return `${sourceName}：${stance ? `立场 ${stance}` : "立场未知"}`;
      })
      .join(" / ");
  }
  return null;
}

function conflictRecords(item: ResearchContinuity["changes"]["items"][number]): ResearchBriefConflictRecord[] | undefined {
  if (item.change_type !== "SOURCE_CONFLICT" || !item.records?.length) return undefined;
  return item.records.map((record) => {
    const values = record.values ?? {};
    const stance = typeof values.stance === "string" ? values.stance : null;
    return {
      source: shown(record.source),
      claim: record.claim_identity || shown(values.claim ?? null),
      stance,
      stanceLabel: stance ? STANCE_LABELS[stance] || stance : null,
      classificationLabel: classificationLabel(values.classification),
      confidence: typeof values.confidence === "string" ? values.confidence : null,
      sourceTitle: typeof values.source_title === "string" && values.source_title ? values.source_title : null,
      sourceUrl: typeof values.source_url === "string" && values.source_url ? values.source_url : null,
      sourceDate: typeof values.source_date === "string" && values.source_date ? values.source_date : null,
      recordedAt: typeof values.accessed_at === "string" && values.accessed_at ? values.accessed_at : null,
    };
  });
}

function mapChanges(
  continuity: ResearchContinuity | null,
  continuityError: string | null,
  campaignId: string,
): ResearchBriefModel["changes"] {
  if (continuityError) {
    return {
      status: "UNAVAILABLE",
      note: `变化摘要读取失败（${continuityError}）。不能声称没有变化。`,
      items: [],
      baselineText: null,
      fetchedAt: null,
      observationCount: null,
    };
  }
  if (!continuity) {
    return {
      status: "NOT_EVALUATED",
      note: "尚未读到研究连续性。不能声称没有变化。",
      items: [],
      baselineText: null,
      fetchedAt: null,
      observationCount: null,
    };
  }
  if (continuity.campaign_id !== campaignId) {
    return {
      status: "UNAVAILABLE",
      note: "研究连续性与当前 Campaign 不一致；已拒绝展示，避免混入其他研究的内容。",
      items: [],
      baselineText: null,
      fetchedAt: null,
      observationCount: null,
    };
  }
  const status = continuity.changes.status;
  if (status === "NO_BASELINE") {
    return {
      status,
      note: "NO_BASELINE · 尚无 Frozen Decision 或已提交的 Formal Original，不能声称没有变化。",
      items: [],
      baselineText: null,
      fetchedAt: continuity.fetched_at,
      observationCount: continuity.changes.observation_count,
    };
  }
  if (status === "NOT_EVALUATED") {
    return {
      status,
      note: "NOT_EVALUATED · 只有基线，没有后续不可变观察，不能声称没有变化。",
      items: [],
      baselineText: baselineText(continuity),
      fetchedAt: continuity.fetched_at,
      observationCount: continuity.changes.observation_count,
    };
  }
  if (status === "UNAVAILABLE") {
    return {
      status,
      note: "UNAVAILABLE · 基线或 Evidence 链无法完整验证，不能声称没有变化。",
      items: [],
      baselineText: null,
      fetchedAt: continuity.fetched_at,
      observationCount: continuity.changes.observation_count,
    };
  }
  const items: ResearchBriefChangeItem[] = continuity.changes.items.map((item) => {
    const claim =
      item.after?.claim_identity
      || item.before?.claim_identity
      || item.records?.[0]?.claim_identity
      || "未知事实";
    const source = shown(item.after?.source || item.before?.source || item.records?.[0]?.source);
    return {
      kind: item.change_type,
      label: CHANGE_LABEL[item.change_type],
      recordKey: item.record_key,
      claim,
      source,
      classificationLabel: classificationLabel(
        item.after?.values?.classification
          ?? item.before?.values?.classification
          ?? item.records?.[0]?.values?.classification,
      ),
      detail: changeDetail(item),
      conflictRecords: conflictRecords(item),
    };
  });
  if (items.length === 0) {
    return {
      status,
      note: "已有后续观察，完成比较后未发现证据字段变化。这不是“没有变化”的投资结论。",
      items,
      baselineText: baselineText(continuity),
      fetchedAt: continuity.fetched_at,
      observationCount: continuity.changes.observation_count,
    };
  }
  return {
    status,
    note: "只比较 Current Thesis 的不可变 Evidence 快照；变化内容保留比较双方原文。",
    items,
    baselineText: baselineText(continuity),
    fetchedAt: continuity.fetched_at,
    observationCount: continuity.changes.observation_count,
  };
}

export function buildResearchBrief(input: {
  campaignId: string;
  campaign: CampaignRecord | null;
  currentThesis: CampaignCurrentThesis | null;
  hydration: DecisionContextHydrationResult | null;
  continuity: ResearchContinuity | null;
  continuityError: string | null;
  contextState: ResearchBriefContextState;
  contextMessage: string;
}): ResearchBriefModel {
  const campaign = input.campaign;
  const strategyCode = campaign?.strategy ?? "";
  const strategyLabel = campaign
    ? CAMPAIGN_STRATEGY_LABELS[campaign.strategy] || campaign.strategy
    : "未知";
  // 只有上下文校验通过才展示冻结快照；校验失败绝不输出 CONFIRMED。
  const snapshot = confirmedSnapshot(input.currentThesis, input.contextState);
  const { updates, malformedCount } = mapDeltas(input.currentThesis, input.contextState);
  const effectiveState = mapEffectiveState(input.currentThesis, input.contextState);
  const hydration = input.hydration;
  let horizonText = "未知";
  let horizonSource: ResearchBriefModel["horizonSource"] = "LOADING";
  if (input.contextState === "ready" && hydration?.status === "READY") {
    horizonText = hydration.horizonText;
    horizonSource = "CURRENT_THESIS";
  } else if (input.contextState === "unavailable") {
    horizonText = "无法从已确认 Current Thesis 读取";
    horizonSource = "MANUAL_FALLBACK";
  }

  let thesisVersionText = "未知";
  if (input.contextState !== "ready") {
    thesisVersionText = input.contextState === "loading"
      ? "正在读取"
      : "Current Thesis 不可用";
  } else if (input.currentThesis?.ready) {
    thesisVersionText = `已确认冻结 v${input.currentThesis.frozen_revision}`;
  } else if (input.currentThesis) {
    thesisVersionText = `未就绪（${input.currentThesis.formal_status}）`;
  }

  let confirmed: ResearchBriefModel["confirmed"];
  if (input.contextState === "unavailable") {
    // 校验失败（identity / binding / revision）时，即使投影可读也不当作已确认内容。
    confirmed = {
      status: "UNAVAILABLE",
      title: null,
      summary: null,
      claims: [],
      note: `已确认研究观点当前不可用：${input.contextMessage || "UNKNOWN"}。不会把未确认草稿当作正式观点，也不展示校验失败对象的证据与失效条件。`,
    };
  } else if (input.contextState === "loading") {
    confirmed = {
      status: "NOT_CONFIRMED",
      title: null,
      summary: null,
      claims: [],
      note: "正在读取 Campaign / Current Thesis 上下文；尚未确认是否已有可引用的确认版本。",
    };
  } else if (snapshot) {
    const revision = input.currentThesis?.ready
      ? input.currentThesis.frozen_revision
      : snapshot.thesis.frozen_revision;
    confirmed = {
      status: "CONFIRMED",
      title: snapshot.thesis.title || null,
      summary: snapshot.thesis.summary || null,
      claims: snapshot.thesis.core_claims || [],
      note: `来源：Current Thesis 冻结快照 v${revision ?? "?"}（${snapshot.thesis.frozen_at ?? "冻结时间未知"}）。以下是最初冻结原文，不代表其后没有被削弱或推翻；当前结论以上方确认状态与已确认变更为准。`,
    };
  } else {
    confirmed = {
      status: "NOT_CONFIRMED",
      title: null,
      summary: null,
      claims: [],
      note: input.currentThesis && !input.currentThesis.ready
        ? `已绑定 Thesis，但尚未形成可引用的确认版本（${input.currentThesis.reason}）。页面表单与 AI 草稿不是已确认观点。`
        : "还没有可追溯的已确认 Current Thesis。不会把未确认草稿当作正式观点。",
    };
  }

  let updatesNote: string;
  if (input.contextState !== "ready" || !input.currentThesis?.ready) {
    updatesNote = "当前确认状态未读取或校验未通过；不展示已确认变更。";
  } else if (updates.length === 0) {
    updatesNote = "冻结后没有已确认变更记录（backend deltas 为空）；这不等于没有新证据或新变化。";
  } else {
    const latest = updates[updates.length - 1];
    updatesNote = `共 ${updates.length} 条已确认变更；最新一条：${latest.stateLabel} · ${latest.reason}${latest.confirmedAt ? ` · ${latest.confirmedAt}` : ""}。`;
  }

  const links = snapshot?.evidence_links ?? [];
  const supporting = links.filter((item) => item.stance === "support").map(mapEvidence);
  const opposing = links.filter((item) => item.stance === "oppose").map(mapEvidence);
  const opposingFromUpdates = updates.reduce(
    (count, update) => count + update.evidence.filter((item) => item.stance === "oppose").length,
    0,
  );
  let evidenceNote = "证据来自已确认冻结快照与已确认变更的不可变关联记录，并标出事实 / 推断 / 未知。";
  if (!snapshot) {
    evidenceNote = "没有已确认版本的证据快照，不展示未确认草稿中的证据。";
  } else if (opposing.length === 0 && opposingFromUpdates === 0) {
    evidenceNote = "最初冻结版本及其后的已确认变更都没有反对立场的证据记录；这不等于没有反对证据。";
  }

  const conditions = snapshot?.thesis.invalidation_conditions ?? [];
  const invalidationNote = input.contextState !== "ready"
    ? "上下文未就绪或校验未通过；不把任何失效条件当作已确认内容展示。"
    : snapshot
      ? (conditions.length
        ? "以下是已记录的失效条件，不是这些条件已经触发。"
        : "已确认版本没有记录失效条件；这不等于不存在失效风险。")
      : "没有已确认版本，不把表单里的失效条件当作正式记录。";

  const gaps: string[] = [];
  // 只有与当前 Campaign 同源的 continuity 才参与展示；不匹配视为未读取。
  const continuityScoped = input.continuity && input.continuity.campaign_id === input.campaignId
    ? input.continuity
    : null;
  if (input.contextState === "unavailable") {
    gaps.push(`Campaign / Current Thesis 上下文：${input.contextMessage || "不可用"}`);
  }
  if (!snapshot) gaps.push("缺少已确认冻结 Thesis 快照");
  if (malformedCount > 0) gaps.push(`存在 ${malformedCount} 条无法解析的已确认变更记录`);
  if (input.continuityError) gaps.push(`研究连续性读取失败：${input.continuityError}`);
  else if (input.continuity && input.continuity.campaign_id !== input.campaignId) {
    gaps.push("研究连续性与当前 Campaign 不一致");
  } else if (!continuityScoped) gaps.push("尚未读到研究连续性");
  else if (continuityScoped.changes.status !== "NORMAL") {
    gaps.push(`变化比较：${continuityScoped.changes.status}`);
  }
  if (snapshot && opposing.length === 0 && opposingFromUpdates === 0) {
    gaps.push("确认版本未记录反对证据");
  }
  if (snapshot && conditions.length === 0) gaps.push("确认版本未记录失效条件");
  if (horizonSource !== "CURRENT_THESIS") gaps.push("预期周期无法从已确认 Thesis 读取");
  const calendar = continuityScoped?.decision_calendar;
  if (
    calendar
    && (calendar.state === "NO_RECORD" || calendar.state === "UNAVAILABLE" || calendar.state === "ERROR")
  ) {
    gaps.push(`披露日历：${calendar.state}`);
  }

  return {
    campaignId: campaign?.campaign_id || input.campaignId,
    securityCode: campaign?.security_code || "UNKNOWN",
    strategyCode,
    strategyLabel,
    horizonText,
    thesisVersionText,
    horizonSource,
    contextState: input.contextState,
    effectiveState,
    confirmed,
    confirmedUpdates: updates,
    updatesNote,
    changes: mapChanges(input.continuity, input.continuityError, input.campaignId),
    evidence: {
      supporting,
      opposing,
      opposingRecorded: opposing.length + opposingFromUpdates > 0,
      note: evidenceNote,
    },
    invalidation: { conditions, note: invalidationNote },
    freshness: {
      frozenAt: snapshot?.thesis.frozen_at ?? null,
      calendarText: calendarText(continuityScoped?.decision_calendar),
      gaps,
    },
  };
}
