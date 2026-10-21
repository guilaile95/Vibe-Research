import assert from 'node:assert/strict';
import test from 'node:test';
import { calculateReverseDcf, formatImpliedGrowth, requiredNumber, type ReverseDcfInput, type ReverseDcfResult } from '../src/lib/reverseDcf.ts';
function input(): ReverseDcfInput {
 const observation = (value: number, unit: string, currency = 'USD') => ({ value, unit, currency, source: 'Synthetic report', as_of: '2026-10-19' });
 return { market: 'US', symbol: 'TEST', industry: 'non_financial', industry_source: 'Synthetic industry', fcf_basis: 'annual_unlevered_fcff', price: observation(20,'currency_per_share'), fcff: observation(100,'million_currency'), net_debt: observation(200,'million_currency'), shares: observation(100,'million_shares','NONE'), assumptions: { wacc: .1, terminal_growth: .02, years: 5, growth_lower: -.9, growth_upper: 1, sensitivity_wacc: [.1], rationale: 'Manual synthetic assumptions' } };
}
function response(): ReverseDcfResult { return { schema_version:'reverse-dcf.v1',classification:'MODEL_IMPLIED_NOT_FORECAST',input_verification:'USER_ENTERED_UNVERIFIED',inputs:input(),evaluated_on:'2026-10-19',status:'SOLVED',reason_codes:[],implied_growth:.123456789,residual_ev:0,sensitivity:[{wacc:.1,status:'SOLVED',implied_growth:.123456789,residual_ev:0}] }; }
test('required values reject blank and nonfinite; zero is explicit',()=>{
 for(const value of ['',' ','Infinity','NaN','1e999']) assert.throws(()=>requiredNumber(value));
 assert.equal(requiredNumber('0'),0);
 assert.equal(formatImpliedGrowth(.123456789),'12.35%');
 assert.equal(formatImpliedGrowth(null),'不可计算');
 assert.equal(formatImpliedGrowth(Number.NaN),'不可计算');
 assert.equal(formatImpliedGrowth(-.123456789),'-12.35%');
});
test('only deterministic endpoint called, same signal and explicit assumptions',async t=>{
 let count=0;const signal=new AbortController().signal;
 t.mock.method(globalThis,'fetch',async(url,init)=>{count++;assert.equal(String(url),'/api/company-research/reverse-dcf');assert.equal(init?.signal,signal);assert.deepEqual(JSON.parse(String(init?.body)),input());return new Response(JSON.stringify({data:response()}));});
 const result=await calculateReverseDcf(input(),signal);assert.equal(result.implied_growth,.123456789);assert.equal(count,1);
});
for(const variant of ['identity','source','date','currency','unit','assumption','nan','missingScenario','wrongWacc','wrongStatus','forecast','unknownWithValue']) test(`response fails closed: ${variant}`,async t=>{
 const r=response();
 if(variant==='identity')r.inputs.symbol='OTHER';
 if(variant==='source')r.inputs.fcff.source='different';
 if(variant==='date')r.inputs.price.as_of='2026-01-01';
 if(variant==='currency')r.inputs.price.currency='HKD';
 if(variant==='unit')r.inputs.fcff.unit='currency';
 if(variant==='assumption')r.inputs.assumptions.wacc=.12;
 if(variant==='nan')r.implied_growth=NaN;
 if(variant==='missingScenario')r.sensitivity=[];
 if(variant==='wrongWacc')r.sensitivity[0].wacc=.2;
 if(variant==='wrongStatus')r.status='bogus' as never;
 if(variant==='forecast')r.classification='FORECAST' as never;
 if(variant==='unknownWithValue')r.status='UNKNOWN';
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:r})));
 await assert.rejects(calculateReverseDcf(input(),new AbortController().signal));
});
test('unknown and no-root remain null without substitution',async t=>{
 const r=response();r.status='UNKNOWN';r.implied_growth=null;r.residual_ev=null;r.sensitivity=[];r.reason_codes=['INDUSTRY_UNKNOWN'];
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:r})));
 assert.equal((await calculateReverseDcf(input(),new AbortController().signal)).implied_growth,null);
});
test('validation failure gives actionable field constraints without sending more requests',async t=>{
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:[{loc:['body','assumptions'],msg:'WACC must exceed terminal growth in every scenario'}]}),{status:422}));
 await assert.rejects(calculateReverseDcf(input(),new AbortController().signal),/assumptions: WACC must exceed terminal growth/);
});
