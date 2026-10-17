import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { comparisonRefs, generateComparison, parseComparisonRecord, readComparisonBundles, readComparisonBundle, readComparisonRuns, type ComparisonRecord } from '../src/lib/companyComparison.ts';
const golden = JSON.parse(readFileSync(new URL('../../backend/tests/fixtures/company_comparison/US-AAPL--HK-00700.json', import.meta.url), 'utf8'));
const bundles = golden.bundles;
const refs = comparisonRefs(bundles), day = golden.request.as_of, H = 'b'.repeat(64), I = golden.record.run_id;
const llm = golden.request.llm;
function record(): ComparisonRecord { return structuredClone(golden.record); }
const start = () => ({ type: 'run_started', run_id: I, pair_sha256: golden.record.pair_sha256, subjects: refs, as_of: day, max_model_calls: 1 });
test('qualified pair context accepts production bundle fixtures without inferring comparability', () => { assert.equal(parseComparisonRecord(record()).comparability, 'NOT_ESTABLISHED'); });
for (const kind of ['crossCitation','missingCitation','duplicateCitation','wrongSubject','wrongHash','ranked','verifiedUnits','extra','yearZero','finishedBeforeStart','failedWithOutput','nonArray']) test(`record rejects ${kind}`, () => {
  const r: any = record();
  if (kind === 'crossCitation') r.output.subjects[0].citations[0].symbol = bundles[1].subject.symbol;
  if (kind === 'missingCitation') r.output.subjects[0].citations = [];
  if (kind === 'duplicateCitation') r.output.subjects[0].citations.push(r.output.subjects[0].citations[0]);
  if (kind === 'wrongSubject') r.evidence[1].symbol = 'WRONG';
  if (kind === 'wrongHash') r.subjects[0].expected_bundle_sha256 = 'bad';
  if (kind === 'ranked') r.numeric_ranking = 'WINNER';
  if (kind === 'verifiedUnits') r.evidence[0].sources[0].units = 'CNY';
  if (kind === 'extra') r.extra = true;
  if (kind === 'yearZero') r.started_at = '0000-01-01T00:00:00Z';
  if (kind === 'finishedBeforeStart') r.finished_at = '2020-01-01T00:00:00Z';
  if (kind === 'failedWithOutput') { r.status = 'FAILED'; delete r.result_sha256; }
  if (kind === 'nonArray') r.evidence = {};
  assert.throws(() => parseComparisonRecord(r));
});
for (const kind of ['ok','truncated','duplicate','wrongPair','wrongDate','wrongBudget','crossCitation','cancelled']) test(`one exact bounded stream: ${kind}`, async t => {
  const controller = new AbortController(); const events: any[] = [start(), { type: 'done', record: record() }];
  if (kind === 'truncated') events.pop(); if (kind === 'duplicate') events.push(events[1]);
  if (kind === 'wrongPair') events[1].record.pair_sha256 = 'e'.repeat(64);
  if (kind === 'wrongDate') events[0].as_of = '2026-09-29'; if (kind === 'wrongBudget') events[0].max_model_calls = 2;
  if (kind === 'crossCitation') events[1].record.output.subjects[0].citations[0].symbol = bundles[1].subject.symbol;
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async (url, init) => { calls++; assert.equal(String(url), '/api/company-comparison/generate'); assert.equal(init?.method, 'POST'); const body = JSON.parse(String(init?.body)); assert.deepEqual(body.subjects, refs); assert.equal(body.as_of, day); assert.equal(body.confirm_model_calls, true); if (kind === 'cancelled') controller.abort(); return new Response(events.map(e => JSON.stringify(e)).join('\n') + '\n'); });
  if (kind === 'ok') assert.equal((await generateComparison(bundles, day, llm, controller.signal)).run_id, I);
  else await assert.rejects(generateComparison(bundles, day, llm, controller.signal));
  assert.equal(calls, 1);
});
test('invalid cutoff, same identity and CLI runtime fail before network', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('OUTBOUND_FORBIDDEN'); });
  await assert.rejects(generateComparison([bundles[0], bundles[0]], day, llm, new AbortController().signal), /不同股票/);
  await assert.rejects(generateComparison(bundles, '2026-09-29', llm, new AbortController().signal), /截止日/);
  await assert.rejects(generateComparison(bundles, day, { ...llm, provider: 'cli-codex' as any }, new AbortController().signal), /仅支持 API/);
});
test('selector and readback are exact subject/date/hash bound', async t => {
  const b = bundles[0], choice = { ...b.subject, bundle_id: b.bundle_id, bundle_sha256: b.bundle_sha256, archive_cutoff: day, captured_at: b.captured_at, available_source_count: 1, missing_source_count: 1, limitations: ['synthetic'] };
  const calls: string[] = []; t.mock.method(globalThis, 'fetch', async url => { calls.push(String(url)); return new Response(JSON.stringify({ data: String(url).includes('/bundles?') ? [choice] : b })); });
  assert.deepEqual(await readComparisonBundles(b.subject, day, new AbortController().signal), [choice]);
  assert.equal((await readComparisonBundle(choice, new AbortController().signal)).bundle_id, b.bundle_id);
  assert.deepEqual(calls, [`/api/company-comparison/bundles?market=US&symbol=AAPL&as_of=${day}`, `/api/company-research/bundles/${b.bundle_id}`]);
  await assert.rejects(readComparisonBundle({ ...choice, bundle_sha256: H }, new AbortController().signal), /版本/);
});

