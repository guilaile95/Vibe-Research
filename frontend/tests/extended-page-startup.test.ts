import assert from 'node:assert/strict';
import test from 'node:test';
import {createExtendedPageFixture,startupGolden,CLOCK} from './e2e/extended-page.fixture.mjs';
import {verificationDate,isVerificationViewForDate} from '../src/lib/nextDayVerification.ts';
const origin='http://127.0.0.1:8911';
const journal='/api/next-day-verification/2026-10-13',calendar='/api/research-events?security_code=600000';
test('initial journal date follows fixed Shanghai day before review arrives',()=>{
 assert.equal(verificationDate(undefined,new Date(CLOCK)),'2026-10-13');
 assert.equal(isVerificationViewForDate(startupGolden.journal.data,'2026-10-13'),true);
 const f=createExtendedPageFixture(origin);assert.deepEqual(f.handle(origin+journal).body,startupGolden.journal);
 assert.deepEqual(f.violations,[]);assert.deepEqual(f.base.violations,[]);assert.deepEqual(f.base.writes,[]);
});
test('mounted CN calendar preserves actual unavailable source projection',()=>{
 const f=createExtendedPageFixture(origin);assert.deepEqual(f.handle(origin+calendar).body,startupGolden.calendar);
 assert.equal(startupGolden.calendar.data.status,'UNAVAILABLE');assert.deepEqual(startupGolden.calendar.data.events,[]);
 assert.equal(startupGolden.calendar.data.universe.securities[0].security_code,'600000');
 assert.equal(startupGolden.calendar.data.as_of,'2026-10-13');assert.ok(Object.values(startupGolden.calendar.data.writes).every(v=>v===0));
 assert.deepEqual(f.violations,[]);assert.deepEqual(f.base.violations,[]);assert.deepEqual(f.base.writes,[]);
});
for(const path of [journal,calendar])for(const method of ['POST','PUT','DELETE','HEAD'])test(`startup forbids ${method} ${path}`,()=>{
 const f=createExtendedPageFixture(origin);assert.equal(f.handle(origin+path,method).kind,'deny');assert.equal(f.violations.length,1);
});
for(const path of [journal+'?as_of=2026-10-13',journal+'?trade_date=2026-10-13&trade_date=2026-10-13','/api/next-day-verification/2026-10-12','/api/next-day-verification/2026-10-14',calendar+'&security_code=600000',calendar+'&date_from=2026-10-13',calendar+'&provider=live','/api/research-events?security_code=600001','/api/research-events'])test('startup exact identity rejects '+path,()=>{
 const f=createExtendedPageFixture(origin);assert.equal(f.handle(origin+path).kind,'deny');assert.equal(f.violations.length+f.base.violations.length,1);
});
