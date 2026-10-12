import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { parseOcrResult, recognizeWatchlistImage } from '../src/lib/watchlistOcr.ts';
const hash=createHash('sha256').update('synthetic').digest('hex');
const fixture=()=>({schema_version:'local_ocr_preview.v1',status:'OCR_UNVERIFIED',source_truth_verified:false,source_sha256:hash,engine:'local-tesseract',language:'eng',limitations:['OCR may misread'],pages:[{page_number:1,text:'600519\n000858',source_sha256:hash,image_sha256:hash,text_sha256:createHash('sha256').update('600519\n000858').digest('hex')}]});
test('OCR is explicitly unverified and accepts only source-bound bounded page text',()=>{
 assert.equal(parseOcrResult(fixture()).text,'600519\n000858');
 for(const bad of [{...fixture(),source_truth_verified:true},{...fixture(),status:'VERIFIED'},{...fixture(),pages:[]},{...fixture(),source_sha256:'wrong'},{...fixture(),engine:'remote-model'},{...fixture(),pages:[{...fixture().pages[0],text:'x'.repeat(65537)}]}]) assert.throws(()=>parseOcrResult(bad));
});
test('explicit OCR sends only chosen bytes to authenticated local API, never watchlist or model',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',async(url,init)=>{calls++;assert.equal(String(url),'/api/local-ocr/preview');assert.equal(init?.method,'POST');assert.deepEqual(JSON.parse(String(init?.body)),{content_b64:'c3ludGhldGlj',extension:'.png',language:'eng',confirm_local_processing:true});return new Response(JSON.stringify({data:fixture()}));});
 const result=await recognizeWatchlistImage(new File(['synthetic'],'fixture.png'),'eng',new AbortController().signal);assert.equal(result.sourceSha256,hash);assert.equal(calls,1);
});
test('rejected type and cancelled local read never transmit',async t=>{
 t.mock.method(globalThis,'fetch',async()=>assert.fail('must not transmit'));
 await assert.rejects(recognizeWatchlistImage(new File(['x'],'private.pdf'),'eng',new AbortController().signal));
 const c=new AbortController();c.abort();await assert.rejects(recognizeWatchlistImage(new File(['x'],'fixture.png'),'eng',c.signal));
});

for (const change of [{language:'chi_sim+eng'}, {pages:[{...fixture().pages[0],image_sha256:'b'.repeat(64)}]}, {pages:[{...fixture().pages[0],text_sha256:'b'.repeat(64)}]}]) {
 test(`OCR language/text hash mismatch never reaches import ${JSON.stringify(change)}`,async t=>{
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({data:{...fixture(),...change}})));
  await assert.rejects(recognizeWatchlistImage(new File(['synthetic'],'fixture.png'),'eng',new AbortController().signal));
 });
}
test('OCR no-text status and text content must agree',()=>{
 assert.throws(()=>parseOcrResult({...fixture(),status:'OCR_NO_TEXT'}));
 assert.throws(()=>parseOcrResult({...fixture(),pages:[{...fixture().pages[0],text:'   '}]}));
 assert.throws(()=>parseOcrResult({...fixture(),schema_version:'future'}));
});

test('missing Chinese language never silently falls back or retries',async t=>{let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return new Response(JSON.stringify({detail:'CHINESE_LANGUAGE_UNAVAILABLE'}),{status:400});});await assert.rejects(recognizeWatchlistImage(new File(['synthetic'],'fixture.png'),'chi_sim+eng',new AbortController().signal),/未安装简体中文语言包.*不会自动改用英文/);assert.equal(calls,1);});
