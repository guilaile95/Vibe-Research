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

export interface ResearchBriefChangeItem {
  kind: "ADDED" | "CHANGED" | "SOURCE_CONFLICT";
  label: string;
  claim: string;
  source: string;
  detail: string | null;
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
  confirmed: {
    status: "CONFIRMED" | "NOT_CONFIRMED" | "UNAVAILABLE";
    title: string | null;
    summary: string | null;
    claims: string[];
    note: string;
  };
  changes: {
    status: string;
    note: string;
    items: ResearchBriefChangeItem[];
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
  ADDED: "新增事实",
  CHANGED: "事实变化",
  SOURCE_CONFLICT: "来源冲突",
} as const;

const CLASSIFICATION_LABEL: Record<string, string> = {
  fact: "事实",
  inference: "推断",
  unknown: "未知",
};

function shown(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "未知" : value;
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

function confirmedSnapshot(current: CampaignCurrentThesis | null): ThesisAggregate | null {
  if (!current?.ready) return null;
  const snapshot = current.original_snapshot;
  if (!snapshot?.thesis || !Array.isArray(snapshot.evidence_links)) return null;
  return snapshot;
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

function mapChanges(continuity: ResearchContinuity | null, continuityError: string | null): ResearchBriefModel["changes"] {
  if (continuityError) {
    return {
      status: "UNAVAILABLE",
      note: `变化摘要读取失败（${continuityError}）。不能声称没有变化。`,
      items: [],
    };
  }
  if (!continuity) {
    return {
      status: "NOT_EVALUATED",
      note: "尚未读到研究连续性。不能声称没有变化。",
      items: [],
    };
  }
  const status = continuity.changes.status;
  if (status === "NO_BASELINE") {
    return {
      status,
      note: "NO_BASELINE · 尚无 Frozen Decision 或已提交的 Formal Original，不能声称没有变化。",
      items: [],
    };
  }
  if (status === "NOT_EVALUATED") {
    return {
      status,
      note: "NOT_EVALUATED · 只有基线，没有后续不可变观察，不能声称没有变化。",
      items: [],
    };
  }
  if (status === "UNAVAILABLE") {
    return {
      status,
      note: "UNAVAILABLE · 基线或 Evidence 链无法完整验证，不能声称没有变化。",
      items: [],
    };
  }
  const items: ResearchBriefChangeItem[] = continuity.changes.items.map((item) => {
    const claim =
      item.after?.claim_identity
      || item.before?.claim_identity
      || item.records?.[0]?.claim_identity
      || "未知事实";
    const source = shown(item.after?.source || item.before?.source || item.records?.[0]?.source);
    let detail: string | null = null;
    if (item.change_type === "CHANGED" && item.changed_fields?.length) {
      detail = item.changed_fields.join("、");
    }
    if (item.change_type === "SOURCE_CONFLICT" && item.records?.length) {
      detail = item.records.map((record) => shown(record.source)).join(" / ");
    }
    return {
      kind: item.change_type,
      label: CHANGE_LABEL[item.change_type],
      claim,
      source,
      detail,
    };
  });
  if (items.length === 0) {
    return {
      status,
      note: "已有后续观察，未发现事实字段变化。这不是“没有变化”的投资结论。",
      items: [],
    };
  }
  return { status, note: "只比较 Current Thesis 的不可变 Evidence 快照。", items };
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
  const snapshot = confirmedSnapshot(input.currentThesis);
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
  if (input.currentThesis?.ready) {
    thesisVersionText = `已确认冻结 v${input.currentThesis.frozen_revision}`;
  } else if (input.currentThesis) {
    thesisVersionText = `未就绪（${input.currentThesis.formal_status}）`;
  } else if (input.contextState === "unavailable") {
    thesisVersionText = "Current Thesis 不可用";
  }

  let confirmed: ResearchBriefModel["confirmed"];
  if (input.contextState === "unavailable" && !snapshot) {
    confirmed = {
      status: "UNAVAILABLE",
      title: null,
      summary: null,
      claims: [],
      note: `已确认研究观点当前不可用：${input.contextMessage || "UNKNOWN"}。不会把未确认草稿当作正式观点。`,
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
      note: `来源：Current Thesis 冻结快照 v${revision ?? "?"}。`,
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

  const links = snapshot?.evidence_links ?? [];
  const supporting = links.filter((item) => item.stance === "support").map(mapEvidence);
  const opposing = links.filter((item) => item.stance === "oppose").map(mapEvidence);
  let evidenceNote = "证据来自已确认冻结快照的关联记录，并标出事实 / 推断 / 未知。";
  if (!snapshot) {
    evidenceNote = "没有已确认版本的证据快照，不展示未确认草稿中的证据。";
  } else if (opposing.length === 0) {
    evidenceNote = "当前确认版本没有反对立场的证据记录；这不等于没有反对证据。";
  }

  const conditions = snapshot?.thesis.invalidation_conditions ?? [];
  const invalidationNote = snapshot
    ? (conditions.length
      ? "以下是已记录的失效条件，不是这些条件已经触发。"
      : "已确认版本没有记录失效条件；这不等于不存在失效风险。")
    : "没有已确认版本，不把表单里的失效条件当作正式记录。";

  const gaps: string[] = [];
  if (input.contextState === "unavailable") {
    gaps.push(`Campaign / Current Thesis 上下文：${input.contextMessage || "不可用"}`);
  }
  if (!snapshot) gaps.push("缺少已确认冻结 Thesis 快照");
  if (input.continuityError) gaps.push(`研究连续性读取失败：${input.continuityError}`);
  else if (!input.continuity) gaps.push("尚未读到研究连续性");
  else if (input.continuity.changes.status !== "NORMAL") {
    gaps.push(`变化比较：${input.continuity.changes.status}`);
  }
  if (snapshot && opposing.length === 0) gaps.push("确认版本未记录反对证据");
  if (snapshot && conditions.length === 0) gaps.push("确认版本未记录失效条件");
  if (horizonSource !== "CURRENT_THESIS") gaps.push("预期周期无法从已确认 Thesis 读取");
  const calendar = input.continuity?.decision_calendar;
  if (calendar && (calendar.state === "NO_RECORD" || calendar.state === "UNAVAILABLE" || calendar.state === "ERROR")) {
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
    confirmed,
    changes: mapChanges(input.continuity, input.continuityError),
    evidence: {
      supporting,
      opposing,
      opposingRecorded: opposing.length > 0,
      note: evidenceNote,
    },
    invalidation: { conditions, note: invalidationNote },
    freshness: {
      frozenAt: snapshot?.thesis.frozen_at ?? null,
      calendarText: calendarText(input.continuity?.decision_calendar),
      gaps,
    },
  };
}
