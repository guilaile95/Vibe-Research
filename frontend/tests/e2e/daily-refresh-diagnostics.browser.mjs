// Production bundle, synthetic intercepted API only; no backend or provider calls.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createReadStream, existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { ancillaryReply } from './final-families.fixture.mjs';
import { readReply } from './ai-settings-storage.fixture.mjs';
const dist = fileURLToPath(new URL('../../dist/', import.meta.url));
const evidence = mkdtempSync(join(tmpdir(), 'vr-daily-refresh-ui-'));
const server = createServer((req,res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  if(path.startsWith('/api/')) return res.writeHead(503).end();
  let file = resolve(dist, `.${path}`);
  if(!file.startsWith(resolve(dist)+sep) && file!==resolve(dist)) return res.writeHead(403).end();
  if(!existsSync(file)||!extname(file)) file=join(dist,'index.html');
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(file)]||'application/octet-stream');
  createReadStream(file).pipe(res);
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const baseURL=`http://127.0.0.1:${server.address().port}`;
const attempt={state:'failed',started_at:'2026-10-31 14:00:00',finished_at:'2026-10-31 14:03:30',reason_code:'SOURCE_TIMEOUT',failed_sources:['emotion'],pending_sources:['breadth']};
const record={source_id:'daily_review',module:'每日复盘',display_name:'每日复盘',status:'normal',is_stale:true,observed_at:'2026-09-22T08:47:30Z',last_success_at:'2026-09-22T08:47:30Z',data_trade_date:'2026-09-22',data_cutoff:null,stale_after_seconds:300,is_cached:true,is_degraded:false,coverage_current:8,coverage_expected:8,last_error_code:null,last_error_summary:null,last_error_at:null,blocks_advice:false,block_reason:null,detail_path:'/daily-review',refresh_attempt:attempt};
const results=[];let browser;
try {
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{})});
 for(const width of [1440,390]) {
  const context=await browser.newContext({baseURL,viewport:{width,height:1000},serviceWorkers:'block'});
  const errors=[],external=[],writes=[];let posts=0, release;
  const pending=new Promise(r=>release=r);
  await context.routeWebSocket('**/*',socket=>{external.push(socket.url());socket.close()});
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.origin==='https://fonts.googleapis.com') return route.fulfill({contentType:'text/css',body:''});
   if(url.origin!==baseURL){external.push(url.origin);return route.abort()}
   if(!url.pathname.startsWith('/api/')) return route.continue();
   if(req.method()!=='GET') writes.push(`${req.method()} ${url.pathname}`);
   if(url.pathname==='/api/daily-review/refresh'){posts++;await pending;return route.fulfill({status:503,json:{detail:'关键市场数据暂不可用，本次刷新未完成',refresh_attempt:attempt}})}
   if(url.pathname==='/api/data-health')return route.fulfill({json:{overall_status:'normal',blocks_advice:false,block_reasons:[],summary:{normal:1,partial:0,unavailable:0,stale:1,not_initialized:0},items:[record]}});
   if(url.pathname==='/api/daily-review') {const value=ancillaryReply('GET',url.pathname);value.data.generated_at='2026-09-22 16:47:30';value.cache_meta={source:'persisted',stale:true,refreshing:false,refresh_failed:true,refresh_error:'刷新失败',refresh_attempt:null};return route.fulfill({json:value})}
   const reply=readReply(req.method(),url.pathname,url.search)||ancillaryReply(req.method(),url.pathname,url.search);
   if(reply)return route.fulfill({json:reply});
   return route.fulfill({status:503,json:{detail:'SYNTHETIC_UNAVAILABLE'}});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  try {
   await page.goto('/data-health');await page.getByLabel('最近刷新尝试').waitFor();
   await page.getByRole('button',{name:'重新读取健康状态',exact:true}).click();
   assert.equal(posts,0);assert.match(await page.getByLabel('最近刷新尝试').innerText(),/SOURCE_TIMEOUT/);
   await page.screenshot({path:join(evidence,`health-${width}.png`)});
   await page.getByRole('link',{name:'每日复盘刷新数据',exact:true}).click();
   const button=page.getByTestId('daily-review-refresh');await button.waitFor();
   await button.click();assert.equal(await button.isDisabled(),true);await button.evaluate(el=>{el.click();el.click()});
   release();await page.getByLabel('最近刷新尝试').waitFor();
   assert.equal(posts,1);assert.match(await page.getByLabel('最近刷新尝试').innerText(),/未完成组件：市场广度/);
   assert.match(await page.locator('body').innerText(),/2026-09-22 16:47:30/);
   assert.equal(await button.isDisabled(),false);
   assert.deepEqual(writes,['POST /api/daily-review/refresh']);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
   await page.screenshot({path:join(evidence,`daily-${width}.png`)});results.push({width,status:'PASS'});
  } finally {release();await context.close()}
 }
} finally {await browser?.close();server.closeAllConnections();await new Promise(done=>server.close(done));writeFileSync(join(evidence,'results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({results,evidence}))}
