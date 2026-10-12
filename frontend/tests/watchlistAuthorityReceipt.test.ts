import assert from 'node:assert/strict';
import test from 'node:test';
import { saveWatchAuthoritative, loadWatchAuthoritative } from '../src/lib/watchlist.ts';
const tag = '0123456789abcdef';
for (const response of [null, {}, { codes: ['000858'], etag: tag }, { codes: ['600519'], etag: 'bad' }, { codes: ['600519','600519'], etag: tag }]) {
 test(`uncertain save acknowledgement retains draft ${JSON.stringify(response)}`, async t => {
  let clears=0;const old=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{removeItem:()=>{clears++;}}});
  t.after(()=>old?Object.defineProperty(globalThis,'localStorage',old):Reflect.deleteProperty(globalThis,'localStorage'));
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:response})));
  await assert.rejects(saveWatchAuthoritative(['600519'],tag));assert.equal(clears,0);
 });
}
test('verified save sends explicit expected absent state and only then clears draft',async t=>{
 let clears=0;const old=Object.getOwnPropertyDescriptor(globalThis,'localStorage');Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{removeItem:()=>{clears++;}}});t.after(()=>old?Object.defineProperty(globalThis,'localStorage',old):Reflect.deleteProperty(globalThis,'localStorage'));
 t.mock.method(globalThis,'fetch',async(_,init)=>{assert.deepEqual(JSON.parse(String(init?.body)),{codes:['600519'],expected_etag:'NOT_CONFIGURED'});return new Response(JSON.stringify({data:{codes:['600519'],etag:tag}}));});
 assert.deepEqual(await saveWatchAuthoritative(['600519','600519'],'NOT_CONFIGURED'),{codes:['600519'],etag:tag});assert.equal(clears,1);
});
for(const data of [null,{status:'valid',data:{codes:['600519']},etag:'bad'},{status:'valid',data:{codes:['wrong']},etag:tag},{status:'not_configured',data:{codes:[]},etag:null},{status:'unknown',data:null,etag:null}]){
 test(`malformed authority cannot become import base ${JSON.stringify(data)}`,async t=>{
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data})));
  await assert.rejects(loadWatchAuthoritative());
 });
}