test('microsecond timestamp ordering rejects reversed submilliseconds', () => {
 const r = record(); r.started_at='2026-10-13T00:00:00.000002Z';r.finished_at='2026-10-13T00:00:00.000001Z';
 assert.throws(()=>parseComparisonRecord(r));
 r.finished_at='2026-10-13T00:00:00.000003Z';assert.equal(parseComparisonRecord(r),r);
});
test('output UTF-8 cap rejects oversized nonASCII within individual scalar limits', () => {
 const r=record(); r.output!.subjects.forEach(s=>{s.summary='测'.repeat(3400);});
 assert.throws(()=>parseComparisonRecord(r));
});
test('same bundle ID, unavailable ledger and false source provenance are rejected',()=>{
 for(const mutate of [
  (r:any)=>{r.subjects[1].bundle_id=r.subjects[0].bundle_id;},
  (r:any)=>{r.evidence[0].sources.forEach((s:any)=>{s.status='MISSING';});},
  (r:any)=>{r.evidence[0].sources[0].fixture=true;r.evidence[0].sources[0].source='other';},
  (r:any)=>{r.model.provider='cli-codex';},
  (r:any)=>{r.output.subjects[0].caveats=[];},
  (r:any)=>{r.as_of='2026-12-31';},
 ]){const r=record();mutate(r);assert.throws(()=>parseComparisonRecord(r));}
});
test('duplicate history run IDs fail closed',async t=>{
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:[record(),record()]})));
 await assert.rejects(readComparisonRuns(new AbortController().signal),/重复/);
});
for(const field of ['provider','name'])test('done model metadata binds requested '+field,async t=>{
 const r=record();r.model[field as 'provider'|'name']='different';
 t.mock.method(globalThis,'fetch',async()=>new Response([start(),{type:'done',record:r}].map(e=>JSON.stringify(e)).join('\n')+'\n'));
 await assert.rejects(generateComparison(bundles,day,llm,new AbortController().signal),/回执不匹配/);
});
test('selector rejects capture before common cutoff',async t=>{
 const choice={...golden.bundle_lists[0][0],captured_at:'2026-09-29T00:00:00Z'};
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:[choice]})));
 await assert.rejects(readComparisonBundles(bundles[0].subject,day,new AbortController().signal),/截止日/);
});

test('total-record UTF-8 bound rejects large ledger even with individually bounded fields',()=>{
 const r=record();
 r.evidence.forEach(e=>{
  const source=e.sources.find(s=>s.status==='AVAILABLE')!;
  e.sources=Array.from({length:20},(_,i)=>({...source,evidence_id:('e'+i).padEnd(100,'x'),source:'\u0000'.repeat(200),fixture:false,source_as_of:'2026-09-30T00:00:00.123456Z',captured_at:'2026-10-01T00:00:00.123456Z'}));
 });
 r.model={provider:'\u0000'.repeat(200),name:'\u0000'.repeat(200)};
 r.output!.subjects.forEach((s,i)=>{
  s.summary='Draft';s.missingness=[];s.caveats=['Unverified'];
  s.citations=[{market:s.market,symbol:s.symbol,evidence_id:r.evidence[i].sources[0].evidence_id}];
 });
 const size=(v:unknown)=>new TextEncoder().encode(JSON.stringify(v)).byteLength;
 while(size(r.output)<15900)r.output!.subjects[0].summary+='\u0000';
 assert.ok(r.output!.subjects[0].summary.length<=3500);
 assert.ok(size(r.output)<=16000);
 assert.ok(size(r)>80*1024,'negative fixture must exceed total record cap');
 assert.throws(()=>parseComparisonRecord(r));
});

