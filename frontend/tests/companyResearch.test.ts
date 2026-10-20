import assert from 'node:assert/strict';
import test, { type TestContext } from 'node:test';
import { captureCompanyResearch, generateCompanyResearch, parseResearchBundle, parseResearchRecord, RESEARCH_STAGES, researchNote, type ResearchBundle, type ResearchStage } from '../src/lib/companyResearch.ts';
const H='a'.repeat(64), I='b'.repeat(32), R='c'.repeat(32);
const bundle: ResearchBundle={schema_version:'company_research.v1',classification:'PUBLIC_ADAPTER_INPUT_UNVERIFIED',bundle_id:I,bundle_sha256:H,subject:{market:'A',symbol:'600519'},captured_at:'2026-10-12T00:00:00Z',limitations:['fixture'],sources:[{evidence_id:'facts',source:'fixture',status:'AVAILABLE',captured_at:'2026-10-12T00:00:00Z',source_as_of:null,payload_sha256:H,stages:[...RESEARCH_STAGES],payload:{value:0},scope:'fixture'}]};
const llm={provider:'deepseek' as const,model:'fixture',baseURL:'https://fixture.example',apiKey:'synthetic'};
function events(){const stages:ResearchStage[]=[];const rows:unknown[]=[{type:'run_started',run_id:R,bundle_sha256:H,subject:bundle.subject,max_model_calls:6}];for(const stage of RESEARCH_STAGES){rows.push({type:'stage_started',run_id:R,stage});const output={stage,summary:'Synthetic only',evidence_ids:['facts'],gaps:['not verified'],output_sha256:H,input_bundle_sha256:H,previous_stage_hashes:stages.map(x=>x.output_sha256),source_gaps:[],classification:'NON_AUTHORITATIVE_AI_DRAFT',numeric_claim_verification:'NOT_EVALUATED'};stages.push(output);rows.push({type:'stage_done',run_id:R,stage,output});}rows.push({type:'done',record:{schema_version:'company_research.v1',run_id:R,bundle_id:I,bundle_sha256:H,subject:bundle.subject,status:'COMPLETED',started_at:'2026-10-12T00:00:00Z',finished_at:'2026-10-12T00:00:00Z',stages,completed_stage_count:6,model:{provider:'fixture',name:'fixture'},result_sha256:H,classification:'NON_AUTHORITATIVE_AI_DRAFT',numeric_claim_verification:'NOT_EVALUATED'}});return rows;}
function mockStream(t: TestContext, rows: unknown[], suffix=''){t.mock.method(globalThis,'fetch',async(url,init)=>{assert.equal(String(url),'/api/company-research/generate');const body=JSON.parse(String(init?.body));assert.equal(body.expected_bundle_sha256,H);return new Response(rows.map(x=>JSON.stringify(x)).join('\n')+'\n'+suffix);});}
test('capture is explicit and rejects wrong identity or malformed source receipts',async t=>{t.mock.method(globalThis,'fetch',async(url,init)=>{assert.equal(String(url),'/api/company-research/capture');assert.equal(JSON.parse(String(init?.body)).confirm_public_fetch,true);return new Response(JSON.stringify({data:bundle}));});assert.deepEqual(await captureCompanyResearch(bundle.subject,new AbortController().signal),bundle);assert.throws(()=>parseResearchBundle({...bundle,subject:{market:'HK',symbol:'00700'}},bundle.subject));assert.throws(()=>parseResearchBundle({...bundle,bundle_sha256:'wrong'},bundle.subject));});
test('six ordered stages use one bundle; only terminal report can be saved',async t=>{mockStream(t,events());const progress:string[]=[];const result=await generateCompanyResearch(bundle,llm,(stage,out)=>{if(out)progress.push(stage);},new AbortController().signal);assert.deepEqual(progress,[...RESEARCH_STAGES]);assert.match(researchNote(result),/数字与事实未自动核验/);assert.doesNotMatch(researchNote(result),/apiKey|synthetic/);});
for(const kind of ['missingdone','duplicate','wrongbundle','unknowncitation','malformedline','partiallastline']){test(`fail closed stream: ${kind}`,async t=>{const rows=events() as any[];let suffix='';if(kind==='missingdone')rows.pop();if(kind==='duplicate')rows.splice(2,0,rows[1]);if(kind==='wrongbundle')rows[0].bundle_sha256='d'.repeat(64);if(kind==='unknowncitation')rows[2].output.evidence_ids=['missing'];if(kind==='malformedline')suffix='broken json\n';if(kind==='partiallastline')suffix='{}';mockStream(t,rows,suffix);await assert.rejects(generateCompanyResearch(bundle,llm,()=>{},new AbortController().signal));});}
test('cancellation propagates before result success',async t=>{mockStream(t,events());const controller=new AbortController();controller.abort();await assert.rejects(generateCompanyResearch(bundle,llm,()=>{},controller.signal));});

