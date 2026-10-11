// Generated from real backend _continuity/_chain/compare_evidence: 11 additions,
// one modified original, one multi-source conflict. No real account/provider data.
import items from './research-continuity-adapter/changes.json' with { type: 'json' };
export function continuity(marker) {
  return { schema_version: 'research_continuity.v0.1', status: 'NORMAL', campaign_id: marker,
    security_code: '000001', strategy: 'SWING', fetched_at: '2026-10-11T00:00:00Z',
    baseline: { status: 'READY', authority_type: 'CANDIDATE_RESEARCH_FORMAL_ORIGINAL' },
    changes: { status: 'NORMAL', observation_count: 1, items }, authority_refs: [],
    decision_calendar: { state: 'NO_RECORD', next: null, latest_actual: null, source: `SYNTHETIC_${marker}`, fetched_at: '2026-10-11T00:00:00Z' },
    writes: { thesis: 0, decision: 0, campaign: 0, trade: 0 } };
}
export function readOnlyReply(method, path, marker = 'A', failed = false) {
  if (method !== 'GET' || !/^\/api\/campaigns\/[AB]\/research-continuity$/.test(path)) return null;
  return failed ? { status: 503, json: { detail: 'Synthetic obsolete error' } } : { status: 200, json: { data: continuity(marker) } };
}
