import type { AssessmentContent, AssessmentRevision, Excursion, PatternContent, PersonalReview } from "./personalReview.ts";
export class ReviewResponseError extends Error { constructor() { super("个人复查响应无法核验，请显式重新加载；当前草稿未清除"); } }
const fail = (): never => { throw new ReviewResponseError(); };
const object = (v: unknown): Record<string, any> => v !== null && typeof v === "object" && !Array.isArray(v) ? v as Record<string, any> : fail();
const text = (v: unknown, max = 2000): string => typeof v === "string" && v.length <= max ? v : fail();
const number = (v: unknown): number => typeof v === "number" && Number.isFinite(v) ? v : fail();
const integer = (v: unknown, max = 20000): number => Number.isInteger(number(v)) && (v as number) >= 0 && (v as number) <= max ? v as number : fail();
const flag = (v: unknown) => typeof v === "boolean" ? v : fail();
const list = (v: unknown, max = 20000): unknown[] => Array.isArray(v) && v.length <= max ? v : fail();
const nullableNumber = (v: unknown) => v === null ? null : number(v);
const nullableText = (v: unknown, max = 2000) => v === null ? null : text(v, max);
const enumValue = (v: unknown, values: string[]) => values.includes(text(v)) ? v : fail();
const instant = (v: unknown) => { const s = text(v, 40); if (!/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00)$/.test(s) || !Number.isFinite(Date.parse(s))) fail(); day(s.slice(0,10)); return s; };
const day = (v: unknown) => { const s = text(v, 10); if (s.startsWith("0000-") || !/^\d{4}-\d{2}-\d{2}$/.test(s) || !Number.isFinite(Date.parse(s)) || new Date(s).toISOString().slice(0,10) !== s) fail(); return s; };
const hex = (v: unknown, length = 64) => { const s = text(v, length); if (!new RegExp(`^[a-f0-9]{${length}}$`).test(s)) fail(); return s; };
const identity = (v: unknown) => { const s = text(v, 64); if (!/^[a-zA-Z0-9_-]{1,64}$/.test(s)) fail(); return s; };
function assessment(v: unknown) {
  const a = object(v); text(a.environment, 500); if (a.closing_board_rank !== null && (integer(a.closing_board_rank,100) < 1)) fail();
  enumValue(a.judgment,["unknown","correct","incorrect"]); enumValue(a.execution,["unknown","followed","deviated"]);
  list(a.violations,10).forEach(x=>{ if (!text(x,100).trim()) fail(); });
  if (a.stop_price !== null && number(a.stop_price) <= 0) fail();
  if ((a.pattern_id === null) !== (a.pattern_revision === null)) fail();
  if (a.pattern_id !== null) { identity(a.pattern_id); if(integer(a.pattern_revision)<1) fail(); }
  text(a.note,2000); return a;
}
function assessmentRevision(v: unknown) {
  const r=object(v); if(integer(r.revision)<1) fail(); assessment(r.content); instant(r.saved_at);
  if(r.stop_recorded_at!==null) instant(r.stop_recorded_at);
  enumValue(r.classification,["RETROSPECTIVE_SELF_ASSESSMENT"]); return r;
}
function patternContent(v: unknown) { const p=object(v); for(const field of ["name","setup","entry_rule","exit_rule","invalidation"]) if(!text(p[field],field==="name"?80:1000).trim()) fail(); return p; }
function summary(v: unknown) {
  const s=object(v); if(s.requested!==null) integer(s.requested,50); integer(s.closed_count); integer(s.money_scored); integer(s.wins); integer(s.losses); integer(s.flat);
  flag(s.insufficient_samples); nullableNumber(s.net_pnl); nullableNumber(s.win_rate_excluding_flat); integer(s.self_assessed_count); integer(s.self_reported_deviations); integer(s.self_reported_violations,200000);
  if(s.money_scored>s.closed_count || s.wins+s.losses+s.flat!==s.money_scored || s.self_assessed_count>s.closed_count || s.self_reported_deviations>s.self_assessed_count) fail();
  const rate=s.wins+s.losses?s.wins/(s.wins+s.losses):null;
  if(s.win_rate_excluding_flat!==rate || (s.net_pnl===null)!==(s.money_scored===0)) fail(); return s;
}
export function parsePersonalReview(value: unknown): PersonalReview {
  const v=object(value); enumValue(v.schema_version,["personal-review.v1"]); enumValue(v.privacy,["LOCAL_ONLY_EXCLUDED_FROM_MODEL_CONTEXT"]); instant(v.as_of); if(v.data_time!==null) instant(v.data_time); integer(v.trade_count,10000);
  list(v.windows,3).forEach(summary); if(JSON.stringify(v.windows.map((w:any)=>w.requested))!=="[10,20,50]") fail();
  list(v.closed_episodes,10000).forEach(raw=>{ const e=object(raw); hex(e.episode_id,32); text(e.code,6); text(e.name,64); list(e.trade_ids,10000).forEach(x=>hex(x,32)); instant(e.opened_at); instant(e.closed_at); integer(e.holding_calendar_days,100000); enumValue(e.state,["CLOSED","MIXED_CAMPAIGN_UNSCORED"]); number(e.gross_pnl); nullableNumber(e.net_pnl); nullableNumber(e.fees); enumValue(e.fee_coverage,["LEDGER_RECORDED","UNKNOWN"]); if(e.assessment!==null) assessmentRevision(e.assessment); list(e.formal_attributions,10000).forEach(raw=>{if(raw===null)return;const a=object(raw);text(a.decision_id,200);text(a.campaign_id,200);instant(a.decision_committed_at);instant(a.trade_executed_at);}); });
  list(v.diagnostics,10000).forEach(raw=>{const d=object(raw);nullableText(d.code,6);text(d.reason,100);});
  list(v.patterns).forEach(raw=>{const p=object(raw);identity(p.pattern_id);if(integer(p.revision)<1)fail();patternContent(p.content);instant(p.saved_at);day(p.effective_from);if(p.effective_until!==null)day(p.effective_until);summary(p.statistics);});
  const risk=object(v.risk);nullableNumber(risk.equity_reference);if(risk.equity_effective_at!==null)instant(risk.equity_effective_at);text(risk.equity_confirmation,100);text(risk.boundary,200);
  list(risk.open_episodes,10000).forEach(raw=>{const r=object(raw);text(r.code,6);integer(r.remaining_quantity,1e15);nullableNumber(r.entry_reference_stop_scenario);if(r.stop_recorded_at!==null)instant(r.stop_recorded_at);});
  const history=object(v.assessment_history);if(Object.keys(history).length>10000)fail();let revisions=0;
  for(const [id,items] of Object.entries(history)){hex(id,32);const rows=list(items);revisions+=rows.length;if(revisions>20000)fail();rows.forEach(assessmentRevision);}
  list(v.limitations,30).forEach(x=>text(x,2000));
  if(v.weekly!==undefined){const week=object(v.weekly);day(week.from);day(week.through_exclusive);summary(week.summary);}
  return value as PersonalReview;
}
const same = (a: unknown,b: unknown) => { const left=object(a),right=object(b); return Object.keys(left).length===Object.keys(right).length && Object.keys(left).every(k=>JSON.stringify(left[k])===JSON.stringify(right[k])); };
export function parseSavedAssessment(value: unknown, body: AssessmentContent & {revision:number}): AssessmentRevision {
  const r=assessmentRevision(value);const {revision,...content}=body;
  if(![Math.max(1,revision),revision+1].includes(r.revision)||!same(r.content,content))fail();
  return value as AssessmentRevision;
}
export function parseSavedPattern(value: unknown, body: PatternContent & {revision:number}): {revision:number} {
  const p=object(value);const {revision,...content}=body;
  if(![Math.max(1,revision),revision+1].includes(integer(p.revision))||!same(patternContent(p.content),content))fail();
  instant(p.saved_at);day(p.effective_from);enumValue(p.effective_rule,["NEXT_SHANGHAI_CALENDAR_DAY"]);return {revision:p.revision};
}
export function parseExcursion(value: unknown): Excursion {
  const v=object(value);text(v.state,100);if(v.mfe_pct!==null||v.mae_pct!==null)fail();nullableNumber(v.raw_interior_high);nullableNumber(v.raw_interior_low);text(v.boundary,200);text(v.reason,200);
  if(v.source!==null){const s=object(v.source);day(s.as_of);instant(s.fetched_at);integer(s.sessions,1000);enumValue(s.adjustment,["UNADJUSTED"]);}
  if(v.adjusted_bound!==null){const a=object(v.adjusted_bound);enumValue(a.state,["BASIS_ARCHIVE_INVALID","INTERIOR_DAILY_ADJUSTED_BOUND"]);if(a.state==="BASIS_ARCHIVE_INVALID"&&Object.keys(a).some(k=>k!=="state"))fail();if(a.state==="INTERIOR_DAILY_ADJUSTED_BOUND"){number(a.bounded_mfe_pct);number(a.bounded_mae_pct);number(a.adjusted_entry_reference);integer(a.interior_sessions,1000);text(a.limitations,2000);const source=object(a.source);instant(source.captured_at);instant(source.archived_at);text(source.provider_revision,120);text(source.adjustment_basis_id,120);hex(source.capture_sha256);}}
  return value as Excursion;
}
export type BasisReceipt = { capture_sha256:string; code:string; provider_id:string; provider_revision:string; adjustment_basis_id:string; from:string; through:string; sessions:number; evidence_status:string };
export async function parseBasisReceipt(value: unknown, raw: string): Promise<BasisReceipt> {
  const r=object(value);hex(r.capture_sha256);text(r.code,6);text(r.provider_id,120);text(r.provider_revision,120);text(r.adjustment_basis_id,120);day(r.from);day(r.through);if(integer(r.sessions,1000)<1)fail();enumValue(r.evidence_status,["PROVIDER_ASSERTED_ARCHIVED_RESEARCH_NOT_PIT_OR_TOTAL_RETURN"]);hex(r.raw_snapshot_id);hex(r.raw_artifact_sha256);instant(r.captured_at);
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw));
  const hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");if(hash!==r.capture_sha256)fail();
  const capture=object(JSON.parse(raw));for(const field of ["code","provider_id","provider_revision","adjustment_basis_id","raw_snapshot_id","raw_artifact_sha256","captured_at"])if(r[field]!==capture[field])fail();
  return value as BasisReceipt;
}
