/** Production-build paired browser benchmark. Controlled loopback APIs, never supplier/model latency.
 * Baseline and candidate run in alternating order. Cold = new browser context; OS cache is not reset.
 * External fonts removed identically. No request interception (it would disable HTTP caching).
 * Runtime metrics are evidence, not flaky CI thresholds. Correctness assertions still fail CI.
 */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { resolve, dirname, extname, sep, join } from 'node:path';
import { performance } from 'node:perf_hooks';
import { chromium } from 'playwright';
import ts from 'typescript';
import { ancillaryReply, ANCILLARY_CLOCK } from '../e2e/final-families.fixture.mjs';
import { researchFixture } from './research-fixture.mjs';
import { measureBuild } from './build-assets.mjs';
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs,arg,i,all)=>arg.startsWith('--')?[...pairs,[arg.slice(2),all[i+1]]]:pairs,[]));
assert.ok(args['baseline-dist'] && args['candidate-dist'] && args.output, 'Pass --baseline-dist --candidate-dist --output');
const output=resolve(args.output);mkdirSync(output,{recursive:true});
const samples=Number(process.env.PERF_BROWSER_SAMPLES||21), warmup=1;
assert.ok(Number.isInteger(samples)&&samples>=3);
const sourceErrors=[],writes=[],external=[],rows=[],sequence=[];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function fixtureReply(url) {
 const p=url.pathname,code=url.searchParams.get('code');
 if(p==='/api/valuation')return {data:{code,name:`合成证券 ${code}`,price:10,pe_ttm:12,pb:1,mcap_yi:30,analyst_count:0}};
 if(p==='/api/news')return {data:[{新闻标题:`合成主资讯 ${code}`,发布时间:'2026-10-08 10:00',新闻链接:''}]};
 if(p==='/api/finance')return {data:{}};
 if(p==='/api/reports'||p==='/api/announcements'||p==='/api/myreports')return {data:[]};
 if(p==='/api/quote')return {data:{}};
 if(p==='/api/daily-review/history')return {data:{items:[],count:0,limit:20,offset:0}};
 if(p==='/api/sector-research/market-context')return {data:{items:[]}};
 const reply=ancillaryReply('GET',p,url.search);
 if(p==='/api/daily-review'&&reply){reply.data.status='partial';reply.data.warnings=['合成基准：仅指数与证券报价可用，其他来源明确不可用'];reply.data.market_environment.indices.data=[{name:'合成基准指数',price:3000,change_pct:1,amount:1000}];}
 return reply;
}
async function serverFor(label,dist) {
 const root=resolve(dist),src=join(dirname(root),'src');assert.ok(existsSync(join(root,'index.html')));
 const server=createServer(async(req,res)=>{
  try{
   const url=new URL(req.url,'http://synthetic.invalid'),path=url.pathname;
   if(path.startsWith('/api/')){
    res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json');
    if(req.method!=='GET'){writes.push({label,method:req.method,path});res.writeHead(405);res.end(JSON.stringify({detail:'Unexpected synthetic write'}));return;}
    // Same deterministic provider wait, unchanged for both builds; never counted as real provider performance.
    await sleep(20);
    const reply=fixtureReply(url);
    if(reply==null){sourceErrors.push({label,path:path+url.search});res.writeHead(503);res.end(JSON.stringify({detail:'Synthetic unavailable source'}));return;}
    res.end(JSON.stringify(reply));return;
   }
   if(path==='/perf-storage'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Isolated native storage performance</title>');return;}
   if(path.startsWith('/perf-src/')&&path.endsWith('.ts')){
    const file=resolve(src,path.slice('/perf-src/'.length));if(!file.startsWith(src+sep)||!existsSync(file)){res.writeHead(404).end();return;}
    res.setHeader('Content-Type','text/javascript');res.end(ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.ESNext}}).outputText);return;
   }
   let file=resolve(root,'.'+path);if(!file.startsWith(root+sep)||!existsSync(file)||!extname(file))file=join(root,'index.html');
   let data=readFileSync(file);const ext=extname(file);
   if(ext==='.html')data=Buffer.from(data.toString().replace(/\s*<link[^>]*https:\/\/fonts\.(?:googleapis|gstatic)\.com[^>]*>/g,''));
   res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[ext]||'application/octet-stream');
   res.setHeader('Cache-Control',ext==='.html'?'no-cache':'public, max-age=31536000, immutable');
   res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'");
   res.setHeader('Content-Length',data.length);res.end(data);
  }catch(error){res.writeHead(500);res.end('Synthetic server error');console.error(error);}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));return {label,root,server,origin:`http://127.0.0.1:${server.address().port}`};
}
function observe(){
 window.__perf={pending:0,started:0,longTasks:[]};
 try{new PerformanceObserver(list=>window.__perf.longTasks.push(...list.getEntries().map(e=>({startTime:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});}catch{}
 const fetch=window.fetch.bind(window);window.fetch=async(...args)=>{window.__perf.pending++;window.__perf.started++;try{const response=await fetch(...args);for(const method of ['json','text','arrayBuffer','blob']){const read=response[method].bind(response);response[method]=async(...values)=>{window.__perf.pending++;try{return await read(...values);}finally{window.__perf.pending--;}};}return response;}finally{window.__perf.pending--;}};
}
async function settle(page){for(let attempt=0;attempt<30;attempt++){await page.waitForFunction(()=>window.__perf?.pending===0);const started=await page.evaluate(()=>window.__perf.started);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));if(await page.evaluate(started=>window.__perf.pending===0&&window.__perf.started===started,started))return;}throw Error('UI did not settle within bounded frame checks');}
function quantile(values,p){return [...values].sort((a,b)=>a-b)[Math.ceil(values.length*p)-1];}
const servers=await Promise.all([serverFor('baseline',args['baseline-dist']),serverFor('candidate',args['candidate-dist'])]);let browser;
try{
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{})});
 for(let trial=-warmup;trial<samples;trial++)for(const server of trial%2===0?servers:[...servers].reverse()){
  sequence.push({label:server.label,trial});
  const context=await browser.newContext({baseURL:server.origin,viewport:{width:1440,height:960},serviceWorkers:'block'});
  await context.addInitScript(observe);const page=await context.newPage();page.setDefaultTimeout(15000);
  // Freeze Date, not performance clocks, to keep calendar-dependent requests identical.
  await page.clock.setFixedTime(new Date(ANCILLARY_CLOCK));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',req=>{if(new URL(req.url()).origin!==server.origin)external.push(req.url());});
  const cdp=await context.newCDPSession(page);await cdp.send('Performance.enable');
  const measure=async(name,action,ready)=>{
   const before=await page.evaluate(()=>({start:performance.now(),resourceCount:performance.getEntriesByType('resource').length,longCount:window.__perf?.longTasks.length||0})).catch(()=>({start:0,resourceCount:0,longCount:0}));
   const start=performance.now();await action();await ready();const firstUsefulMs=performance.now()-start;await settle(page);const uiSettledMs=performance.now()-start;
   const details=await page.evaluate(({before,name})=>{const nav=name.includes('reload')||name.includes('cold')||name.includes('document');const resources=performance.getEntriesByType('resource').slice(nav?0:before.resourceCount);const tasks=(window.__perf?.longTasks||[]).slice(nav?0:before.longCount);return {requests:resources.map(r=>({path:new URL(r.name).pathname+new URL(r.name).search,transferBytes:r.transferSize,decodedBytes:r.decodedBodySize,durationMs:r.duration})),longTaskCount:tasks.length,longTaskMs:tasks.reduce((s,t)=>s+t.duration,0),navigationType:performance.getEntriesByType('navigation')[0]?.type,paints:performance.getEntriesByType('paint').map(e=>({name:e.name,startTime:e.startTime})),navigation:performance.getEntriesByType('navigation')[0]?.toJSON()};},{before,name});
   const metrics=Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m=>[m.name,m.value]));
   if(trial>=0)rows.push({label:server.label,trial,name,firstUsefulMs,uiSettledMs,...details,jsHeapUsedBytes:metrics.JSHeapUsedSize,cumulativeTaskDurationSeconds:metrics.TaskDuration});
   if(trial===0&&['daily-cold','stock-document','pcb-content-route'].includes(name))await page.screenshot({path:join(output,`${server.label}-${name}.png`)});
  };
  await measure('daily-cold',()=>page.goto('/daily-review'),()=>page.getByText('合成基准指数',{exact:true}).waitFor());
  await measure('daily-warm-reload',()=>page.reload(),()=>page.getByText('合成基准指数',{exact:true}).waitFor());
  await measure('stock-document',()=>page.goto('/stock-data?code=600001'),()=>page.getByRole('heading',{name:'合成证券 600001',exact:true}).waitFor());
  await measure('stock-events-tab',()=>page.getByTestId('stock-data-tab-events').click(),()=>page.getByText('合成主资讯 600001',{exact:true}).waitFor());
  await measure('stock-switch-security',async()=>{await page.getByPlaceholder(/A 股 6 位代码/).fill('600002');await page.getByPlaceholder(/A 股 6 位代码/).press('Enter');},()=>page.getByRole('heading',{name:'合成证券 600002',exact:true}).waitFor());
  await measure('sector-document',()=>page.goto('/sectors'),()=>page.getByRole('heading',{name:'板块中心',exact:true}).waitFor());
  await measure('pcb-content-route',()=>page.locator('a[href="/sectors/pcb/overview"]').first().click(),()=>page.getByText(/^AI 服务器用 PCB 可理解为 AI 机柜内的电气互连骨架/).waitFor());
  assert.deepEqual(errors,[],`${server.label} page errors`);await context.close();
 }
 // Native IndexedDB measurement: seed raw synthetic records outside measured region, then run real store validation.
 const storage=[];
 for(const [count,chars] of [[25,1000],[250,50000],[1000,1000]]){
  const pages=[];
  for(const server of servers){
   const context=await browser.newContext({baseURL:server.origin});const page=await context.newPage();await page.goto('/perf-storage');
   await page.evaluate(async(snapshot)=>{
    const {createResearchWorkflowStore}=await import('/perf-src/lib/researchWorkflowStore.ts');const name=`perf-${snapshot.questions.length}`;const store=createResearchWorkflowStore({dbName:name});await store.listQuestions();
    const db=await new Promise((resolve,reject)=>{const r=indexedDB.open(name);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    await new Promise((resolve,reject)=>{const tx=db.transaction(Object.keys(snapshot),'readwrite');for(const [name,rows]of Object.entries(snapshot))for(const row of rows)tx.objectStore(name).add(row);tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error);});
    window.__storageRun=async()=>{const w=await store.readWorkspace('600001',null),c=await store.getQuestionContext('q0');if(w.questions.length!==1||c.question.id!=='q0')throw Error('Research result mismatch');};
    for(let i=0;i<3;i++)await window.__storageRun();
    window.__storageReads=0;const getAll=IDBObjectStore.prototype.getAll;IDBObjectStore.prototype.getAll=function(...args){window.__storageReads++;return getAll.apply(this,args);};
    window.__storageClose=()=>{IDBObjectStore.prototype.getAll=getAll;store.close();db.close();};
   },researchFixture(count,chars));
   pages.push({label:server.label,page,context,timingsMs:[]});
  }
  for(let trial=0;trial<samples;trial++)for(const entry of trial%2===0?pages:[...pages].reverse()){
   entry.timingsMs.push(await entry.page.evaluate(async()=>{const start=performance.now();await window.__storageRun();return performance.now()-start;}));
  }
  for(const entry of pages){
   const getAllPerMount=await entry.page.evaluate(samples=>window.__storageReads/samples,samples);assert.equal(getAllPerMount,8);
   storage.push({label:entry.label,count,chars,getAllPerMount,timingsMs:entry.timingsMs,p50Ms:quantile(entry.timingsMs,.5),p95Ms:quantile(entry.timingsMs,.95)});
   await entry.page.evaluate(()=>window.__storageClose());await entry.context.close();
  }
 }

 assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
 const summary=[];for(const label of ['baseline','candidate'])for(const name of [...new Set(rows.map(r=>r.name))]){const group=rows.filter(r=>r.label===label&&r.name===name);summary.push({label,name,samples:group.length,firstUsefulP50Ms:quantile(group.map(r=>r.firstUsefulMs),.5),firstUsefulP95Ms:quantile(group.map(r=>r.firstUsefulMs),.95),uiSettledP50Ms:quantile(group.map(r=>r.uiSettledMs),.5),uiSettledP95Ms:quantile(group.map(r=>r.uiSettledMs),.95),medianSubresourceTransferredBytes:quantile(group.map(r=>r.requests.reduce((s,q)=>s+q.transferBytes,0)),.5),medianRequests:quantile(group.map(r=>r.requests.length),.5)});}
 const buildIdentities=Object.fromEntries(servers.map(s=>[s.label,JSON.parse(readFileSync(join(s.root,'vibe-build.json'),'utf8'))]));
 const builds=Object.fromEntries(servers.map(s=>[s.label,measureBuild(s.root)]));
 assert.equal(builds.baseline.eagerPcbBody,true,'Baseline must reproduce eager content');assert.equal(builds.candidate.eagerPcbBody,false,'Candidate must defer unrelated full sector bodies');
 const report={buildIdentities,builds,sequence,schema:'frontend-performance.v1',node:process.version,browser:browser.version(),samples,warmup,scope:'Production assets over uncompressed loopback; 20 ms synthetic API wait; cold browser context, warm reload, OS cache not reset; external fonts removed; no live provider/model/user data; UI-settled proxy = ready marker + fetch/body-read idle and unchanged request count across two animation frames; not full market-data completion',rows,summary,storage,unavailableSources:[...new Set(sourceErrors.map(r=>r.path))],writes,external};
 writeFileSync(join(output,'results.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({summary,storage},null,2));
}catch(error){writeFileSync(join(output,'failure.json'),JSON.stringify({message:error.message,stack:error.stack,rows,sourceErrors,writes,external},null,2));throw error;}finally{await browser?.close();await Promise.all(servers.map(s=>new Promise(r=>s.server.close(r))));}
