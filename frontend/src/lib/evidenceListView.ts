export const EVIDENCE_PAGE_SIZE = 50;
export const EVIDENCE_SUBJECT_LABELS: Record<string, string> = {
  stock: "个股", sector: "板块", theme: "主题",
};

/** A subject is a pair: never silently turn a partial deep link into an all-subject query. */
export function parseEvidenceListQuery(search: URLSearchParams) {
  const subjectType = search.get("subject_type") ?? "";
  const subjectId = (search.get("subject_id") ?? "").trim();
  const rawPage = search.get("page") ?? "1";
  const value = /^\d+$/.test(rawPage) ? Number(rawPage) : 1;
  const page = value >= 1 && Number.isSafeInteger(value * EVIDENCE_PAGE_SIZE) ? value : 1;
  const error = subjectType && !Object.prototype.hasOwnProperty.call(EVIDENCE_SUBJECT_LABELS, subjectType)
    ? "请选择有效的主体类型。"
    : Boolean(subjectType) !== Boolean(subjectId)
      ? "请同时选择主体类型并填写代码或标识，或清除筛选查看全部证据。"
      : null;
  return { subjectType, subjectId, page, offset: (page - 1) * EVIDENCE_PAGE_SIZE, error };
}

/** Preserve inbound navigation context while resetting pagination on a new filter. */
export function evidenceFilterQuery(current: URLSearchParams, subjectType: string, subjectId: string) {
  const next = new URLSearchParams(current);
  next.delete("page");
  for (const [key, value] of [["subject_type", subjectType], ["subject_id", subjectId.trim()]]) {
    if (value) next.set(key, value);
    else next.delete(key);
  }
  return next;
}

export function evidencePageQuery(current: URLSearchParams, page: number) {
  const next = new URLSearchParams(current);
  if (page <= 1) next.delete("page");
  else next.set("page", String(page));
  return next;
}

export function evidenceDateLabel(value: string | null | undefined) {
  if (!value?.trim()) return "未知";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "未知（日期无效）";
  // A source's calendar date is not an instant and must not shift with the viewer's timezone.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return date.toISOString().slice(0, 10) === value ? value : "未知（日期无效）";
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}
