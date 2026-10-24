import test from "node:test";
import assert from "node:assert/strict";
import { ReadRequestContext } from "../src/lib/readRequestContext.ts";
const deferred = <T,>() => { let resolve!: (v:T)=>void; const promise = new Promise<T>(r => { resolve=r; }); return {promise,resolve}; };
const tick = () => new Promise(r=>setImmediate(r));
test("bounded FIFO and in-flight dedupe; completed and failed reads can retry", async () => {
  const c = new ReadRequestContext(()=>"auth", 2);
  const held = deferred<number>(); const calls:string[]=[];
  const a=c.read("a",()=>{calls.push("a");return held.promise;});
  assert.equal(c.read("a",()=>{throw Error("duplicate");}),a);
  const b=c.read("b",()=>{calls.push("b");return held.promise;});
  const d=c.read("d",async()=>{calls.push("d");return 3;});
  assert.deepEqual(calls,["a","b"]);
  held.resolve(1); assert.deepEqual(await Promise.all([a,b,d]),[1,1,3]);
  assert.equal(await c.read("a",async()=>4),4);
  await assert.rejects(c.read("fail",async()=>{throw Error("no");}),/no/);
  assert.equal(await c.read("fail",async()=>5),5);
});
test("cancel rejects queued and active immediately even if fetch ignores abort; no queued dispatch", async()=>{
 const c=new ReadRequestContext(()=>"",1); let signal:AbortSignal|undefined; let queued=false;
 const a=c.read("a",s=>{signal=s;return new Promise(()=>{});});
 const b=c.read("b",async()=>{queued=true;return 2;});
 const outcomes=Promise.allSettled([a,b]);c.cancel();
 assert.equal(signal?.aborted,true);assert.equal(queued,false);
 assert.ok((await outcomes).every(v=>v.status==="rejected" && v.reason.name==="AbortError"));
 await assert.rejects(c.read("late",async()=>1),{name:"AbortError"});
});
test("auth ownership forbids queued dispatch and late fill; distinct contexts never share",async()=>{
 let auth="A";const c=new ReadRequestContext(()=>auth,1);const held=deferred<number>();
 const a=c.read("same",()=>held.promise);const b=c.read("queued",async()=>{throw Error("must not start");});
 const outcomes=Promise.allSettled([a,b]); auth="B";held.resolve(9);
 assert.ok((await outcomes).every(v=>v.status==="rejected" && v.reason.name==="AbortError"));
 const fresh=new ReadRequestContext(()=>auth);assert.equal(await fresh.read("same",async()=>2),2);
});
test("timeout aborts underlying transport, releases slot and does not accept late success",async()=>{
 const c=new ReadRequestContext(()=>"",1,10);const held=deferred<number>();let signal:AbortSignal|undefined;
 const a=c.read("slow",s=>{signal=s;return held.promise;});const b=c.read("next",async()=>2);
 await assert.rejects(a,/读取超时/);assert.equal(signal?.aborted,true);assert.equal(await b,2);
 held.resolve(99);await tick();assert.equal(await c.read("slow",async()=>3),3);
});
test("falsy rejection is not transformed into successful empty data",async()=>{
 const c=new ReadRequestContext(()=>"");
 const result=await Promise.allSettled([c.read("bad",()=>Promise.reject(null))]);
 assert.equal(result[0].status,"rejected");
 assert.equal(await c.read("bad",async()=>7),7);
});
