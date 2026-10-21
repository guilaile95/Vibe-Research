/** Full built pages; registered-API synthetic archive goldens. Never a real provider/model browser. */
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {captureBrowserFailure} from './browser-failure-evidence.mjs';
import {createExtendedPageFixture,marketGolden,companyGolden,failureGolden,missingGolden,researchGolden,subjects,syntheticStoredLlm,CLOCK,CUTOFF} from './extended-page.fixture.mjs';
if(process.env.CI!=='true')throw Error('Browser execution is CI-only');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),dist=path.join(root,'dist');
const output=process.env.EXTENDED_PUBLIC_BROWSER_OUTPUT_DIR;assert.ok(output);mkdirSync(output,{recursive:true});
let origin,browser,page,width,phase='startup';const runs=[],errors=[],violations=[],captures=[];
const server=createServer((req,res)=>{
 const u=new URL(req.url,origin);
 if(req.method!=='GET'||req.headers.host!==new URL(origin).host||u.pathname.startsWith('/api')){violations.push('escaped '+req.url);res.writeHead(403).end();return;}
 const file=path.resolve(dist,['/daily-review','/stock-data'].includes(u.pathname)?'index.html':u.pathname.slice(1));
 if(!file.startsWith(dist+path.sep)||!existsSync(file)){res.writeHead(404).end();return;}
 let bytes=readFileSync(file);const ext=path.extname(file);
 if(ext==='.html')bytes=Buffer.from(bytes.toString().replace(/<link\b(?=[^>]*\brel=["'](?:preconnect|dns-prefetch)["'])[^>]*>/gi,'').replace(/<link\b(?=[^>]*\bhref=["']https?:\/\/)[^>]*>/gi,''));
 res.setHeader('content-type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[ext]||'application/octet-stream');res.end(bytes);
});
// Hold fetch delivery after the HTTP response, not the network: late completion must
// be rejected by the production owner's serial, including a previously unmounted card.
function observer(){
 const original=window.fetch.bind(window);window.__archiveReads=[];window.__archiveHolds=[];window.__holdArchives=[];
 window.fetch=async(input,init)=>{
  const u=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.origin);
  if(u.origin!==location.origin||!u.pathname.startsWith('/api/public-research/'))return original(input,init);
  const key=u.pathname+u.search,record={key,parsed:false};window.__archiveReads.push(record);
  const response=await original(input,init),json=response.json.bind(response);response.json=async()=>{const value=await json();record.parsed=true;return value;};
  const i=window.__holdArchives.indexOf(key);if(i>=0){window.__holdArchives.splice(i,1);await new Promise(resolve=>window.__archiveHolds.push({key,record,resolve}));}
  return response;
 };
}
try{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({headless:true,args:['--disable-background-networking','--dns-prefetch-disable']});
 for(width of [1440,390]){
  const context=await browser.newContext({viewport:{width,height:1000},serviceWorkers:'block'}),fixture=createExtendedPageFixture(origin);runs.push({width,fixture});
  await context.routeWebSocket('**/*',ws=>{violations.push('websocket');ws.close();});
  await context.route('**/*',async route=>{const req=route.request();let body;if(req.method()==='POST'){try{body=req.postDataJSON();}catch{}}
   const reply=fixture.handle(req.url(),req.method(),body);if(reply.kind==='deny')return route.abort();if(reply.kind==='static')return route.continue();
   return reply.kind==='stream'?route.fulfill({contentType:'application/x-ndjson',body:reply.body}):route.fulfill({status:reply.status||200,json:reply.body});
  });
  await context.addInitScript(llm=>{localStorage.clear();localStorage.setItem('vr-llm',JSON.stringify(llm));},syntheticStoredLlm);
  await context.addInitScript(observer);page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.clock.setFixedTime(new Date(CLOCK));
  const settle=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  const shot=async(card,name)=>{await card.evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));await settle();const bounds=await card.boundingBox();assert.ok(bounds);const text=await card.innerText();await page.screenshot({path:path.join(output,`${width}-${name}.png`),clip:{x:Math.max(0,bounds.x),y:Math.max(0,bounds.y),width:Math.min(bounds.width,width-Math.max(0,bounds.x)),height:Math.min(bounds.height,1000-Math.max(0,bounds.y))}});captures.push({width,name,text});};
  const hold=key=>page.evaluate(key=>window.__holdArchives.push(key),key);
  const held=key=>page.waitForFunction(key=>window.__archiveHolds.some(h=>h.key===key),key);
  const release=async key=>{await page.evaluate(key=>{const h=window.__archiveHolds.find(h=>h.key===key);if(!h)throw Error('missing held read');h.resolve();},key);await page.waitForFunction(key=>window.__archiveHolds.find(h=>h.key===key)?.record.parsed,key);await settle();};
  const archiveCount=()=>fixture.calls.filter(c=>c.path.startsWith('/api/public-research/')).length;
  const posts=()=>fixture.calls.filter(c=>c.method==='POST');
  const market=()=>page.getByRole('region',{name:'指数估值利率研究归档',exact:true});
  const ready=async(card,value)=>{
   const name=await card.getAttribute('aria-label'),headers=value.blocks.map(b=>`${b.label} · ${b.subject} · ${b.status}${b.archive_stale?' · 归档陈旧':''}`);
   if(value.turnover)headers.push('沪深两市成交额近60个交易日');
   await page.waitForFunction(({name,headers})=>{const c=[...document.querySelectorAll('section[aria-label]')].find(c=>c.getAttribute('aria-label')===name);return c&&JSON.stringify([...c.querySelectorAll('article h4')].map(h=>h.textContent))===JSON.stringify(headers);},{name,headers});
   await card.getByText('合成案例：非真实市场数据',{exact:true}).waitFor();await card.getByRole('status').getByText(value.status+' · '+value.message,{exact:true}).waitFor();assert.equal(await card.locator('article h4').count(),headers.length);assert.equal(value.ingestion_enabled,false);assert.equal(value.schedule_enabled,false);
  };
  phase='DailyReview current explicit archive read';await page.goto(origin+'/daily-review',{waitUntil:'domcontentloaded'});await page.locator('#market-detail-short-history > summary').click();await market().waitFor();assert.equal(archiveCount(),0);
  await market().getByRole('button',{name:'读取来源归档',exact:true}).click();await ready(market(),marketGolden['2026-07-31']);await shot(market(),'current-market-partial-synthetic');assert.equal(posts().length,0);
  phase='DailyReview historical identity and close reopen';await page.getByRole('tab',{name:'历史复盘',exact:true}).click();
  const openHistory=day=>page.getByRole('row').filter({has:page.getByRole('cell',{name:day,exact:true})}).getByRole('button',{name:'查看',exact:true}).click();
  await openHistory('2026-07-30');await market().getByRole('button',{name:'读取来源归档',exact:true}).click();await ready(market(),marketGolden['2026-07-30']);await shot(market(),'history-market');
  await page.getByRole('button',{name:'关闭',exact:true}).click();await market().waitFor({state:'detached'});await openHistory('2026-07-30');await market().getByRole('button',{name:'读取来源归档',exact:true}).click();await ready(market(),marketGolden['2026-07-30']);
  const old='/api/public-research/market-context?as_of=2026-07-30';await hold(old);await market().getByRole('button',{name:'重读研究原料',exact:true}).click();await held(old);
  phase='late historical response cannot own new snapshot';await openHistory('2026-07-29');
  // Wait for the new snapshot owner, not just the history-row click. Detail loading
  // temporarily unmounts this card, so a count() before readiness races the fetch.
  await market().getByText('截止日 2026-07-29 · 只读已有归档，不联网采集或调用模型',{exact:true}).waitFor();
  const read=market().getByRole('button',{name:'读取来源归档',exact:true});if(await read.count())await read.click();
  await ready(market(),marketGolden['2026-07-29']);await release(old);assert.match(await market().innerText(),/截止日 2026-07-29/);assert.doesNotMatch(await market().innerText(),/@2026-07-30/);await shot(market(),'late-history-owned');
  phase='real failed receipt and missing archive';fixture.setNext(failureGolden['2026-07-29']);await market().getByRole('button',{name:'重读研究原料',exact:true}).click();await ready(market(),failureGolden['2026-07-29']);await market().getByText('暂无合格记录；缺失不作为零值',{exact:true}).waitFor();assert.equal(await market().locator('article').first().locator('table').count(),0);assert.match(await market().innerText(),/缺失：.*em_market_trend/);await shot(market(),'raw-failure-missing-sources');
  fixture.setNext(missingGolden['2026-07-29']);await market().getByRole('button',{name:'重读研究原料',exact:true}).click();await market().getByRole('status').getByText(missingGolden['2026-07-29'].status+' · '+missingGolden['2026-07-29'].message,{exact:true}).waitFor();assert.equal(await market().locator('article').count(),1,'only unknown turnover session grid remains');assert.match(await market().innerText(),/20日均额 未知 · 60日均额 未知/);await shot(market(),'missing-market');
  await page.getByRole('button',{name:'关闭',exact:true}).click();await page.getByRole('tab',{name:'当前市场',exact:true}).click();await page.locator('#market-detail-short-history > summary').click();
  await market().getByRole('button',{name:'读取来源归档',exact:true}).click();await ready(market(),marketGolden['2026-07-31']);assert.equal(posts().length,0);
  for(const [m,symbol] of subjects){
   phase=`StockData ${m}:${symbol} explicit date and qualified archive`;await page.goto(`${origin}/stock-data?code=${symbol}`,{waitUntil:'domcontentloaded'});
   const card=page.getByRole('region',{name:'公司原始来源归档',exact:true});await card.getByRole('heading',{name:`${m} ${symbol} 财务与预期原料`,exact:true}).waitFor();
   const before=archiveCount();assert.equal(await page.getByLabel('原料研究截止日',{exact:true}).inputValue(),'');await card.getByRole('button',{name:'读取来源归档',exact:true}).click();await card.getByText('先选择有效研究日期；不使用系统今天替代缺失业务日',{exact:true}).waitFor();assert.equal(archiveCount(),before);
   await page.getByLabel('原料研究截止日',{exact:true}).fill(CUTOFF);await ready(card,companyGolden[m]);await shot(card,`${m}-company-raw-qualified`);
   const bad=structuredClone(companyGolden[m]);const financial=bad.blocks.find(b=>b.source_id.includes('financials'));financial.rows[0].period_months=8;fixture.setNext(bad);
   await card.getByRole('button',{name:'重读研究原料',exact:true}).click();await card.getByRole('alert').getByText('归档读取或来源合同校验失败，请重试',{exact:true}).waitFor();assert.equal(await card.locator('article').count(),0);await shot(card,`${m}-invalid-fiscal-blocked`);
   await card.getByRole('button',{name:'重读研究原料',exact:true}).click();await ready(card,companyGolden[m]);
   const late=structuredClone(companyGolden[m]);late.blocks.find(b=>b.source_id.includes('financials')).rows[0].notice_date='2026-10-01';fixture.setNext(late);
   await card.getByRole('button',{name:'重读研究原料',exact:true}).click();await card.getByRole('alert').waitFor();assert.equal(await card.locator('article').count(),0);await shot(card,`${m}-after-cutoff-values-blocked`);
   await card.getByRole('button',{name:'重读研究原料',exact:true}).click();await ready(card,companyGolden[m]);
   phase=`${m} archive bundle to six actual stages`;const panel=page.getByTestId('company-research');await panel.locator('summary').first().click();await panel.getByLabel('研究归档截止日',{exact:true}).fill(CUTOFF);
   const generate=panel.getByRole('button',{name:'确认预算并开始六阶段研究',exact:true});assert.equal(await generate.isDisabled(),true);
   const start=posts().length;fixture.expectResearch(m,'capture');await panel.getByRole('button',{name:'采集并冻结公开资料（不调用模型）',exact:true}).click();const g=researchGolden[m];await panel.getByText(`资料包 ${g.bundle.bundle_id} · SHA256 ${g.bundle.bundle_sha256}`,{exact:true}).waitFor();assert.equal(posts().length,start+1);
   for(const source of g.bundle.sources.filter(s=>s.source==='immutable_public_source_archive'&&s.status==='AVAILABLE')){assert.ok((await panel.innerText()).includes(source.evidence_id));assert.ok((await panel.innerText()).includes(source.payload.source_artifact_hash));}
   await shot(panel,`${m}-frozen-source-qualified-bundle`);page.once('dialog',d=>d.dismiss());await generate.click();assert.equal(posts().length,start+1);
   fixture.expectResearch(m,'generate');page.once('dialog',d=>d.accept());await generate.click();const done=g.events.at(-1).record;await panel.getByText(`六阶段流程完成，事实与数字仍未核验 · ${done.run_id}`,{exact:true}).waitFor();assert.equal(await panel.locator('section').count(),6);assert.equal(posts().length,start+2);await shot(panel,`${m}-six-stage-unverified-result`);
   if(m==='US'){
    phase='failed raw quote stays a gap through full six-stage UI';const failed=researchGolden['US-failed'];fixture.expectResearch('US-failed','capture');await panel.getByRole('button',{name:'采集并冻结公开资料（不调用模型）',exact:true}).click();await panel.getByText(`资料包 ${failed.bundle.bundle_id} · SHA256 ${failed.bundle.bundle_sha256}`,{exact:true}).waitFor();
    assert.match(await panel.innerText(),/global_quote_ref.*ERROR/);fixture.expectResearch('US-failed','generate');page.once('dialog',d=>d.accept());await generate.click();await panel.getByText(`六阶段流程完成，事实与数字仍未核验 · ${failed.events.at(-1).record.run_id}`,{exact:true}).waitFor();assert.match(await panel.innerText(),/global_quote_ref:ERROR/);await shot(panel,'US-failed-quote-explicit-stage-gaps');
    phase='late US archive cannot replace HK selection';const oldCompany='/api/public-research/company-inputs?as_of='+CUTOFF+'&market=US&symbol=AAPL';await hold(oldCompany);await card.getByRole('button',{name:'重读研究原料',exact:true}).click();await held(oldCompany);
    const input=page.getByPlaceholder('A 股 6 位代码，或美股/港股/韩股（AAPL / 00700 / 005930.KS）');await input.fill('00700');await input.press('Enter');await card.getByRole('heading',{name:'HK 00700 财务与预期原料',exact:true}).waitFor();assert.equal(await page.getByLabel('原料研究截止日',{exact:true}).inputValue(),'');await page.getByLabel('原料研究截止日',{exact:true}).fill(CUTOFF);await card.getByRole('button',{name:'读取来源归档',exact:true}).click();await ready(card,companyGolden.HK);await release(oldCompany);assert.doesNotMatch(await card.innerText(),/US:AAPL|US AAPL/);assert.match(await card.innerText(),/HK:00700/);await shot(card,'late-US-cannot-own-HK');
   }
  }
  phase=`${width} completed scenarios: strict request audit`;
  assert.equal(posts().length,8,'three qualified plus one failed-quote archive freeze/stream pair, each explicit');assert.deepEqual(fixture.expectedPosts,[]);assert.deepEqual(fixture.violations,[]);assert.deepEqual(fixture.base.violations,[]);assert.deepEqual(fixture.base.writes,[]);await context.close();page=null;
 }
 assert.deepEqual(errors,[]);assert.deepEqual(violations,[]);
}catch(error){errors.push(String(error));process.exitCode=1;await captureBrowserFailure({page,output,prefix:String(width||'startup'),selector:'[aria-label="指数估值利率研究归档"], [aria-label="公司原始来源归档"], [data-testid="company-research"]',error,audit:{phase,violations,errors,runs:runs.map(({width,fixture:f})=>({width,requests:f.calls,violations:f.violations,baseViolations:f.base.violations}))}});console.error(error);}
finally{writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:!process.exitCode,scope:'Built DailyReview and StockData, exact synthetic registered API goldens; no live provider/model; browser only runs in CI',phase,captures,errors,violations,runs:runs.map(({width,fixture:f})=>({width,requests:f.calls,violations:f.violations,baseViolations:f.base.violations}))},null,2));await browser?.close();await new Promise(r=>server.close(r));}