test('history page sends ordered pair and cutoff before limit and rejects mixed history',async t=>{
 const {readComparisonRunPage}=await import('../src/lib/companyComparison.ts');
 let data:any={records:[record()],next_cursor:'51'};
 t.mock.method(globalThis,'fetch',async url=>{assert.equal(String(url),`/api/company-comparison/runs?first_market=US&first_symbol=AAPL&second_market=HK&second_symbol=00700&as_of=${day}&before=100`);return new Response(JSON.stringify({data}));});
 const read=()=>readComparisonRunPage(bundles[0].subject,bundles[1].subject,day,new AbortController().signal,'100');
 assert.equal((await read()).records[0].run_id,I);
 data.next_cursor='100';await assert.rejects(read());
 data={records:[record(),record()],next_cursor:null};await assert.rejects(read());
 data={records:[record()],next_cursor:null};data.records[0].as_of='2026-09-29';await assert.rejects(read());
});

for(const category of ['TIMEOUT','UPSTREAM','OUTPUT_INVALID','PERSISTENCE','secret-in-category','wrong-run']) test(`failure category and run ownership ${category}`,async t=>{
 const event={type:'error',run_id:category==='wrong-run'?'f'.repeat(32):I,code:'COMPARISON_INCOMPLETE',category:category==='wrong-run'?'TIMEOUT':category,message:'https://private.example/secret'};
 let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return new Response([start(),event].map(e=>JSON.stringify(e)).join('\n')+'\n');});
 await assert.rejects(generateComparison(bundles,day,llm,new AbortController().signal),e=>{
   assert.doesNotMatch(String(e),/private.example|secret-in-category|ffffffff/);
   assert.match(String(e),/可能已产生模型费用/);
   if(!['secret-in-category','wrong-run'].includes(category)){assert.match(String(e),new RegExp(category));assert.ok(String(e).includes(I));}
   return true;
 });assert.equal(calls,1);
});

test('exact frozen citation read binds subject bundle hash ledger and never calls generation',async t=>{
 const {readComparisonEvidence}=await import('../src/lib/companyComparison.ts');
 let response=structuredClone(bundles[0]);let calls=0;
 t.mock.method(globalThis,'fetch',async(url,init)=>{calls++;assert.equal(String(url),`/api/company-research/bundles/${bundles[0].bundle_id}`);assert.ok(!init?.method || init.method==='GET');return new Response(JSON.stringify({data:response}));});
 const source=golden.record.output.subjects[0].citations[0].evidence_id;
 assert.deepEqual(await readComparisonEvidence(record(),0,source,new AbortController().signal),bundles[0]);
 await assert.rejects(readComparisonEvidence(record(),0,'not_in_this_bundle',new AbortController().signal));assert.equal(calls,1);
 for(const field of ['bundle_sha256','bundle_id']){
  response=structuredClone(bundles[0]);response[field]='f'.repeat(field==='bundle_id'?32:64);
  await assert.rejects(readComparisonEvidence(record(),0,source,new AbortController().signal));
 }
 response=structuredClone(bundles[1]);await assert.rejects(readComparisonEvidence(record(),0,source,new AbortController().signal));
 response=structuredClone(bundles[0]);const changed=record();changed.evidence[0].sources[0].payload_sha256='a'.repeat(64);
 await assert.rejects(readComparisonEvidence(changed,0,source,new AbortController().signal),/历史回执/);
 const stop=new AbortController();stop.abort();await assert.rejects(readComparisonEvidence(record(),0,source,stop.signal));
});
test('legacy records retain unknown historical limits; new limits cannot imply observed usage',()=>{
 const legacy=record();delete legacy.limits;assert.equal(parseComparisonRecord(legacy).limits,undefined);
 for(const limits of [{max_model_calls:2,max_seconds:90,max_output_tokens:2500},{max_model_calls:1,max_seconds:91,max_output_tokens:2500},{max_model_calls:1,max_seconds:90,max_output_tokens:3000},{max_model_calls:1,max_seconds:90,max_output_tokens:2500,actual_cost:0}]){
  assert.throws(()=>parseComparisonRecord({...record(),limits} as any));
 }
});
