import test from 'node:test';import assert from 'node:assert/strict';
import {createShortlineFixture,golden,DAY} from './e2e/shortline-review.fixture.mjs';
import {ownsPreview,ownsReview} from '../src/lib/shortlineReview.ts';
test('actual API goldens retain daily/weekly/missing scopes and unverified authority',()=>{
 for(const [name,g]of Object.entries(golden)){assert.equal(ownsPreview(g.preview,DAY,g.preview.mode),true,name);if(g.version)assert.equal(ownsReview(g.version,DAY,g.preview.mode),true,name);}
 assert.equal(golden.daily.synthetic_model_calls,6);assert.equal(golden.weekly.synthetic_model_calls,4);assert.equal(golden.partial.version.stages[3].status,'skipped');assert.equal(golden.empty.preview.available,false);
});
test('fixture accepts only explicit synthetic generation bodies and exact reads',()=>{
 const origin='http://127.0.0.1:1234',f=createShortlineFixture(origin),p='/api/shortline-review/';
 for(const [path,method,body]of [[p+'preview?trade_date='+DAY+'&mode=daily&x=1','GET'],[p+'versions?trade_date='+DAY+'&trade_date='+DAY+'&mode=daily','GET'],[p+'generate','PUT',{}],[p+'generate','POST',{llm:{apiKey:'unexpected'}}]])assert.equal(f.handle(origin+path,method,body).kind,'deny');
 const clean=createShortlineFixture(origin);const body={trade_date:DAY,mode:'daily',bundle_id:golden.daily.preview.bundle_id,generation_id:'f'.repeat(32),llm:{provider:'cli-codex',baseURL:'',apiKey:'',model:'SYNTHETIC_OFFLINE'}};
 const stream=clean.handle(origin+p+'generate','POST',body);assert.equal(stream.kind,'stream');assert.equal(clean.saved.size,0);stream.commit();assert.equal(clean.saved.size,1);assert.equal(clean.handle(origin+p+'version/'+body.generation_id).body.data.fact_verification,'NOT_PERFORMED');
 assert.equal(clean.handle('https://external.invalid'+p+'versions?trade_date='+DAY+'&mode=daily').kind,'deny');
});
