import assert from 'node:assert/strict';
import test from 'node:test';
import { comparableSections, filingSourceUrl, filingRequest, type FilingDocument } from '../src/lib/filingEvidence.ts';
const before = { id:'one', issuer:'600519', form:'10-K', sections:[{key:'document',title:'Full',start:0,end:9},{key:'item-1',title:'Business',start:0,end:9}] } as FilingDocument;
test('comparison refuses different issuer, form, amendment, same version and missing section', () => {
  assert.deepEqual(comparableSections(before,before), []);
  assert.deepEqual(comparableSections(before,{...before,id:'two',issuer:'000001'}), []);
  assert.deepEqual(comparableSections(before,{...before,id:'two',form:'10-Q'}), []);
  assert.deepEqual(comparableSections(before,{...before,id:'two',form:'10-K/A'}), []);
  assert.deepEqual(comparableSections(before,{...before,id:'two',sections:[before.sections[0]]}), [before.sections[0]]);
});
test('source jumps allow only explicit safe http(s) references', () => {
  for (const url of ['javascript:alert(1)','data:text/html,foo','//example.com','https://user:password@example.com',null,'https://example.com/\nfoo']) assert.equal(filingSourceUrl(url),null);
  assert.equal(filingSourceUrl('https://example.com/report'),'https://example.com/report');
});
test('conflict is surfaced once without write retry', async () => {
  let calls=0;
  const original=globalThis.fetch;
  globalThis.fetch=(async () => { calls++; return new Response(JSON.stringify({detail:'版本已登记'}),{status:409}); }) as typeof fetch;
  try { await assert.rejects(filingRequest('/documents/id',{revision:'one'}), /版本已登记/); assert.equal(calls,1); }
  finally { globalThis.fetch=original; }
});
