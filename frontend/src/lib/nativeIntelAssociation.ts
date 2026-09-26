import type { NativeIntelItemEntity } from "./api/types.ts";

const kindLabel = (kind: string) => ({ security_code: "证券代码词", company_name: "公司名称词", industry: "行业词", concept: "概念词" } as Record<string, string>)[kind] || "未知类型词";

/** Deduplicate shared mapped words, without inferring company event relevance. */
export function articleAssociationText(entities?: readonly NativeIntelItemEntity[]): string {
  if (!entities?.length) return "文章关联依据：暂无已保存的词面关联，相关性未知。";
  const words = [...new Map(entities.map((entity) => [
    JSON.stringify([entity.term_kind, entity.term]), entity,
  ])).values()];
  const labels = words.slice(0, 3).map((entity) => {
    const term = Array.from(entity.term);
    return `${kindLabel(entity.term_kind)}「${term.slice(0, 24).join("")}${term.length > 24 ? "…" : ""}」`;
  });
  return `关联词：${labels.join("、")}${words.length > 3 ? `等 ${words.length} 项` : ""}。词面关联不代表公司直接事件。`;
}

/** Full saved match and current mapping provenance, shown only on expansion. */
export function articleAssociationDetail(entity: NativeIntelItemEntity): string {
  const location = entity.matched_in === "title" ? "标题命中"
    : entity.matched_in === "summary" ? "摘要命中" : "命中位置未知";
  const subject = entity.security_code || "证券未知";
  const kind = kindLabel(entity.term_kind);
  const source = entity.source_ref || "未知";
  return `${location} ${subject} 映射的${kind}「${entity.term}」（当前映射来源：${source}）`;
}
