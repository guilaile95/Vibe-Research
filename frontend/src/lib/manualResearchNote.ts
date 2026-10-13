import { parseNoteResearchMetadata, safeResearchSourceUrl, type NoteResearchMetadata } from "./researchNote.ts";

export interface ManualResearchNoteDraft {
  title: string;
  content: string;
  securityCode: string;
  sourceTitle: string;
  sourceUrl: string;
}

export function manualResearchNotePayload(draft: ManualResearchNoteDraft): {
  kind: string; title: string; content: string; research?: NoteResearchMetadata;
} {
  const title = draft.title.trim(), content = draft.content.trim(), code = draft.securityCode.trim();
  const sourceTitle = draft.sourceTitle.trim(), sourceUrl = draft.sourceUrl.trim();
  if (!title || title.length > 120) throw new Error("请填写 1–120 字的记录标题。");
  if (!content || content.length > 6000) throw new Error("请填写 1–6000 字的记录正文。");
  if (code && !/^\d{6}$/.test(code)) throw new Error("关联股票代码须为 6 位数字，也可以留空保存普通记录。");
  if (Boolean(sourceTitle) !== Boolean(sourceUrl)) throw new Error("来源标题和链接需一起填写，也可以一起留空。");
  if (sourceTitle.length > 200 || sourceUrl.length > 2048) throw new Error("来源标题最多 200 字，链接最多 2048 字。");
  if (sourceUrl && !code) throw new Error("关联来源需要填写股票代码；也可以清空来源字段，先保存普通记录。");
  const safeUrl = sourceUrl ? safeResearchSourceUrl(sourceUrl) : null;
  if (sourceUrl && !safeUrl) throw new Error("来源链接须为无账户信息的 http/https 地址或本应用的证据详情路径。");
  return {
    kind: "暂定研究", title,
    content: `用户手动记录，尚未核验。\n\n${content}`,
    ...(code ? { research: parseNoteResearchMetadata({ securityCode: code,
      ...(safeUrl ? { sourceLinks: [{ title: sourceTitle, url: safeUrl }] } : {}),
    }) } : {}),
  };
}
