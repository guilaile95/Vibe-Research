/** Only a completed, identifiable response can replace the previous result. */
export function isCompletedAnalysis(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  if (row.status !== "SUCCESS" || typeof row.artifact_id !== "string" || !row.artifact_id
    || typeof row.generated_at !== "string" || !row.generated_at || !row.counts || typeof row.counts !== "object") return false;
  const counts = row.counts as Record<string, unknown>;
  return ["total_news", "analyzed_news", "hotlist_count", "rss_count", "hotlist_analyzed", "rss_analyzed"].every(key =>
    typeof counts[key] === "number" && Number.isSafeInteger(counts[key]) && (counts[key] as number) >= 0);
}

/** Coverage belongs to the saved input, never to today's configuration. */
export function rssNotAnalyzedMessage(reason?: string): string {
  const reasons: Record<string, string> = {
    disabled: "生成时已关闭RSS输入",
    no_items: "本次可用RSS输入为0条",
    budget_exhausted: "本次输入预算未纳入RSS",
    source_unavailable: "RSS来源不可用",
  };
  return `本次未分析RSS：${reasons[reason ?? ""] ?? "本次实际纳入0条，具体原因未记录"}；不代表无新增信息。`;
}
