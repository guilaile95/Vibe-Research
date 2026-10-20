// Synthetic storage contracts, not a substitute for backend persistence validation.
export const anchor = { id: 'anchor', edit_token: 'v1', subject_type: 'stock', subject_id: '000001', evidence_type: 'financial_filing', source_title: 'Synthetic filing', claim: 'Synthetic claim', source_date: '2026-01-01', source_url: null, updated_at: '2026-01-01T00:00:00Z' };
export function predictionData(records) {
  const binary = records.filter(r => ['TRUE', 'FALSE'].includes(r.outcome));
  return { schema_version: 'manual-prediction.v1', as_of: '2031-01-01T00:00:00Z', records,
    summary: { total: records.length, resolved_binary: binary.length, unresolved: records.filter(r => r.outcome === 'UNRESOLVED').length, indeterminate: records.filter(r => r.outcome === 'INDETERMINATE').length,
      brier: binary.length ? binary.reduce((s, r) => s + (r.forecast.probability - Number(r.outcome === 'TRUE')) ** 2, 0) / binary.length : null,
      benchmark_count: 0, benchmark_brier: null, matched_forecast_brier: null, sample_caution: true, display_caution_minimum: 20,
      bins: Array.from({ length: 10 }, (_, i) => { const rows = binary.filter(r => Math.min(9, Math.floor(r.forecast.probability * 10)) === i); return { lower: i / 10, upper: (i + 1) / 10, upper_inclusive: i === 9, count: rows.length, mean_probability: rows.length ? rows.reduce((s,r) => s+r.forecast.probability,0)/rows.length : null, observed_frequency: rows.length ? rows.filter(r => r.outcome === 'TRUE').length/rows.length : null, sample_caution: true }; }),
    } };
}
export function syntheticApi() {
  const state = { calls: [], documents: [], notes: [], records: [], groups: [], versions: [], wrongDcf: false, failAnnotation: false, expireAllocation: false };
  const candidate = { ...anchor, id: 'commentary', source_title: 'Synthetic commentary', evidence_type: 'announcement' };
  function dispatch(method, url, body) {
    const path = url.pathname.replace(/^\/api/, '');
    state.calls.push({ method, path, body });
    if (method === 'POST' && path === '/company-research/reverse-dcf') return { schema_version: 'reverse-dcf.v1', classification: 'MODEL_IMPLIED_NOT_FORECAST', input_verification: 'USER_ENTERED_UNVERIFIED', inputs: state.wrongDcf ? { ...body, symbol: '000002' } : body, evaluated_on: '2026-01-06', status: 'SOLVED', implied_growth: 0.05, residual_ev: 0, reason_codes: [], sensitivity: body.assumptions.sensitivity_wacc.map(wacc => ({ wacc, status: 'SOLVED', implied_growth: 0.05, residual_ev: 0 })) };
    if (method === 'GET' && /^\/filing-evidence\/context\/(anchor|other)$/.test(path)) return { documents: path.endsWith('/other') ? [] : state.documents, original_text_status: state.documents.length ? 'AVAILABLE' : 'UNAVAILABLE', notice: 'synthetic', has_more: false };
    if (method === 'POST' && path === '/filing-evidence/documents/anchor') { const doc = { ...body, id: `doc-${state.documents.length+1}`, evidence_id: 'anchor', issuer: '000001', sha256: String(state.documents.length+1).repeat(64), registered_at: '2026-01-06T00:00:00Z', warnings: [], provenance: 'USER_SUPPLIED_UNVERIFIED', sections: [{ key: 'document', title: '全文', start: 0, end: body.text.length }] }; state.documents.push(doc); return doc; }
    if (method === 'GET' && /^\/filing-evidence\/documents\/doc-\d+$/.test(path)) return state.documents.find(d => d.id === path.split('/').at(-1));
    if (method === 'POST' && path === '/filing-evidence/compare') { const before = state.documents.find(d => d.id === body.before_id), after = state.documents.find(d => d.id === body.after_id); return { before, after, section: body.section, method: 'synthetic', interpretation: 'not verified', changes: [{ kind: 'replace', before: before.text, after: after.text }] }; }
    if (method === 'GET' && path === '/research-annotations') return { records: [...state.notes, { id: 'wrong-subject', code: '000002', text: 'MUST NOT DISPLAY WRONG SUBJECT' }] };
    if (method === 'POST' && path === '/research-annotations') { if (state.failAnnotation) return { errorStatus: 409, detail: 'Synthetic stale snapshot' }; const note = { ...body, code: body.context.code, bar_period: 'day', snapshot_id: body.context.snapshot_id, id: `note-${state.notes.length+1}`, link_revision: null, created_at: '2026-01-06T00:00:00Z' }; state.notes.push(note); return note; }
    if (method === 'GET' && path === '/prediction-journal') return predictionData(state.records);
    if (method === 'POST' && path === '/prediction-journal') { const record = { schema_version: 'manual-prediction.v1', forecast: body, locked_at: '2026-01-01T00:00:00Z', revision: 0, outcome: 'UNRESOLVED', history: [] }; state.records.push(record); return record; }
    if (method === 'POST' && /^\/prediction-journal\/[^/]+\/resolutions$/.test(path)) { const record = state.records.find(r => r.forecast.id === path.split('/')[2]); record.revision++; record.outcome = body.outcome; record.history.push({ revision: record.revision, recorded_at: '2031-01-01T00:00:00Z', resolution: body }); return record; }
    if (method === 'GET' && path === '/portfolio/allocation-targets') return { latest_version: state.versions.length, active_version: state.versions.length || null, versions: state.versions, status: state.versions.length ? 'COMPARABLE' : 'NOT_CONFIGURED', as_of: '2026-01-06T00:00:00Z', valid_until: new Date(Date.now() + (state.expireAllocation ? -1000 : 60000)).toISOString(), denominator: state.versions.length ? 1000 : null, reasons: [], limitations: ['Synthetic account; no trading actions'], coverage: { holding_count: 1, priced_count: 1, unknown_industry_count: 1 }, rows: state.versions.length ? [{ key: '000001', target_pct: 40, actual_pct: 50, drift_pp: 10, reason: null }, { key: 'CASH', target_pct: null, actual_pct: 50, drift_pp: null, reason: '未指定目标' }] : [] };
    if (method === 'PUT' && path === '/portfolio/allocation-targets') { const version = { version: state.versions.length+1, created_at: '2026-01-06T00:00:00Z', input: body }; state.versions.push(version); return version; }
    if (method === 'GET' && /^\/announcement-groups\/context\/(anchor|other)$/.test(path)) return { groups: path.endsWith('/other') ? [] : state.groups, history: state.groups, candidates: path.endsWith('/other') ? [] : [anchor, candidate], current_members: path.endsWith('/other') ? [] : state.groups.length ? [anchor, candidate] : [anchor], member_conflicts: [], has_more: false, ownership_change: { status: 'UNAVAILABLE' } };
    if (method === 'POST' && path === '/announcement-groups') { const group = { ...body, group_id: 'group-1', subject_id: '000001', revision: 1, created_at: '2026-01-06T00:00:00Z', members: body.members.map(m => ({ ...m, source_kind: 'user', evidence_snapshot: m.evidence_id === 'anchor' ? anchor : candidate })) }; state.groups = [group]; return group; }
    throw new Error(`Unexpected synthetic route: ${method} ${url.pathname}${url.search}`);
  }
  return { state, dispatch };
}

// Every mutation workflow must demonstrate its own readback at each viewport.
export function auditMutationReadbacks(calls) {
  const missing = [];
  for (const width of [1280, 375]) {
    for (const [workflow, method, path, readPath] of [
      ['filing', 'POST', '/filing-evidence/documents/anchor', '/filing-evidence/context/anchor'],
      ['annotation', 'POST', '/research-annotations', '/research-annotations'],
      ['prediction', 'POST', '/prediction-journal', '/prediction-journal'],
      ['allocation', 'PUT', '/portfolio/allocation-targets', '/portfolio/allocation-targets'],
      ['groups', 'POST', '/announcement-groups', '/announcement-groups/context/anchor'],
    ]) {
      const id = `${workflow}-${width}`;
      const scoped = calls.filter(call => call.case === id);
      const write = scoped.findIndex(call => call.method === method && call.path === path);
      if (write < 0 || !scoped.slice(write + 1).some(call => call.method === 'GET' && call.path === readPath)) {
        missing.push({ case: id, error: `${method} ${path} must have a subsequent ${readPath} readback in this case` });
      }
    }
  }
  return missing;
}
