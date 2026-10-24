import assert from 'node:assert/strict';
import test from 'node:test';
import { createResearchWorkflowStore } from '../src/lib/researchWorkflowStore.ts';
import { canonicalJson, RESEARCH_DEFAULT_BUDGET_BYTES } from '../src/lib/researchWorkflow.ts';
// Readonly IndexedDB scheduler double. Native transactions and CAS are also
// exercised in research-workflow-storage.browser.mjs, not inferred from this.
function fixture(count: number, chars: number) {
  const questions = [], rounds = [];
  for (let i=0;i<count;i++) {
    const securityCode=i===0?'600001':'600002';
    rounds.push({id:`r${i}`,questionId:`q${i}`,securityCode,parentRoundId:null,createdAt:2,materials:[{id:`m${i}`,version:'v1',securityCode,title:'synthetic',content:'x'.repeat(chars),sourceUrl:null,sourceKind:'manual',sourceHash:null,publishedAt:null,capturedAt:1,readRange:{pages:[],totalPages:null,truncated:false,ocr:false,description:'synthetic'},availability:'partial'}],calculation:null,judgement:'synthetic',limitations:'synthetic',nextMaterial:'next',reviewedMaterialKeys:[],ignoredMaterialKeys:[],coverage:'partial'});
    questions.push({id:`q${i}`,securityCode,question:'synthetic',origin:{kind:'manual',label:'synthetic',capturedAt:1},createdAt:1,updatedAt:2,revision:1,headRoundId:`r${i}`,status:'watching',reviewedMaterialKeys:[]});
  }
  return {questions,rounds,operations:[],legacySources:[]};
}
function readonlyDatabase(snapshot: ReturnType<typeof fixture>) {
 let calls=0,bytes=0;
 const db={objectStoreNames:{contains:()=>true},close(){},transaction(){let pending=0,aborted=false;const tx:any={objectStore(name:keyof typeof snapshot){return{getAll(){pending++;const r:any={};queueMicrotask(()=>{r.result=structuredClone(snapshot[name]);calls++;bytes+=Buffer.byteLength(JSON.stringify(r.result));r.onsuccess();if(!--pending&&!aborted)queueMicrotask(()=>tx.oncomplete());});return r;}};},abort(){aborted=true;queueMicrotask(()=>tx.onabort());}};return tx;}};
 Object.defineProperty(globalThis,'indexedDB',{configurable:true,value:{open(){const r:any={};queueMicrotask(()=>{r.result=db;r.onsuccess();});return r;}}});
 return {get calls(){return calls;},get bytes(){return bytes;}};
}
test('candidate initial list/legacy/source read uses one snapshot, plus one selected context snapshot',async()=>{
 const snapshot=fixture(250,50000), bytes=Buffer.byteLength(canonicalJson(snapshot));assert.ok(bytes<RESEARCH_DEFAULT_BUDGET_BYTES);
 const reads=readonlyDatabase(snapshot),store=createResearchWorkflowStore();
 const workspace=await store.readWorkspace('600001',null);const context=await store.getQuestionContext('q0');
 assert.equal(workspace.questions.length,1);assert.deepEqual(workspace.legacyNotes,[]);assert.equal(workspace.legacySource.changed,false);assert.equal(context?.question.id,'q0');
 assert.equal(reads.calls,8,'baseline used 16 getAll calls for the same UI mount');assert.ok(reads.bytes<bytes*2.01);
 console.log(JSON.stringify({snapshotBytes:bytes,getAllCalls:reads.calls,bytesRead:reads.bytes,baselineGetAllCalls:16}));store.close();
});
test('unrelated damaged global chain still rejects optimized workspace reads; no false healthy cache',async()=>{
 const snapshot=fixture(2,100);readonlyDatabase(snapshot);const store=createResearchWorkflowStore();
 assert.equal((await store.readWorkspace('600001',null)).questions.length,1);
 snapshot.questions[1].headRoundId='missing-unrelated';
 await assert.rejects(()=>store.readWorkspace('600001',null),/缺父|链头/);
 await assert.rejects(()=>store.getQuestionContext('q0'),/缺父|链头/);store.close();
});

