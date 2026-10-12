import test from 'node:test';
import assert from 'node:assert/strict';
import {createFixture,DAY,HISTORY_DAYS} from './e2e/next-day-verification.fixture.mjs';
import {ancillaryReply,ANCILLARY_TRADE_DATE,realRouteAllowed} from './e2e/final-families.fixture.mjs';
const origin='http://127.0.0.1:18761',path='/api/shortline-review/versions';
test('segmented version fixtures permit only exact expected date GETs',()=>{
 for(const day of [DAY,...HISTORY_DAYS]){
  const f=createFixture(origin,{withSealQuality:true,fullReview:true});
  assert.deepEqual(f.handle(origin+path+`?trade_date=${day}&mode=daily`).body,{data:[]});
 }
 const query=`?trade_date=${ANCILLARY_TRADE_DATE}&mode=daily`;
 assert.deepEqual(ancillaryReply('GET',path,query),{data:[]});
 for(const method of ['POST','PUT','PATCH','DELETE','HEAD']){
  assert.equal(ancillaryReply(method,path,query),null);
  assert.equal(createFixture(origin,{withSealQuality:true}).handle(origin+path+`?trade_date=${DAY}&mode=daily`,method).kind,'deny');
 }
 for(const suffix of ['',`?trade_date=${DAY}`,`?trade_date=${DAY}&mode=weekly`,`?trade_date=${DAY}&mode=daily&mode=daily`,`?trade_date=${DAY}&mode=daily&refresh=true`,`?trade_date=2026-01-01&mode=daily`])assert.equal(createFixture(origin,{withSealQuality:true}).handle(origin+path+suffix).kind,'deny');
 for(const search of ['',query+'&mode=daily',query+'&root=/tmp',query.replace('daily','weekly'),query.replace('10-08','10-09')])assert.equal(ancillaryReply('GET',path,search),null);
 assert.equal(realRouteAllowed('GET',path,'history-late-success'),false);
 assert.equal(createFixture(origin,{withSealQuality:true}).handle(origin+path+`?trade_date=${HISTORY_DAYS[0]}&mode=daily`).kind,'deny');
});
