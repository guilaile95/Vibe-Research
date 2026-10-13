import type { EvidenceRecord } from "./api/types";
import { safeInternalReturnTo } from "./internalReturnTo.ts";
import { researchVisitHref } from "./researchResume.ts";

/** Optional browser-local research context. Never formal evidence or decision authority. */
export interface NoteResearchMetadata {
  securityCode: string;
  question?: string;
  sourceLinks?: Array<{ title: string; url: string }>;
  returnTo?: string;
  tentativeView?: string;
  contraryEvidence?: string;
  nextQuestion?: string;
}

/** Sources describe supplied context, not proof that the model verified each source. */
export function conversationNoteMetadata(
  current: NoteResearchMetadata,
  history: readonly (NoteResearchMetadata | undefined)[],
): NoteResearchMetadata {
  const parsed = parseNoteResearchMetadata(current);
  const links = new Map((parsed.sourceLinks ?? []).map((link) => [link.url, link]));
  for (const previous of history) {
    if (!previous || previous.securityCode !== parsed.securityCode) continue;
    for (const link of previous.sourceLinks ?? []) {
      if (!links.has(link.url)) links.set(link.url, {
        ...link, title: link.title.startsWith("历史轮次 · ") ? link.title : `历史轮次 · ${link.title}`,
      });
    }
  }
  if (links.size > 20) throw new Error("这段对话的研究来源已超过 20 条，请先保存已有回答并清空对话，再开始新的研究；本次未发送。");
  return parseNoteResearchMetadata({ ...parsed, sourceLinks: [...links.values()] });
}

export function safeResearchSourceUrl(value: string): string | null {
  if (value.startsWith("/")) {
    const local = safeInternalReturnTo(value, "");
    return local && /^\/evidence\/[^/?#]+(?:[?#]|$)/.test(local) ? local : null;
  }
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

/** Strict optional-field validation keeps imported metadata from becoming unsafe navigation. */
export function parseNoteResearchMetadata(value: unknown): NoteResearchMetadata {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("研究上下文格式无效");
  const input = value as Record<string, unknown>;
  if (typeof input.securityCode !== "string" || !/^\d{6}$/.test(input.securityCode)) throw new Error("研究上下文证券代码无效");
  const result: NoteResearchMetadata = { securityCode: input.securityCode };
  for (const key of ["question", "tentativeView", "contraryEvidence", "nextQuestion"] as const) {
    if (input[key] !== undefined) {
      if (typeof input[key] !== "string") throw new Error(`研究上下文 ${key} 无效`);
      result[key] = input[key];
    }
  }
  if (input.returnTo !== undefined) {
    if (typeof input.returnTo !== "string") throw new Error("研究返回位置无效");
    const path = researchVisitHref(input.returnTo);
    if (!path || new URL(path, "http://localhost").pathname !== `/candidates/${input.securityCode}`) throw new Error("研究返回位置与证券不一致");
    result.returnTo = path;
  }
  if (input.sourceLinks !== undefined) {
    if (!Array.isArray(input.sourceLinks) || input.sourceLinks.length > 20) throw new Error("研究来源列表无效");
    result.sourceLinks = input.sourceLinks.map((entry) => {
      if (!entry || typeof entry !== "object" || typeof entry.title !== "string" || typeof entry.url !== "string") throw new Error("研究来源无效");
      const url = safeResearchSourceUrl(entry.url);
      if (!url) throw new Error("研究来源链接无效");
      return { title: entry.title, url };
    });
  }
  return result;
}

/** Select only explicit, currently loaded records for this security; never positions or account data. */
export function candidateResearchSelection(code: string, records: readonly EvidenceRecord[], selectedIds: readonly string[]) {
  const selected = new Set(selectedIds);
  return records.filter((record) => record.subject_type === "stock" && record.subject_id === code && !record.deleted && selected.has(record.id)).slice(0, 10);
}

export function candidateResearchContext(code: string, records: readonly EvidenceRecord[], selectedIds: readonly string[]): string {
  const selected = candidateResearchSelection(code, records, selectedIds);
  return [
    `候选研究 · ${code}。以下仅为用户本次明确选中的本地证据摘录，不代表已读取原始来源全文。`,
    "这是非正式研究讨论；区分原记录中的事实、推断和未知，不替用户确认投资逻辑或决策。未自动加入行情图表、未选证据、账户持仓或资金字段及其他页面内容；所选摘录仍按用户提供的原文理解。",
    selected.length ? `本次选中 ${selected.length} 条：` : "本次没有选择证据；只能帮助梳理研究问题，不能声称已核验这只股票的事实。",
    ...selected.map((record, index) => [
      `[${index + 1}] ${record.source_title || "来源标题未知"} · 记录 ${record.id}`,
      `原记录分类：${record.classification}；置信度：${record.confidence}；来源日期：${record.source_date || "未知"}`,
      `摘录：${record.claim}`,
      `来源链接：${record.source_url && safeResearchSourceUrl(record.source_url) || "未提供安全链接"}`,
    ].join("\n")),
  ].join("\n\n");
}

export function candidateResearchSourceLinks(records: readonly EvidenceRecord[]): NoteResearchMetadata["sourceLinks"] {
  return records.map((record) => ({
    title: record.source_title || record.claim,
    url: record.source_url && safeResearchSourceUrl(record.source_url) || `/evidence/${encodeURIComponent(record.id)}`,
  }));
}
