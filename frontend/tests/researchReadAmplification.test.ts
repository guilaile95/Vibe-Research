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