for (const captured_at of ['bad','2026-10-12T00:00:00+01:60','2026-02-30T00:00:00Z','20261012T00:00:00Z']) {
 test(`strict bundle timestamp ${captured_at}`,()=>assert.throws(()=>parseResearchBundle({...bundle,captured_at},bundle.subject)));
}
test('bundle classification, source cap and subject grammar are strict',()=>{
 assert.throws(()=>parseResearchBundle({...bundle,classification:'VERIFIED'},bundle.subject));
 assert.throws(()=>parseResearchBundle({...bundle,sources:Array.from({length:21},(_,i)=>({...bundle.sources[0],evidence_id:`facts_${i}`}))},bundle.subject));
 assert.throws(()=>parseResearchBundle({...bundle,subject:{market:'A',symbol:'bad'}},{market:'A',symbol:'bad'}));
});

for (const variant of ['badsubject','badtime','missingfinished','reversed','runningcount','extrakey','yearzero']) {
 test(`restore record fails closed: ${variant}`,()=>{
  const record=(events().at(-1) as any).record;
  if(variant==='badsubject')record.subject={market:'HK',symbol:'bad'};
  if(variant==='badtime')record.started_at='20261012T120000+0000';
  if(variant==='missingfinished'){record.status='FAILED';record.stages=[];delete record.result_sha256;delete record.finished_at;}
  if(variant==='reversed')record.finished_at='2000-01-01T00:00:00Z';
  if(variant==='runningcount'){record.status='RUNNING';record.stages=[];delete record.result_sha256;delete record.finished_at;}
  if(variant==='extrakey')record.unknown=true;
  if(variant==='yearzero')record.started_at='0000-01-01T00:00:00Z';
  assert.throws(()=>parseResearchRecord(record));
 });
}

test('restore preserves microsecond timestamp ordering',()=>{const row=(events().at(-1) as any).record;row.started_at='2026-10-12T00:00:00.000002Z';row.finished_at='2026-10-12T00:00:00.000001Z';assert.throws(()=>parseResearchRecord(row));});

test('explicit archive cutoff travels unchanged and invalid cutoff never requests',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',async(url,init)=>{calls++;assert.equal(JSON.parse(String(init?.body)).as_of,'2026-09-30');return new Response(JSON.stringify({data:bundle}));});
 await captureCompanyResearch(bundle.subject,new AbortController().signal,'2026-09-30');
 for(const value of ['','2026-02-30','2099-01-01'])await assert.rejects(captureCompanyResearch(bundle.subject,new AbortController().signal,value));
 assert.equal(calls,1);
});

