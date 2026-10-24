import { credentialStatus, storedCredential } from './credential-generation.fixture.mjs';
import {isDeepStrictEqual} from 'node:util';
import {readFileSync} from 'node:fs';
import {createFixture} from './next-day-verification.fixture.mjs';
const load=name=>JSON.parse(readFileSync(new URL('../fixtures/'+name,import.meta.url),'utf8'));
export const startupGolden=load('extended-page-startup.golden.json');
export const marketGolden=load('extended-page-market.golden.json');
export const companyGolden=load('extended-public-research.golden.json');
export const failureGolden=load('extended-page-market-failure.golden.json');
export const missingGolden=load('extended-page-market-missing.golden.json');
export const CLOCK='2026-10-12T23:00:00Z', CUTOFF='2026-09-30';
export const subjects=[['US','AAPL'],['HK','00700'],['A','600000']];
export const researchGolden=Object.fromEntries(subjects.map(([market,symbol])=>[market,JSON.parse(readFileSync(new URL(`../../../backend/tests/fixtures/company_research/${market}-${symbol}.json`,import.meta.url),'utf8'))]));
researchGolden['US-failed']=JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/company_research/US-AAPL-failed-quote.json',import.meta.url),'utf8'));
export const syntheticLlm={provider:'deepseek',model:'synthetic',baseURL:'https://fixture.example',apiKey:'synthetic'};
export const syntheticStoredLlm=storedCredential(syntheticLlm);
const ancillary=['financials','reports','announcements','margin','block-trade','holders','dividend','fund-flow','dragon-tiger','lockup','blocks','hot-concepts','investor-qa','valuation/percentile','news','stock-relative-context','stock-valuation-context'];
export function createExtendedPageFixture(origin){
 const base=createFixture(origin,{withSealQuality:true,fullReview:true});
 const calls=[],violations=[];let next=null;const expectedPosts=[];
 const json=(data,status=200)=>({kind:'json',status,body:{data}});
 const deny=message=>{violations.push(message);return {kind:'deny'};};
 return {base,calls,violations,expectedPosts,expectResearch(market,action){expectedPosts.push({market,action});},setNext(value){next=structuredClone(value);},handle(url,method='GET',body){
  const u=new URL(url);if(u.origin!==origin)return deny('foreign origin');
  calls.push({method,path:u.pathname,search:u.search});
  if(u.pathname==='/api/ai/credential-status')return method==='GET'&&!u.search&&body===undefined?{kind:'json',status:200,body:credentialStatus(syntheticLlm)}:deny('credential preflight method/query/body');
  // Full-page initial renders observed in CI: before dr arrives, the journal
  // uses the fixed clock's Shanghai date; CN StockData mounts its event calendar.
  if(u.pathname==='/api/next-day-verification/2026-10-13')return method==='GET'&&u.search===''?{kind:'json',status:200,body:structuredClone(startupGolden.journal)}:deny('startup journal method/query');
  if(u.pathname==='/api/research-events')return method==='GET'&&u.search==='?security_code=600000'?{kind:'json',status:200,body:structuredClone(startupGolden.calendar)}:deny('startup calendar method/security/query');
  if(u.pathname.startsWith('/api/company-research/')){
   const expected=expectedPosts[0];if(method!=='POST'||u.search||!expected||u.pathname!=='/api/company-research/'+expected.action)return deny('unplanned research request');
   const g=researchGolden[expected.market],bundle=g.bundle;
   const wanted=expected.action==='capture'?{...g.subject,confirm_public_fetch:true,as_of:g.as_of}:{...g.subject,bundle_id:bundle.bundle_id,expected_bundle_sha256:bundle.bundle_sha256,confirm_model_calls:true,llm:syntheticStoredLlm};
   if(!isDeepStrictEqual(body,wanted))return deny('research body identity mismatch');
   expectedPosts.shift();return expected.action==='capture'?json(bundle):{kind:'stream',body:g.events.map(e=>JSON.stringify(e)).join('\n')+'\n'};
  }
  if(u.pathname.startsWith('/api/public-research/')){
   if(method!=='GET')return deny('archive mutation');
   let value;
   if(u.pathname==='/api/public-research/market-context')value=Object.entries(marketGolden).find(([day])=>u.search==='?as_of='+day)?.[1];
   if(u.pathname==='/api/public-research/company-inputs'){
    const found=subjects.find(([market,symbol])=>u.search===`?as_of=${CUTOFF}&market=${market}&symbol=${symbol}`);
    if(found)value=companyGolden[found[0]];
   }
   if(!value)return deny('unlisted archive identity '+u.pathname+u.search);
   const result=next||structuredClone(value);next=null;return json(result);
  }
  if(u.pathname==='/stock-data')return method==='GET'&&subjects.some(([,s])=>u.search==='?code='+s)?{kind:'static'}:deny('stock page identity');
  if(method==='GET'){
   const found=subjects.find(([,s])=>u.search==='?symbol='+s);
   if(found&&found[0]!=='A'&&u.pathname==='/api/global/stock')return json({code:found[1],name:'Synthetic '+found[1],market:found[0],quote:{price:150,change_pct:0,mcap:null,amount:null},metrics:null});
   if(found&&found[0]!=='A'&&u.pathname==='/api/global/hk/cashflow')return json(null,503);
   if(u.search==='?code=600000'){
    if(u.pathname==='/api/valuation')return json({name:'Synthetic 600000',code:'600000',price:150,mcap_yi:null,pe_ttm:null,pb:null,eps_26e:null,eps_27e:null,pe_26e:null,cagr_pct:null,peg:null,digest_years:null,analyst_count:0,dynamic_pe_used:false});
    if(ancillary.some(p=>u.pathname==='/api/'+p))return json(null,503);
   }
   if(u.pathname==='/api/market/top-risk'&&u.search==='?code=600000&days=120')return json(null,503);
   if(u.pathname==='/api/market/technical-indicators'&&u.search==='?code=600000&period=daily&days=120')return json(null,503);
  }
  return base.handle(url,method,body);
 }};
}
