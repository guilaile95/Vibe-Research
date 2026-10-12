import assert from "node:assert/strict";
import test from "node:test";
import { emptyAssessment, emptyPattern, eligiblePatterns, localWeekSummary, reviewNumber, type PatternRevision, type PersonalEpisode } from "../src/lib/personalReview.ts";

test("unknown, zero and negative money remain distinct", () => {
  assert.equal(reviewNumber(null), "未知"); assert.equal(reviewNumber(NaN), "未知");
  assert.equal(reviewNumber(0), "0.00"); assert.equal(reviewNumber(-3), "-3.00");
});
test("new self assessment cannot claim verified knowledge", () => {
  const one = emptyAssessment(); one.violations.push("test");
  assert.deepEqual(emptyAssessment().violations, []);
  assert.equal(emptyAssessment().judgment, "unknown");
  assert.equal(emptyAssessment().stop_price, null);
  assert.equal(emptyPattern().entry_rule, "");
});
test("pattern effective windows use Shanghai day, never current version hindsight", () => {
  const patterns = [{ pattern_id: "one", revision: 1, effective_from: "2026-07-21", effective_until: "2026-07-23" }, { pattern_id: "one", revision: 2, effective_from: "2026-07-23", effective_until: null }] as PatternRevision[];
  assert.deepEqual(eligiblePatterns(patterns, "2026-07-20T15:59:59Z"), []);
  assert.equal(eligiblePatterns(patterns, "2026-07-20T16:00:00Z")[0].revision, 1);
  assert.equal(eligiblePatterns(patterns, "2026-07-22T16:00:00Z")[0].revision, 2);
  assert.deepEqual(eligiblePatterns(patterns, "invalid"), []);
});
test("local weekly stats exclude mixed/unknown money and enforce exclusive end", () => {
  const rows = [ { state: "CLOSED", closed_at: "2026-07-20T08:00:00Z", net_pnl: 0 }, { state: "CLOSED", closed_at: "2026-07-21T08:00:00Z", net_pnl: null }, { state: "MIXED_CAMPAIGN_UNSCORED", closed_at: "2026-07-22T08:00:00Z", net_pnl: 999 }, { state: "CLOSED", closed_at: "2026-07-27T00:00:00Z", net_pnl: 99 } ] as PersonalEpisode[];
  assert.deepEqual(localWeekSummary(rows, "2026-07-20T00:00:00Z", "2026-07-27T00:00:00Z"), { closed: 2, moneyScored: 1, net: 0 });
});

import { parsePersonalReview, parseSavedAssessment, parseSavedPattern, parseExcursion, parseBasisReceipt } from "../src/lib/personalReviewValidation.ts";
const summary = {requested:10,closed_count:0,insufficient_samples:true,money_scored:0,wins:0,losses:0,flat:0,win_rate_excluding_flat:null,net_pnl:null,self_assessed_count:0,self_reported_deviations:0,self_reported_violations:0};
const validView = () => ({schema_version:"personal-review.v1",privacy:"LOCAL_ONLY_EXCLUDED_FROM_MODEL_CONTEXT",as_of:"2026-07-28T00:00:00Z",data_time:null,trade_count:0,closed_episodes:[],diagnostics:[],windows:[10,20,50].map(n=>({...summary,requested:n})),patterns:[],risk:{open_episodes:[],equity_reference:null,equity_effective_at:null,equity_confirmation:"UNKNOWN",boundary:"SELF_REPORTED"},assessment_history:{},limitations:[]});
test("GET guards prevent malformed arrays, counters, histories and dates from entering JSX",()=>{
  assert.equal(parsePersonalReview(validView()).trade_count,0);
  for(const patch of [{windows:null},{windows:[summary]},{patterns:[{}]},{closed_episodes:[{}]},{assessment_history:{a:[{}]}},{as_of:"2026-07-25T12:00:00+01:60"},{as_of:"0000-07-25T12:00:00Z"},{risk:{}}]) assert.throws(()=>parsePersonalReview({...validView(),...patch}));
  assert.throws(()=>parsePersonalReview({...validView(),windows:[10,20,50].map(n=>({...summary,requested:n,wins:1}))}));
});
test("PUT acknowledgements require the exact intended content and revision",()=>{
  const content=emptyAssessment(), body={...content,revision:0};
  const response={revision:1,content,saved_at:"2026-07-28T00:00:00Z",stop_recorded_at:null,classification:"RETROSPECTIVE_SELF_ASSESSMENT"};
  assert.equal(parseSavedAssessment(response,body).revision,1);
  for(const bad of [{},{...response,revision:99},{...response,content:{...content,note:"different write"}},{...response,saved_at:null}]) assert.throws(()=>parseSavedAssessment(bad,body));
  assert.throws(()=>parseSavedPattern({revision:1},{...emptyPattern(),revision:0}));
});
test("excursion response rejects promoted exact MFE and malformed bound sources",()=>{
  const response={state:"NO_EVIDENCE",mfe_pct:null,mae_pct:null,raw_interior_high:null,raw_interior_low:null,boundary:"EXCLUDES_ENTRY_EXIT",reason:"NO_PROOF",source:null,adjusted_bound:null};
  assert.equal(parseExcursion(response).mfe_pct,null);
  assert.throws(()=>parseExcursion({...response,mfe_pct:2}));
  assert.throws(()=>parseExcursion({...response,adjusted_bound:{state:"INTERIOR_DAILY_ADJUSTED_BOUND"}}));
  assert.throws(()=>parseExcursion({...response,adjusted_bound:{state:"BASIS_ARCHIVE_INVALID",limitations:{},source:{provider_revision:{}}}}));
  assert.equal(parseExcursion({...response,adjusted_bound:{state:"BASIS_ARCHIVE_INVALID"}}).adjusted_bound?.state,"BASIS_ARCHIVE_INVALID");
});
test("factor receipt is bound to exact uploaded bytes and source identity",async()=>{
  const raw=JSON.stringify({code:"600000",provider_id:"synthetic",provider_revision:"v1",adjustment_basis_id:"anchor",raw_snapshot_id:"a".repeat(64),raw_artifact_sha256:"b".repeat(64),captured_at:"2026-07-25T00:00:00Z"});
  const hash=Buffer.from(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw))).toString("hex");
  const receipt={...JSON.parse(raw),capture_sha256:hash,from:"2026-07-21",through:"2026-07-24",sessions:4,evidence_status:"PROVIDER_ASSERTED_ARCHIVED_RESEARCH_NOT_PIT_OR_TOTAL_RETURN"};
  assert.equal((await parseBasisReceipt(receipt,raw)).capture_sha256,hash);
  await assert.rejects(()=>parseBasisReceipt({...receipt,capture_sha256:"c".repeat(64)},raw));
  await assert.rejects(()=>parseBasisReceipt({...receipt,provider_revision:"v2"},raw));
});
