import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { isCohortIdentityForDate } from "../src/lib/cohortIdentity.ts";
const day = "2026-07-30", previous = "2026-07-29";
const evidence = d => ({ trade_date:d,source_ids:["eastmoney_getTopicZTPool"],fetched_at:`${d}T08:00:00Z`,snapshot_at:`${d}T08:00:00Z`,stored_at:"2026-07-31T01:00:00Z",envelope_sha256:"a".repeat(64),row_count:1 });
const reply = () => ({ schema_version:"archived-cohort-identity.v0.1",trade_date:day,previous_trade_date:previous,status:"normal",reason_codes:[],message:"fixture",selection_mode:"CURRENT_STORED_POSTHOC",point_in_time_claim:"NONE",research_only:true,evidence:{previous:evidence(previous),current:evidence(day)},projection:{rows:[{stock_code:"600001",previous_source_code:"600001",current_source_code:null,previous_boards:1,current_boards:null,present_today:false}]}});
test("date/provenance guard accepts evidence navigation without inferring zero",()=>{
 assert.equal(isCohortIdentityForDate(reply(),day),true);
 assert.equal(isCohortIdentityForDate(reply(),previous),false);
 for(const mutate of [v=>v.point_in_time_claim="PROVEN",v=>v.research_only=false,v=>v.evidence.previous.row_count=2,v=>{v.evidence.previous.row_count=0;v.projection.rows=[]},v=>v.projection.rows[0].current_boards=0,v=>v.projection.rows[0].present_today=true,v=>v.evidence.current.envelope_sha256="bad",v=>v.projection.rows.push(v.projection.rows[0])]) {
  const v=reply();mutate(v);assert.equal(isCohortIdentityForDate(v,day),false);
 }
 const v=reply();Object.assign(v,{status:"unavailable",projection:null,evidence:null});assert.equal(isCohortIdentityForDate(v,day),true);
 v.projection={rows:[]};assert.equal(isCohortIdentityForDate(v,day),false);
});
test("production DailyReview binds both real date contexts and cancellation",()=>{
 const page=readFileSync(new URL("../src/pages/DailyReview.tsx",import.meta.url),"utf8");
 assert.ok(page.includes('<CohortIdentityCard tradeDate={dr?.trade_date ?? null} />'));
 assert.ok(page.includes('<CohortIdentityCard tradeDate={snap.trade_date ?? null} />'));
 const card=readFileSync(new URL("../src/components/dailyReview/CohortIdentityCard.tsx",import.meta.url),"utf8");
 assert.ok(card.includes('controller.signal.aborted || generation.current !== request'));
 assert.ok(card.includes('state?.date === tradeDate'));
 assert.ok(card.includes('return () => controller.abort()'));
 assert.ok(card.includes('今日所选名单未出现'));
 assert.ok(!card.includes('effective_height'));
});