// Saved history uses only the immutable bundle GET and reconciles the saved run.
test('saved evidence read preserves frozen payload and never recaptures or generates', async t => {
 const { readCompanyResearchEvidence } = await import('../src/lib/companyResearch.ts');
 const record = (events().at(-1) as any).record;
 const signal = new AbortController().signal;
 let calls = 0;
 t.mock.method(globalThis, 'fetch', async (url, init) => {
  calls++; assert.equal(String(url), `/api/company-research/bundles/${I}`);
  assert.equal(init?.method ?? 'GET', 'GET'); assert.equal(init?.signal, signal);
  return new Response(JSON.stringify({data:bundle}));
 });
 assert.deepEqual(await readCompanyResearchEvidence(record, signal), bundle);
 assert.equal(calls, 1);
});
for (const variant of ['id','hash','subject','malformedhash','malformedsource','citation','sourcegap','null','transport']) {
 test(`saved evidence fails closed: ${variant}`, async t => {
  const { readCompanyResearchEvidence } = await import('../src/lib/companyResearch.ts');
  const record = (events().at(-1) as any).record;
  let returned:any = structuredClone(bundle);
  if (variant === 'id') returned.bundle_id = 'd'.repeat(32);
  if (variant === 'hash') returned.bundle_sha256 = 'd'.repeat(64);
  if (variant === 'subject') returned.subject = {market:'US',symbol:'AAPL'};
  if (variant === 'malformedhash') returned.sources[0].payload_sha256 = 'corrupt';
  if (variant === 'malformedsource') returned.sources[0].captured_at = 'bad';
  if (variant === 'citation') record.stages[0].evidence_ids = ['absent'];
  if (variant === 'sourcegap') record.stages[0].source_gaps = [{evidence_id:'facts',status:'MISSING'}];
  if (variant === 'null') returned = null;
  t.mock.method(globalThis, 'fetch', async () => variant === 'transport' ? new Response('',{status:500}) : new Response(JSON.stringify({data:returned})));
  await assert.rejects(readCompanyResearchEvidence(record, new AbortController().signal));
 });
}
test('saved evidence rejects invalid record before fetch and aborted completion after fetch', async t => {
 const { readCompanyResearchEvidence } = await import('../src/lib/companyResearch.ts');
 let calls = 0;
 const controller = new AbortController();
 t.mock.method(globalThis,'fetch',async()=>{calls++;controller.abort();return new Response(JSON.stringify({data:bundle}));});
 const record = (events().at(-1) as any).record;
 await assert.rejects(readCompanyResearchEvidence({...record,bundle_id:'../capture'},new AbortController().signal));
 assert.equal(calls,0);
 await assert.rejects(readCompanyResearchEvidence(record,controller.signal));
 assert.equal(calls,1);
 await assert.rejects(readCompanyResearchEvidence(record,controller.signal));
 assert.equal(calls,1);
});

test('subject history query preserves cursor and accepts explicit diagnostics',async t=>{
 const {readCompanyResearchPage}=await import('../src/lib/companyResearch.ts');
 const row=(events().at(-1) as any).record;
 const page={records:[row],diagnostics:[{run_id:'e'.repeat(32),status:'CORRUPTED_OR_UNSUPPORTED'}],unassigned_corrupt_count:2,next_cursor:'bound-cursor'};
 t.mock.method(globalThis,'fetch',async(url,init)=>{const parsed=new URL(String(url),'https://fixture.example');assert.equal(parsed.pathname,'/api/company-research/history');assert.equal(parsed.searchParams.get('market'),'A');assert.equal(parsed.searchParams.get('symbol'),'600519');assert.equal(parsed.searchParams.get('cursor'),'old+cursor=');return new Response(JSON.stringify({data:page}));});
 assert.deepEqual(await readCompanyResearchPage(bundle.subject,new AbortController().signal,'old+cursor='),page);
});
for(const variant of ['wrongsubject','duplicate','invalidrecord','diagnostic','count','cursor','overlap'])test(`subject history rejects ${variant}`,async t=>{
 const {readCompanyResearchPage}=await import('../src/lib/companyResearch.ts');const row=(events().at(-1) as any).record;
 const page:any={records:[row],diagnostics:[],unassigned_corrupt_count:0,next_cursor:null};
 if(variant==='wrongsubject')row.subject={market:'US',symbol:'AAPL'};
 if(variant==='duplicate')page.records.push(row);
 if(variant==='invalidrecord')row.model.provider='';
 if(variant==='diagnostic')page.diagnostics=[{run_id:null,status:'VALID'}];
 if(variant==='count')page.unassigned_corrupt_count=-1;
 if(variant==='cursor')page.next_cursor=12;
 if(variant==='overlap')page.diagnostics=[{run_id:row.run_id,status:'CORRUPTED_OR_UNSUPPORTED'}];
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:page})));
 await assert.rejects(readCompanyResearchPage(bundle.subject,new AbortController().signal));
});

test('native envelope explicitly binds request without claiming provider identity',()=>{
 const row={...bundle.sources[0],source:'astock.announcements',payload:{schema_version:'company-native-request.v1',adapter:'astock.announcements',requested_subject:bundle.subject,identity_basis:'ADAPTER_REQUEST_CONTRACT_NOT_PROVIDER_IDENTITY',payload:[{title:'Synthetic',date:'2026-10-12'}]}};
 assert.deepEqual(parseResearchBundle({...bundle,sources:[row]},bundle.subject).sources[0],row);
 assert.throws(()=>parseResearchBundle({...bundle,sources:[{...row,payload:{...row.payload,requested_subject:{market:'US',symbol:'AAPL'}}}]},bundle.subject));
 assert.throws(()=>parseResearchBundle({...bundle,sources:[{...row,payload:{...row.payload,identity_basis:'VERIFIED'}}]},bundle.subject));
});
