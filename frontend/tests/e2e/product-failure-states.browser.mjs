// Production build, fresh browser contexts, intercepted synthetic HTTP only. No backend/model.
import assert from 'node:assert/strict';
import {createReadStream,existsSync,mkdtempSync,mkdirSync,writeFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {resolve,join,extname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {storedCredential,credentialStatus} from './credential-generation.fixture.mjs';
import {ancillaryReply} from './final-families.fixture.mjs';
import {readReply} from './ai-settings-storage.fixture.mjs';
const dist=resolve(fileURLToPath(new URL('../../dist/',import.meta.url)));
const evidence=process.env.FAILURE_STATES_EVIDENCE_DIR||mkdtempSync(join(tmpdir(),'vr-product-failures-'));
mkdirSync(evidence,{recursive:true});
const server=createServer((req,res)=>{
 let file=resolve(dist,`.${decodeURIComponent(new URL(req.url,'http://localhost').pathname)}`);
 if(!file.startsWith(dist+sep)&&file!==dist){res.writeHead(403).end();return}
 if(!existsSync(file)||!extname(file))file=join(dist,'index.html');
 res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(file)]||'application/octet-stream');createReadStream(file).pipe(res);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const baseURL=`http://127.0.0.1:${server.address().port}`;
const success={artifact_id:'synthetic-original',mode:'CURRENT',scope:'all',status:'SUCCESS',core_trends:'SYNTHETIC_ORIGINAL_RESULT',sentiment_controversy:'',signals:'',rss_insights:'SYNTHETIC_RSS_CONTENT',outlook_strategy:'',standalone_summaries:{},counts:{total_news:2,analyzed_news:1,max_news_limit:1,hotlist_count:1,rss_count:1,hotlist_analyzed:1,rss_analyzed:0,standalone_analyzed:0},provider:'synthetic',model:'offline',cached:false,generated_at:'2026-10-20T01:02:03Z',disclaimer:''};
const rssSnapshot=reason=>({version:1,status:'CAPTURED',submission_status:'RESPONSE_RECEIVED',items:[],coverage:{hotlist:{enabled:true,available:0,included:0,omitted:0,reason:'no_items'},rss:{enabled:reason!=='disabled',available:reason==='no_items'?0:1,included:0,omitted:reason==='no_items'?0:1,reason},standalone:{enabled:false,available:null,included:0,omitted:null,reason:'disabled'}}});
const defer=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const model={provider:'cli-codex',model:'SYNTHETIC_OFFLINE'};
const results=[];let browser;
try{
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{})});
 for(const width of [1440,390])for(const scenario of ['watch','ai']){
  const context=await browser.newContext({baseURL,viewport:{width,height:960},serviceWorkers:'block'});const errors=[],writes=[],external=[],unavailable=[];let watchMode='slow',aiMode='error',calls=0;let pending=defer();
  await context.addInitScript(value=>localStorage.setItem('vr-llm',JSON.stringify(value)),storedCredential(model));
  await context.routeWebSocket('**/*',ws=>{external.push(ws.url());ws.close()});
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(request.method()==='GET'&&request.url()==='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap')return route.fulfill({contentType:'text/css',body:''});
   if(url.origin!==baseURL){external.push(url.origin);return route.abort()}
   if(!url.pathname.startsWith('/api/'))return route.continue();
   if(request.method()!=='GET')writes.push(`${request.method()} ${url.pathname}`);
   if(url.pathname==='/api/watchlist'&&request.method()==='GET'){
    if(watchMode==='slow'){await pending.promise;return route.fulfill({status:503,json:{detail:'Synthetic unavailable'}})}
    if(watchMode==='error')return route.fulfill({status:503,json:{detail:'Synthetic unavailable'}});
    if(watchMode==='parse')return route.fulfill({contentType:'application/json',body:'{INVALID'});
    if(watchMode==='corrupt')return route.fulfill({json:{data:{status:'corrupted',data:null,etag:null}}});
    return route.fulfill({json:{data:{status:'valid',data:{codes:watchMode==='empty'?[]:['600519'],updated_at:'synthetic'},etag:'1111111111111111'}}});
   }
   if(url.pathname==='/api/native-intel/ai/analysis'&&request.method()==='POST'){
    calls++;if(aiMode==='slow'){await pending.promise;return route.fulfill({json:success})}
    if(aiMode==='parse')return route.fulfill({contentType:'application/json',body:'{INVALID'});
    if(aiMode==='network')return route.abort();
    if(aiMode==='error')return route.fulfill({json:{...success,status:'ERROR',core_trends:'UNTRUSTED_FAILED_CONTENT'}});
    return route.fulfill({json:{...success,counts:{...success.counts,rss_analyzed:aiMode==='included'?1:0},...(['disabled','no_items','budget_exhausted'].includes(aiMode)?{input_sources:rssSnapshot(aiMode)}:{})}});
   }
   if(url.pathname==='/api/ai/credential-status')return route.fulfill({json:credentialStatus(model)});
   if(['/api/native-intel/hotlist','/api/native-intel/filter/items','/api/native-intel/standalone'].includes(url.pathname))return route.fulfill({json:{status:'normal',items:[],sources:[],filter_meta:{status:'OK'}}});
   if(url.pathname==='/api/native-intel/config')return route.fulfill({json:{region_order:['ai_analysis'],regions_enabled:{hotlist:false,rss:false,standalone:false,ai_analysis:true}}});
   if(url.pathname==='/api/daily-review/history')return route.fulfill({json:{data:{items:[],count:0,limit:20,offset:0}}});
   const reply=ancillaryReply(request.method(),url.pathname,url.search)||readReply(request.method(),url.pathname,url.search);
   if(reply)return route.fulfill({json:reply});
   unavailable.push(`${request.method()} ${url.pathname}`);return route.fulfill({status:503,json:{detail:'Synthetic unavailable'}});
  });
  const page=await context.newPage();page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
  try{
   if(scenario==='watch'){
    await page.goto('/daily-review');const state=page.getByTestId('today-watch-list-state');await state.getByText('正在读取关注清单…').waitFor();assert.equal(await page.getByText('还没有关注股票，可从市场发现挑选研究对象。').count(),0);pending.resolve();await state.getByRole('alert').waitFor();
    const retry=state.getByRole('button',{name:'重新读取关注清单'});
    for(const mode of ['parse','corrupt']){watchMode=mode;await retry.click();await state.getByRole('alert').waitFor();assert.equal(await page.getByText('还没有关注股票，可从市场发现挑选研究对象。').count(),0)}
    watchMode='empty';await retry.click();await page.getByText('还没有关注股票，可从市场发现挑选研究对象。').waitFor();
    watchMode='valid';await retry.click();await page.locator('#today-watch-600519').waitFor();const href=await page.locator('#today-watch-600519 a').getAttribute('href');assert.equal(new URL(href,baseURL).searchParams.get('return_to'),'/daily-review#today-watch-600519');
    watchMode='error';await retry.click();await state.getByRole('alert').waitFor();await state.getByText(/上次确认的旧清单/).waitFor();assert.equal(await page.locator('#today-watch-600519').count(),1);assert.equal(await page.getByPlaceholder('加自选：可批量，如 600519 000858').isDisabled(),true);assert.deepEqual(writes,[]);
   }else{
    await page.goto('/intel');await page.getByRole('button',{name:/实时热榜/}).click();const region=page.getByTestId('display-region-ai_analysis');await region.waitFor();const generate=region.getByTestId('wave5-generate-ai-analysis');
    for(const mode of ['error','parse','network']){aiMode=mode;await generate.click();await region.getByText('本次未完成分析',{exact:true}).waitFor();assert.equal(await region.getByTestId('wave5-section-core_trends').count(),0);assert.doesNotMatch(await region.innerText(),/暂无异常|暂无显著|UNTRUSTED_FAILED_CONTENT/)}
    aiMode='success';await generate.click();await region.getByText('SYNTHETIC_ORIGINAL_RESULT',{exact:true}).waitFor();await region.getByTestId('wave5-tab-rss_insights').click();await region.getByText(/本次未分析RSS/).waitFor();assert.equal(await region.getByText('SYNTHETIC_RSS_CONTENT',{exact:true}).count(),0);
    for(const reason of ['disabled','no_items','budget_exhausted']){aiMode=reason;await generate.click();await region.getByTestId('wave5-section-rss_insights').getByText(/本次未分析RSS/).waitFor();assert.equal(await region.getByText('SYNTHETIC_RSS_CONTENT',{exact:true}).count(),0)}
    aiMode='error';await generate.click();await region.getByTestId('wave5-ai-previous-result').waitFor();assert.match(await region.getByTestId('wave5-ai-previous-result').innerText(),/2026-10-20T01:02:03Z.*synthetic-original/);
    aiMode='included';await generate.click();await region.getByText('SYNTHETIC_RSS_CONTENT',{exact:true}).waitFor();assert.equal(await region.getByTestId('wave5-ai-previous-result').count(),0);
    const before=calls;aiMode='slow';const slowStarted=page.waitForRequest(r=>r.url().endsWith('/api/native-intel/ai/analysis'));await generate.click();await slowStarted;assert.equal(await generate.isDisabled(),true);await generate.evaluate(button=>{button.click();button.click()});assert.equal(calls,before+1);pending.resolve();await page.waitForFunction(()=>!document.querySelector('[data-testid="wave5-generate-ai-analysis"]').disabled);assert.equal(calls,before+1);
    pending=defer();const lateStarted=page.waitForRequest(r=>r.url().endsWith('/api/native-intel/ai/analysis'));await generate.click();await lateStarted;await page.getByTestId('hotlist-mode-interests').click();await region.getByText('当前时段尚未生成 AI 宏观研报').waitFor();const lateResponse=page.waitForResponse(r=>r.url().endsWith('/api/native-intel/ai/analysis'));pending.resolve();await lateResponse;await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));assert.equal(await region.getByText('SYNTHETIC_ORIGINAL_RESULT',{exact:true}).count(),0);
    assert.ok(writes.every(x=>x==='POST /api/native-intel/ai/analysis'));
   }
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);await page.screenshot({path:join(evidence,`${scenario}-${width}.png`)});results.push({scenario,width,status:'PASS',calls,unavailable});console.log('PASS',scenario,width);
  }catch(error){console.error({errors,unavailable});await page.screenshot({path:join(evidence,`${scenario}-${width}-failure.png`)}).catch(()=>{});throw error}
  finally{pending.resolve();await context.close()}
 }
}finally{writeFileSync(join(evidence,'results.json'),JSON.stringify({results},null,2));await browser?.close();server.closeAllConnections();await new Promise(r=>server.close(r));console.log('Evidence:',evidence)}
