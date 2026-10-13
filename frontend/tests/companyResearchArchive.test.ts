import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseResearchBundle, parseResearchRecord, generateCompanyResearch } from '../src/lib/companyResearch.ts';
const llm={provider:'deepseek' as const,model:'fixture',baseURL:'https://fixture.example',apiKey:'synthetic'};
const fixtures=['A-600000','US-AAPL','HK-00700','US-AAPL-failed-quote'].map(name=>JSON.parse(readFileSync(new URL(`../../backend/tests/fixtures/company_research/${name}.json`,import.meta.url),'utf8')));
for(const data of fixtures){
 test(`actual registered API golden traverses production parser/stream ${data.subject.market}`,async t=>{
  const b=parseResearchBundle(data.bundle,data.subject,data.as_of);const stages:string[]=[];
  t.mock.method(globalThis,'fetch',async()=>new Response(data.events.map((x:unknown)=>JSON.stringify(x)).join('\n')+'\n'));
  const final=await generateCompanyResearch(b,llm,(s,v)=>{if(v)stages.push(s);},new AbortController().signal);
  assert.equal(stages.length,6);assert.deepEqual(parseResearchRecord(final),data.events.at(-1).record);
 });
}
for(const kind of ['cutoff','unqualified','fixture','capture','hash','hasharray','status','extra','mixedcutoff']){
 test(`archive receipt boundary rejects ${kind}`,()=>{
  const d=structuredClone(fixtures[0]);const row=d.bundle.sources[0];const v=row.payload;
  if(kind==='cutoff')delete d.bundle.archive_cutoff;
  if(kind==='unqualified'){v.qualification='MISSING_OR_INVALID_ARCHIVE';v.status='unavailable';}
  if(kind==='fixture')v.block.fixture='false';
  if(kind==='capture')v.capture_time={untrusted:'object'};
  if(kind==='hash')v.source_artifact_hash='claimedhash';
  if(kind==='hasharray')v.source_artifact_hash=[v.source_artifact_hash];
  if(kind==='status')row.status='ERROR';
  if(kind==='extra')v.extra=true;
  if(kind==='mixedcutoff'){v.as_of='2026-09-29';v.block.subject='A:600000@2026-09-29';v.block.requested_as_of='2026-09-29';}
  assert.throws(()=>parseResearchBundle(d.bundle,d.subject,d.as_of));
 });
}
