/** Full production page, strict synthetic API/NDJSON; actual router/store parity is tested separately. */
import {observedBrowserAction} from './observed-browser-action.mjs';
import {captureBrowserFailure} from './browser-failure-evidence.mjs';
import assert from 'node:assert/strict';import {createServer} from 'node:http';
import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';import path from 'node:path';import {fileURLToPath} from 'node:url';import {chromium} from 'playwright';
import {createFixture,CLOCK} from './next-day-verification.fixture.mjs';import {createShortlineFixture,DAY,golden} from './shortline-review.fixture.mjs';
if(process.env.CI!=='true')throw Error('Browser execution is CI-only');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),dist=path.join(root,'dist'),output=process.env.SHORTLINE_REVIEW_BROWSER_OUTPUT_DIR;
assert.ok(output);mkdirSync(output,{recursive:true});let origin,browser,page,currentWidth;const violations=[],errors=[],results=[],releases=[],runs=[];let phase="startup";
const server=createServer((req,res)=>{if(req.method!=='GET'||req.headers.host!==new URL(origin).host||req.url.startsWith('/api')){violations.push('escaped '+req.url);res.writeHead(403).end();return;}
 const file=path.resolve(dist,req.url==='/daily-review'?'index.html':req.url.slice(1));if(!file.startsWith(dist+path.sep)||!existsSync(file)){res.writeHead(404).end();return;}
 let bytes=readFileSync(file);const ext=path.extname(file);if(ext==='.html')bytes=Buffer.from(bytes.toString().replace(/<link\b(?=[^>]*\brel=["'](?:preconnect|dns-prefetch)["'])[^>]*>/gi,'').replace(/<link\b(?=[^>]*\bhref=["']https?:\/\/)[^>]*>/gi,''));res.setHeader('content-type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[ext]||'application/octet-stream');res.end(bytes);});
const waitGate=async promise=>{let timer;try{await Promise.race([promise,new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('expected request not entered')),10000))]);}finally{clearTimeout(timer);}};
const gate=()=>{let resolve;const promise=new Promise(r=>resolve=r);const g={promise,resolve};releases.push(resolve);return g;};
try{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({headless:true,args:['--disable-background-networking','--dns-prefetch-disable']});
 for(const width of [1440,390]){
  currentWidth=width;const context=await browser.newContext({viewport:{width,height:1000},serviceWorkers:'block'}),base=createFixture(origin,{withSealQuality:true,fullReview:true}),f=createShortlineFixture(origin);
  let holdGeneration=null,holdVersion=null;const requests=[];runs.push({width,requests,fixture:f,base});
  await context.routeWebSocket('**/*',ws=>{violations.push('websocket');ws.close();});
  await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(u.origin!==origin){violations.push('external '+req.url());return route.abort();}
   requests.push({method:req.method(),path:u.pathname,search:u.search});
   let body;if(req.method()==='POST'){try{body=req.postDataJSON();}catch{}}
   const own=f.handle(req.url(),req.method(),body),r=own||base.handle(req.url(),req.method(),body);
   if(r.kind==='deny')return route.abort();if(r.kind==='static')return route.continue();
   try{
    if(r.kind==='stream'){
     const hold=holdGeneration;holdGeneration=null;if(hold){hold.entered.resolve();await hold.release.promise;if(hold.cancelled)return route.abort();}
     r.commit();return route.fulfill({contentType:'application/x-ndjson',body:r.body});
    }
    if(own&&u.pathname.startsWith('/api/shortline-review/version/')&&holdVersion){const h=holdVersion;holdVersion=null;h.entered.resolve();await h.release.promise;}
    return route.fulfill({status:r.status||200,json:r.body});
   }catch(e){if(!/closed|cancel|handled|interception/i.test(String(e)))throw e;}
  });
  await context.addInitScript(()=>{localStorage.clear();localStorage.setItem('vr-llm',JSON.stringify({provider:'cli-codex',baseURL:'',apiKey:'',model:'SYNTHETIC_OFFLINE'}));});
  page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.clock.setFixedTime(new Date(CLOCK));await page.goto(origin+'/daily-review',{waitUntil:'domcontentloaded'});
  const card=page.getByTestId('shortline-segmented-review'),inspect=card.getByRole('button',{name:'查看生成材料',exact:true}),generate=()=>card.getByRole('button',{name:/^手动生成/});
  phase='open actual short-history disclosure';
  await page.locator('#market-detail-short-history > summary').click();
  await card.waitFor();await card.getByText('暂无已保存版本',{exact:true}).waitFor({state:'attached'});
  const shot=async name=>{await card.evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));const geometry=await card.evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth,text:el.innerText}));assert.ok(geometry.scroll<=geometry.width+1);await page.screenshot({path:path.join(output,`${width}-${name}.png`),fullPage:false});results.push({width,name,geometry});};
  const generateComplete=async()=>{const r=await observedBrowserAction(()=>page.waitForResponse(r=>r.request().method()==='POST'&&r.url()===origin+'/api/shortline-review/generate'),()=>generate().click());assert.equal(r.status(),200);const id=r.request().postDataJSON().generation_id;await card.getByText('版本'+id.slice(0,8),{exact:false}).waitFor();return id;};
  phase='empty preview';f.setScenario('empty');await inspect.click();await card.getByText('本次材料范围',{exact:false}).waitFor();assert.equal(await generate().isDisabled(),true);assert.equal(f.calls.filter(x=>x.method==='POST').length,0);await shot('empty-no-model');
  phase='partial generation';f.setScenario('partial');await inspect.click();await card.getByText('DRAGON_TIGER:MISSING:2026-07-31',{exact:false}).first().waitFor();await generateComplete();await card.getByText('材料不足，未生成',{exact:false}).waitFor();await card.getByText('事实核验未执行',{exact:false}).waitFor();assert.equal(f.saved.size,1);await shot('partial-unverified');
  phase='daily generation and cancellation';f.setScenario('daily');await inspect.click();await card.getByText('本次材料范围',{exact:false}).waitFor();
  const h={entered:gate(),release:gate(),cancelled:true};holdGeneration=h;await generate().click();await waitGate(h.entered.promise);
  await card.getByRole('button',{name:'取消当前分段任务',exact:true}).click();await card.getByRole('alert').getByText('已请求取消',{exact:false}).waitFor();h.release.resolve();assert.equal(f.saved.size,1);await shot('cancel-no-confirmed-version');
  phase='cancelled task requires explicit material reread';
  assert.equal(await generate().isDisabled(),true,'cancelled replacement has no owned preview');
  assert.equal(await card.getByText('本次材料范围',{exact:false}).count(),0,'cleared preview must not be reused silently');
  assert.equal(f.calls.filter(x=>x.method==='POST').length,2,'partial and cancelled attempts only before manual reread');
  await inspect.click();await card.getByText('材料身份：'+golden.daily.preview.bundle_id,{exact:true}).waitFor();
  assert.equal(await generate().isDisabled(),false,'explicit current material read permits a new attempt');
  assert.equal(f.calls.filter(x=>x.method==='POST').length,2,'reread never generates');
  await generateComplete();await card.getByText('事实核验未执行',{exact:false}).waitFor();assert.equal(f.saved.size,2);assert.equal(await card.locator('section').count(),6);await shot('daily-five-and-summary');
  const daily=[...f.saved.values()].find(v=>v.mode==='daily'&&v.stages.every(s=>s.status!=='skipped'));assert.ok(daily);
  phase='malformed saved version';f.malformedNext();await card.getByLabel('选择复盘版本').selectOption(daily.generation_id);await card.getByRole('alert').getByText('版本身份或内容无法核对',{exact:false}).waitFor();await shot('malformed-history-rejected');
  await card.getByLabel('选择复盘版本').selectOption('');await card.getByLabel('选择复盘版本').selectOption(daily.generation_id);await card.getByText('事实核验未执行',{exact:false}).waitFor();
  await card.getByLabel('选择复盘版本').selectOption('');const cleared={entered:gate(),release:gate()};holdVersion=cleared;
  await card.getByLabel('选择复盘版本').selectOption(daily.generation_id);await waitGate(cleared.entered.promise);
  await card.getByLabel('选择复盘版本').selectOption('');
  await observedBrowserAction(()=>page.waitForResponse(r=>r.url()===origin+'/api/shortline-review/version/'+daily.generation_id),()=>cleared.release.resolve());
  await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  assert.equal(await card.getByLabel('选择复盘版本').inputValue(),'','cleared version must not be reselected by late detail');await shot('clear-history-owns-selection');
  await card.getByLabel('选择复盘版本').selectOption('');const hv={entered:gate(),release:gate()};holdVersion=hv;await card.getByLabel('选择复盘版本').selectOption(daily.generation_id);await waitGate(hv.entered.promise);
  phase='weekly late-version ownership';f.setScenario('weekly');await card.getByLabel('复盘类型').selectOption('weekly');await card.getByRole('button',{name:'手动生成（最多4次）',exact:true}).waitFor();await page.waitForFunction(()=>{const c=document.querySelector('[data-testid=shortline-segmented-review]');return c?.querySelector('select[aria-label=复盘类型]')?.value==='weekly'&&c.querySelectorAll('section').length===0;});hv.release.resolve();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));assert.equal(await card.locator('section').count(),0,'old daily result cannot own weekly context');
  await inspect.click();await card.getByText('本次材料范围',{exact:false}).waitFor();await generateComplete();await card.getByText('事实核验未执行',{exact:false}).waitFor();assert.equal(await card.locator('section').count(),4);assert.equal(f.saved.size,3);await shot('weekly-three-and-summary');
  assert.equal(f.calls.filter(x=>x.method==='POST').length,4,'partial,cancel,daily,weekly are the only explicit generation attempts');assert.deepEqual(f.violations,[]);assert.deepEqual(base.violations,[]);assert.deepEqual(base.writes,[]);await context.close();page=null;
 }
 assert.deepEqual(violations,[]);assert.deepEqual(errors,[]);
}catch(e){errors.push(String(e));process.exitCode=1;await captureBrowserFailure({page,output,prefix:String(currentWidth||'startup'),selector:'[data-testid=shortline-segmented-review]',error:e,audit:{phase,violations,errors,runs:runs.map(r=>({width:r.width,requests:r.requests,shortlineViolations:r.fixture.violations,baseViolations:r.base.violations}))}});console.error(e);}
finally{for(const release of releases)release();writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:!process.exitCode,scope:'full production page with strict synthetic API streams; real API/store golden parity separate; no model calls',results,violations,errors,phase,runs:runs.map(r=>({width:r.width,requests:r.requests,shortlineViolations:r.fixture.violations,baseViolations:r.base.violations}))},null,2));await browser?.close();await new Promise(r=>server.close(r));}
