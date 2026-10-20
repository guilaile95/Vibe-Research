export interface FilingDocument {
  id: string; evidence_id: string; issuer: string; form: string;
  source_title: string; source_identity: string; revision: string;
  source_date: string | null; source_url: string | null; sha256: string;
  registered_at: string; corrects_id: string | null; text?: string;
  sections: { key: string; title: string; start: number; end: number }[];
  warnings: string[]; provenance: 'USER_SUPPLIED_UNVERIFIED';
}
export interface FilingContext {
  documents: FilingDocument[]; original_text_status: string; notice: string; has_more: boolean;
}
export interface FilingDiff {
  changes: { kind: string; before: string; after: string }[];
  before: { id: string; sha256: string; revision: string };
  after: { id: string; sha256: string; revision: string };
  section: string; method: string; interpretation: string;
}
export function filingSourceUrl(value: string | null): string | null {
  try {
    if (!value || /\s/.test(value)) return null;
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? value : null;
  } catch { return null; }
}
export function comparableSections(before?: FilingDocument, after?: FilingDocument) {
  if (!before || !after || before.id === after.id || before.issuer !== after.issuer || before.form !== after.form) return [];
  return before.sections.filter(section => after.sections.some(s => s.key === section.key));
}
export async function filingRequest<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`/api/filing-evidence${path}`, {
    method: payload === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '文档请求失败，请刷新后重试');
  return body.data as T;
}
