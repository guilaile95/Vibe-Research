/** Isolated Node measurement of real research store validation/serialization.
 * IndexedDB scheduling/structured clone is a controlled double, NOT browser/disk latency.
 * Run identically on baseline and candidate; no external sources or user records.
 */
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { writeFileSync } from 'node:fs';
import { createResearchWorkflowStore } from '../../src/lib/researchWorkflowStore.ts';
import { canonicalJson, RESEARCH_DEFAULT_BUDGET_BYTES } from '../../src/lib/researchWorkflow.ts';
const samples = Number(process.env.PERF_SAMPLES || 15);
import { researchFixture as fixture } from './research-fixture.mjs';

function install(snapshot) {
 let calls=0;
 const db={objectStoreNames:{contains:()=>true},close(){},transaction(){let pending=0,aborted=false;const tx={objectStore(name){return{getAll(){pending++;const request={};queueMicrotask(()=>{request.result=structuredClone(snapshot[name]);calls++;request.onsuccess();if(!--pending&&!aborted)queueMicrotask(()=>tx.oncomplete());});return request;}};},abort(){aborted=true;queueMicrotask(()=>tx.onabort());}};return tx;}};
 Object.defineProperty(globalThis,'indexedDB',{configurable:true,value:{open(){const request={};queueMicrotask(()=>{request.result=db;request.onsuccess();});return request;}}});
 return ()=>calls;
}
const percentile=(values,p)=>[...values].sort((a,b)=>a-b)[Math.ceil(values.length*p)-1];
const results=[];
for(const [count,chars] of [[25,1000],[250,50000],[1000,1000]]) {
 const snapshot=fixture(count,chars),bytes=Buffer.byteLength(canonicalJson(snapshot));
 assert.ok(bytes<RESEARCH_DEFAULT_BUDGET_BYTES);
 const calls=install(snapshot),store=createResearchWorkflowStore();
 const run=async()=>{const workspace=await store.readWorkspace('600001',null);const context=await store.getQuestionContext('q0');assert.equal(workspace.questions.length,1);assert.equal(context.question.id,'q0');assert.equal(context.rounds[0].materials[0].content.length,chars);};
 for(let i=0;i<3;i++)await run();
 const timings=[],cpus=[],heaps=[]; const beforeCalls=calls();
 for(let i=0;i<samples;i++){global.gc?.();const memory=process.memoryUsage().heapUsed,cpu=process.cpuUsage(),start=performance.now();await run();timings.push(performance.now()-start);const used=process.cpuUsage(cpu);cpus.push((used.user+used.system)/1000);heaps.push(process.memoryUsage().heapUsed-memory);}
 assert.equal(calls()-beforeCalls,samples*8);
 results.push({count,chars,snapshotBytes:bytes,getAllPerMount:8,samples,timingsMs:timings,cpuMs:cpus,heapDeltaBytes:heaps,p50Ms:percentile(timings,.5),p95Ms:percentile(timings,.95)});
 // Global damage must not become a healthy cached targeted result.
 snapshot.questions.at(-1).headRoundId='missing';await assert.rejects(()=>store.getQuestionContext('q0'));store.close();
}
const report={schema:'research-read-benchmark.v1',environment:{node:process.version,platform:process.platform,arch:process.arch},scope:'Node real production store + controlled IndexedDB scheduler; not native browser/disk/network',warmup:3,results};
const text=JSON.stringify(report,null,2);if(process.argv[2])writeFileSync(process.argv[2],text+'\n');console.log(text);
