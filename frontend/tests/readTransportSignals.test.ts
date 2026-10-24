import test from "node:test";
import assert from "node:assert/strict";
import { api } from "../src/lib/api.ts";
import { getWatchlist } from "../src/lib/decisionCockpit.ts";

test("all scoped read API wrappers forward the exact signal to fetch and preserve abort rejection", async () => {
 const original=globalThis.fetch;
 const seen:AbortSignal[]=[];
 globalThis.fetch=async (_input, init)=>{
  const signal=init?.signal;
  assert.ok(signal);
  seen.push(signal);
  return await new Promise<Response>((_resolve,reject)=>{
   const abort=()=>reject(new DOMException("Aborted","AbortError"));
   if(signal.aborted) abort();else signal.addEventListener("abort",abort,{once:true});
  });
 };
 try {
  const controller=new AbortController();
  const s=controller.signal;
  const reads=[
   api.valuation("600001",s),api.percentile("600001",s),api.financials("600001",s),
   api.announcements("600001",s),api.quote("600001",s),api.reportsWithCoverage("600001",s),
   api.news("600001",s),api.margin("600001",s),api.blockTrade("600001",s),
   api.holders("600001",s),api.dividend("600001",s),api.fundFlow("600001",s),
   api.dragonTiger("600001",s),api.lockup("600001",s),api.blocks("600001",s),
   api.hotConcepts("600001",s),api.investorQa("600001",s),api.finance("600001",s),
   api.info("600001",s),api.disclosure("600001",s),api.globalStock("AAPL",s),
   api.hkCashflow("00700",s),api.stockRelativeContext("600001",s),
   api.stockValuationContext("600001",s),api.topRisk("600001",120,s),
   api.kline("600001",4,60,s),api.technicalIndicators("600001","daily",120,s),getWatchlist(s),
  ];
  const outcomes=Promise.allSettled(reads);
  await new Promise(r=>setImmediate(r));
  assert.equal(seen.length,28);
  assert.ok(seen.every(signal=>signal===s));
  controller.abort();
  assert.ok((await outcomes).every(v=>v.status==="rejected" && v.reason.name==="AbortError"));
 } finally {globalThis.fetch=original;}
});
