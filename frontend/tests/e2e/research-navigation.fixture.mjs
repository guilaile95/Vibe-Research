/** Synthetic EvidenceListResult, including the production pagination contract. */
export function navigationEvidencePage(records, search) {
  const limit = Number(search.get('limit') ?? 200);
  const offset = Number(search.get('offset') ?? 0);
  const matching = records.filter(record => !record.deleted
    && record.subject_type === search.get('subject_type')
    && record.subject_id === search.get('subject_id'));
  return { items: matching.slice(offset, offset + limit), total: matching.length, limit, offset };
}
