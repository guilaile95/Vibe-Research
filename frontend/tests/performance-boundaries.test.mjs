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
