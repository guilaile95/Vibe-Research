import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {waitForScreenerMode,waitForFullMarketLoading} from './e2e/screener-readiness.mjs';

function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function harness(mode){
 const calls=[],selected=deferred(),panel=deferred(),selectedStarted=deferred(),panelStarted=deferred();
 const page={
  async waitForURL(predicate,options){assert.equal(options.timeout,10000);assert.equal(predicate(new URL(`http://127.0.0.1/screener?mode=${mode}`)),true);calls.push('url');},
  locator(selector){return {async waitFor(options){assert.deepEqual(options,{state:'visible',timeout:10000});calls.push(selector);selectedStarted.resolve();await selected.promise;}};},
  getByPlaceholder(name,options){assert.equal(name,'000001 600519');assert.equal(options.exact,true);return {async waitFor(){calls.push('candidate-panel');panelStarted.resolve();await panel.promise;}};},
  getByTestId(id){assert.equal(id,'full-market-form');return {async waitFor(){calls.push('full-market-panel');panelStarted.resolve();await panel.promise;}};},
 };
 return {page,calls,selected,panel,selectedStarted,panelStarted};
}
for(const mode of ['candidate','full-market'])test(`URL ${mode} alone is not a committed selected panel`,async()=>{
 const h=harness(mode);let done=false;
 const pending=waitForScreenerMode(h.page,mode).then(()=>{done=true;});
 await h.selectedStarted.promise;assert.equal(done,false,'URL changes before React commits selected tab');
 assert.equal(h.calls.length,2);
 h.selected.resolve();await h.panelStarted.promise;assert.equal(done,false,'Selected tab must also own a rendered panel');
 h.panel.resolve();await pending;assert.equal(done,true);
});
for(const loading of [true,false])test(`loading ${loading} waits for enabled/disabled state and matching label`,async()=>{
 const gate=deferred(),started=deferred(),calls=[];let done=false;
 const page={locator(selector){calls.push(selector);return {async waitFor(options){assert.equal(options.timeout,10000);started.resolve();await gate.promise;}};},
  getByRole(role,options){assert.equal(role,'button');calls.push(options.name);assert.equal(options.exact,true);return {async waitFor(options){assert.equal(options.timeout,10000);}};}};
 const pending=waitForFullMarketLoading(page,loading).then(()=>{done=true;});
 await started.promise;assert.equal(done,false);gate.resolve();await pending;
 assert.deepEqual(calls,[`[data-testid="run-full-market"]:${loading?'disabled':'enabled'}`,loading?'查询中…':'运行全市场筛选']);
});

const file=new URL('./e2e/full-market-source-to-sink.browser.mjs',import.meta.url);
const source=ts.createSourceFile(file.pathname,readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
const scenario=source.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='runModeSwitchScenario')?.getText(source);
assert.ok(scenario);
test('actual mode-switch scenario keeps ordinary clicks, commits, cancellation, and late-result checks in order',()=>{
 const ordered=[
  'await page.getByTestId("candidate-pool-tab").click()',
  'await waitForScreenerMode(page, "candidate")',
  'await requestCancelled',
  'await page.getByTestId("full-market-tab").click()',
  'await waitForScreenerMode(page, "full-market")',
  'await waitForFullMarketLoading(page, false)',
  'timing.release()', 'await timing.returned',
  'late Full Market response repopulated Full Market after mode switch',
 ];
 let position=scenario.indexOf(ordered[0]);assert.ok(position>=0);
 for(const fragment of ordered.slice(1)){const next=scenario.indexOf(fragment,position+1);assert.ok(next>position,fragment);position=next;}
 assert.match(scenario,/page\.waitForEvent\("requestfailed",\s*\{\s*predicate: request => request === ownedRequest/);
 assert.doesNotMatch(scenario,/waitForTimeout|force:\s*true/);
});

test('readiness timeout is not swallowed or treated as selected',async()=>{
 const h=harness('candidate');
 h.page.locator=()=>({waitFor:async()=>{throw new Error('selected tab timeout');}});
 await assert.rejects(waitForScreenerMode(h.page,'candidate'),/selected tab timeout/);
 assert.deepEqual(h.calls,['url']);
});
test('loading wait requires the exact final label after button enabled state',async()=>{
 const page={locator:()=>({waitFor:async()=>{}}),getByRole:()=>({waitFor:async()=>{throw new Error('label not committed');}})};
 await assert.rejects(waitForFullMarketLoading(page,false),/label not committed/);
});