test('page projection tampering fails save, import and already-stored read validation', async () => {
 const { reportPageMaterials } = await import('../src/lib/researchCheck.ts');
 const { validateResearchMaterial, validateResearchRound, researchContentHash, RESEARCH_BACKUP_SCHEMA } = await import('../src/lib/researchWorkflow.ts');
 const report = { id:'receipt',name:'synthetic.pdf',size:1,industry:'synthetic',ext:'.pdf',ts:1,file_sha256:'a'.repeat(64),page_count:1 };
 const response = {report_id:report.id,file_sha256:report.file_sha256,scope:'INDEXED_PAGE_TEXT_ONLY' as const,full_report_read:false as const,requested:[1],returned_chars:4,complete_requested_text:true,coverage:{readable:[1],omitted:[],invalid:[],unreadable:[],error:[]},items:[{page:1,status:'readable' as const,reason:'AVAILABLE',text:'text',returned_chars:4,indexed_chars:4,truncated:false}]};
 const [material] = await reportPageMaterials(report,response,'600001',1,1);
 material.capturedAt=1;
 assert.deepEqual(validateResearchMaterial(material),material);
 const legacy=structuredClone(material); legacy.provenance!.page_receipt=JSON.parse(JSON.stringify(response));
 assert.deepEqual(validateResearchMaterial(legacy),legacy);
 const mutations: Record<string,(m:any)=>void> = {
  file:m=>m.provenance.page_receipt.request.file_sha256='b'.repeat(64),
  text:m=>m.provenance.page_receipt.item.text='forged',
  security:m=>m.provenance.security_assignment.code='600002',
  schema:m=>m.provenance.page_receipt.schema_version='bogus',
  missingSchema:m=>delete m.provenance.page_receipt.schema_version,
  digest:m=>m.provenance.page_receipt.original_receipt_sha256='not-a-digest',
  report:m=>m.provenance.page_receipt.request.report_id='another',
  page:m=>m.provenance.page_receipt.item.page=2,
  coverage:m=>m.provenance.page_receipt.request.coverage.omitted=[1],
  status:m=>m.provenance.page_receipt.item.status='omitted',
  truncation:m=>m.provenance.page_receipt.item.truncated=true,
  ocr:m=>m.readRange.ocr=true,
  availability:m=>m.availability='full',
  url:m=>m.sourceUrl='https://example.com/other',
 };
 for (const [name, mutate] of Object.entries(mutations)) {
  const damaged=structuredClone(material);mutate(damaged);
  const snapshot=fixture(1,1);snapshot.rounds[0].materials=[damaged] as any;
  const round=snapshot.rounds[0];
  assert.throws(()=>validateResearchMaterial(damaged),undefined,name);
  assert.throws(()=>validateResearchRound(round),undefined,name);
  readonlyDatabase(fixture(1,1)); const store=createResearchWorkflowStore();
  await assert.rejects(()=>store.appendRound({operationId:'invalid',questionId:'q0',expectedRevision:1,expectedHeadRoundId:'r0',round:round as any}),undefined,`${name}: save`);
  // Recomputed outer checksum cannot legitimize an internally inconsistent projection.
  const backup={schemaVersion:RESEARCH_BACKUP_SCHEMA,exportedAt:new Date().toISOString(),data:snapshot,manifest:{sha256:await researchContentHash(canonicalJson(snapshot)),questionIds:['q0'],roundIds:['r0']}};
  await assert.rejects(()=>store.importBackup(JSON.stringify(backup),'invalid-import'),undefined,`${name}: import`);
  store.close();
  readonlyDatabase(snapshot); const damagedStore=createResearchWorkflowStore();
  await assert.rejects(()=>damagedStore.readWorkspace('600001',null),undefined,`${name}: stored read`);
  damagedStore.close();
 }
 const ocr=structuredClone(material);
 const extraction={schema_version:'local_ocr_preview.v1',status:'OCR_UNVERIFIED',source_sha256:report.file_sha256,engine:'local-tesseract',language:'eng',source_truth_verified:false,limitations:['synthetic'],pages:[{page_number:1,source_sha256:report.file_sha256,image_sha256:'b'.repeat(64),text_sha256:'c'.repeat(64),mean_word_confidence:null}]};
 (ocr.provenance!.page_receipt as any).request.extraction=extraction;ocr.readRange.ocr=true;
 assert.deepEqual(validateResearchMaterial(ocr),ocr);
 extraction.language='bogus';assert.throws(()=>validateResearchMaterial(ocr),/语言/);
 // A well-formed original digest is opaque: a projection cannot prove full-receipt authenticity.
 const opaque=structuredClone(material);(opaque.provenance!.page_receipt as any).original_receipt_sha256='b'.repeat(64);
 assert.deepEqual(validateResearchMaterial(opaque),opaque);
});
