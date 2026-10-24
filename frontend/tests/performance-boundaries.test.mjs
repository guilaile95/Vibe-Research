import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const source=path=>readFileSync(new URL(path,import.meta.url),'utf8');
test('sector content retains existing dynamic boundaries instead of one eager manual chunk',()=>{
 assert.doesNotMatch(source('../vite.config.ts'),/return\s+["']sector-research["']/);
 const registry=source('../src/data/sectorResearch/index.ts');
 assert.match(registry,/pcb:\s*\(\)\s*=>\s*import\(/);
 assert.match(registry,/loadSectorResearchWorkspace/);
});
test('paired production benchmark is bounded and refuses synthetic writes or external traffic',()=>{
 const harness=source('./performance/frontend.browser.mjs');
 assert.match(harness,/assert\.deepEqual\(writes,\[\]\)/);
 assert.match(harness,/assert\.deepEqual\(external,\[\]\)/);
 assert.match(harness,/res\.writeHead\(503\)/);
 assert.match(harness,/getByRole\('heading',\{name:'合成证券 600001'/);
 assert.match(harness,/PERF_BROWSER_SAMPLES\|\|21/);
 assert.match(harness,/trial%2===0\?servers/);
});

import vm from 'node:vm';
import { installDateOnlyClock, assertNativeTelemetry } from './performance/browser-observation.mjs';
test('Date-only freeze preserves genuine performance entries, timers, RAF and explicit Date semantics',()=>{
 const performance={now:()=>123.456,getEntriesByType:()=>[{name:'native-resource'}]};
 const setTimeout=()=>{},requestAnimationFrame=()=>{};
 const scope=vm.createContext({performance,setTimeout,requestAnimationFrame});
 vm.runInContext(`(${installDateOnlyClock.toString()})(1791417600000)`,scope);
 assert.equal(vm.runInContext('Date.now()',scope),1791417600000);
 assert.equal(vm.runInContext('new Date().getTime()',scope),1791417600000);
 assert.equal(vm.runInContext('new Date(0).getTime()',scope),0);
 assert.equal(vm.runInContext('Date.parse("1970-01-01T00:00:00Z")',scope),0);
 assert.equal(vm.runInContext('Date.UTC(1970,0,1)',scope),0);
 assert.equal(vm.runInContext('Date()',scope),vm.runInContext('new Date().toString()',scope));
 assert.equal(vm.runInContext('performance',scope),performance);
 assert.equal(vm.runInContext('setTimeout',scope),setTimeout);
 assert.equal(vm.runInContext('requestAnimationFrame',scope),requestAnimationFrame);
 assert.equal(vm.runInContext('performance.now()',scope),123.456);
 assert.equal(vm.runInContext('performance.getEntriesByType("resource")[0].name',scope),'native-resource');
});
test('fake zero-entry telemetry fails instead of yielding a green performance report',()=>{
 const row={name:'daily-cold',firstUsefulMs:100,uiSettledMs:120,fetchStarted:1,navigation:{responseEnd:5},paints:[{name:'first-contentful-paint',startTime:50}],requests:[{path:'/assets/main.js',decodedBytes:100,transferBytes:400},{path:'/api/daily-review',decodedBytes:20}]};
 assert.doesNotThrow(()=>assertNativeTelemetry(row));
 for(const patch of [{requests:[]},{paints:[]},{navigation:null},{navigation:{responseEnd:0}},{requests:[{path:'/assets/main.js',decodedBytes:100,transferBytes:0},{path:'/api/daily-review',decodedBytes:20}]},{firstUsefulMs:-1},{uiSettledMs:90},{fetchStarted:0}])assert.throws(()=>assertNativeTelemetry({...row,...patch}));
 assert.doesNotMatch(source('./performance/frontend.browser.mjs'),/page\.clock/);
});
