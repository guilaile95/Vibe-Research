import type { EvidenceListResult, EvidenceRecord } from "./api/types.ts";

export class CandidateEvidenceLoadError extends Error {
  constructor() {
    super("证据列表在读取期间发生变化或未完整返回，请刷新后重试");
  }
}

/** Only publish coverage after every page has arrived; offset pages are not a server snapshot. */
export async function loadCandidateEvidence(
  readPage: (params: { limit: number; offset: number }) => Promise<EvidenceListResult>,
  isCancelled: () => boolean,
): Promise<{ records: EvidenceRecord[]; total: number } | null> {
  const limit = 200;
  const records: EvidenceRecord[] = [];
  const ids = new Set<string>();
  let total = 0;
  let firstPage: EvidenceRecord[] = [];

  do {
    if (isCancelled()) return null;
    const page = await readPage({ limit, offset: records.length });
    if (isCancelled()) return null;
    if (records.length === 0) {
      total = page.total;
      firstPage = page.items;
    }
    if (!Number.isSafeInteger(total) || total < 0 || page.total !== total
      || page.offset !== records.length || page.items.length !== Math.min(limit, total - records.length)) {
      throw new CandidateEvidenceLoadError();
    }
    for (const record of page.items) {
      if (ids.has(record.id)) throw new CandidateEvidenceLoadError();
      ids.add(record.id);
      records.push(record);
    }
  } while (records.length < total);

  if (total > limit) {
    // Detect changed totals and head reordering while loading offset pages; no automatic retry loop.
    if (isCancelled()) return null;
    const head = await readPage({ limit, offset: 0 });
    if (isCancelled()) return null;
    if (head.total !== total || head.offset !== 0
      || JSON.stringify(head.items.map(({ id, updated_at }) => [id, updated_at]))
        !== JSON.stringify(firstPage.map(({ id, updated_at }) => [id, updated_at]))) {
      throw new CandidateEvidenceLoadError();
    }
  }
  return { records, total };
}
