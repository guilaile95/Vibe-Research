// Production UI, isolated browser storage and intercepted synthetic API only.
// No application/backend/model process is started; unknown network requests fail closed.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createReadStream,readFileSync,existsSync,mkdtempSync,writeFileSync,mkdirSync} from 'node:fs';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join,resolve,extname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {config,chatKey,readReply} from './ai-settings-storage.fixture.mjs';
const dist=resolve(fileURLToPath(new URL('../../dist/',import.meta.url)));
const evidence=process.env.WORKFLOW_RECOVERY_EVIDENCE_DIR||mkdtempSync(join(tmpdir(),'vr-workflow-recovery-'));
mkdirSync(evidence,{recursive:true});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const server=createServer((req,res)=>{
 const path=new URL(req.url,'http://localhost').pathname;
 if(path.startsWith('/api/')){res.writeHead(503).end('Unmocked request');return;}
 let file=resolve(dist,`.${decodeURIComponent(path)}`);
 if(!file.startsWith(dist+sep)&&file!==dist){res.writeHead(403).end();return;}
 if(!existsSync(file)||!extname(file))file=join(dist,'index.html');
 res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(file)]||'application/octet-stream');createReadStream(file).pipe(res);
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const baseURL=`http://127.0.0.1:${server.address().port}`;
let browser;const results=[];
const git=ref=>execFileSync('git',['rev-parse',ref],{cwd:resolve(dist,'..'),encoding:'utf8'}).trim();
const provenance={checkoutHead:git('HEAD'),checkoutTree:git('HEAD^{tree}'),frontendSourceTree:git('HEAD:frontend/src'),pullRequestHead:process.env.WORKFLOW_RECOVERY_PR_HEAD||null};
try{
 assert.ok(existsSync(join(dist,'index.html')),'Build frontend first');
 browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{})});
 for(const width of [1440,390])for(const scenario of ['chat-recovery','decision-race','revision-identity']){
  const context=await browser.newContext({baseURL,viewport:{width,height:960},serviceWorkers:'block'});const errors=[],unexpected=[],external=[],requests=[];const release=deferred();const started=deferred();let chatCount=0;
  await context.addInitScript(({config,chatKey,scenario})=>{if(!sessionStorage.getItem('recovery-initialized')){localStorage.clear();localStorage.setItem('vr-llm',JSON.stringify(config));if(scenario==='chat-recovery')localStorage.setItem(chatKey,'{CORRUPT_SYNTHETIC_ARCHIVE');sessionStorage.setItem('recovery-initialized','1')}},{config,chatKey,scenario});
  await context.routeWebSocket('**/*',socket=>{external.push(socket.url());socket.close()});
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin==='https://fonts.googleapis.com')return route.fulfill({contentType:'text/css',body:''});
   if(url.origin!==baseURL){external.push(url.origin);return route.abort()}
   if(!url.pathname.startsWith('/api/'))return route.continue();
   requests.push(`${request.method()} ${url.pathname}${url.search}`);
   if(scenario==='chat-recovery'&&url.pathname==='/api/chat'&&request.method()==='POST'){
    const body=request.postDataJSON();assert.equal(body.report_ids[0],'synthetic-report');assert.equal(body.messages.at(-1).content,'SYNTHETIC_SHORT_QUESTION');chatCount++;
    return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'delta',text:'Z'.repeat(80001)})+'\n'+JSON.stringify({type:'done',trace:[],rounds:1})+'\n'});
   }
   if(scenario==='decision-race'&&url.pathname==='/api/decision-evidence'&&request.method()==='GET'){
    const code=url.searchParams.get('code');if(!code){started.resolve();await release.promise}
    return route.fulfill({json:{items:[{id:code?'NEW-SYNTHETIC':'OLD-SYNTHETIC',code:code||'000001',trade_date:'2026-10-20'}],total:1}});
   }
   if(scenario==='revision-identity'&&url.pathname.startsWith('/api/thesis/')&&request.method()==='GET'){
    if(url.pathname==='/api/thesis/A/revisions/1')return route.fulfill({json:{revision_number:1,change_summary:'SYNTHETIC-REVISION-A',created_at:null,snapshot:{thesis:{title:'SYNTHETIC-REVISION-A',core_claims:[],catalysts:[],risks:[],invalidation_conditions:[]},evidence_links:[],evidences:[]}}});
    if(url.pathname==='/api/thesis/B/revisions/2'){started.resolve();await release.promise;return route.fulfill({status:404,json:{detail:'Synthetic revision missing'}})}
   }
   const reply=readReply(request.method(),url.pathname,url.search);if(reply)return route.fulfill({json:reply});
   unexpected.push(`${request.method()} ${url.pathname}${url.search}`);return route.fulfill({status:503,json:{detail:'UNEXPECTED_SYNTHETIC_REQUEST'}});
  });
  const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  try{
   if(scenario==='chat-recovery'){
    const open=async()=>{await page.getByRole('checkbox',{name:'选择 Synthetic report',exact:true}).check();await page.getByRole('button',{name:'基于所选资料提问（1）',exact:true}).click();await page.getByPlaceholder('询问 Vibe...').waitFor()};
    await page.goto('/my-reports');await open();const panel=page.locator('aside[aria-label="Vibe AI 对话"]');
    await panel.getByRole('alert').filter({hasText:'存档损坏'}).waitFor();assert.equal(await page.evaluate(key=>localStorage.getItem(key),chatKey),'{CORRUPT_SYNTHETIC_ARCHIVE');
    const original=panel.getByRole('link',{name:'导出原始存档'});assert.equal(decodeURIComponent((await original.getAttribute('href')).split(',')[1]),'{CORRUPT_SYNTHETIC_ARCHIVE');const download=page.waitForEvent('download');await original.click();assert.equal(readFileSync(await (await download).path(),'utf8'),'{CORRUPT_SYNTHETIC_ARCHIVE');
    await panel.getByRole('button',{name:'清空损坏存档'}).click();assert.equal(await page.evaluate(key=>localStorage.getItem(key),chatKey),null);
    const old=JSON.stringify([{role:'user',content:'SYNTHETIC_OLD_Q'},{role:'assistant',content:'SYNTHETIC_OLD_A'}]);await page.evaluate(({key,raw})=>localStorage.setItem(key,raw),{key:chatKey,raw:old});await page.reload();await open();
    const input=page.getByPlaceholder('询问 Vibe...');await input.fill('x'.repeat(80001));await panel.getByRole('button',{name:'发送',exact:true}).click();await panel.getByText(/问题超过 80000 字符/).waitFor();assert.equal((await input.inputValue()).length,80001);assert.equal(chatCount,0);
    await input.fill('SYNTHETIC_SHORT_QUESTION');await panel.getByRole('button',{name:'发送',exact:true}).click();await panel.getByRole('alert').filter({hasText:'超长回答未写入'}).waitFor();assert.equal(chatCount,1);assert.equal(await page.evaluate(key=>localStorage.getItem(key),chatKey),old);
    const exported=await panel.getByRole('link',{name:'导出当前对话'}).getAttribute('href');assert.equal(JSON.parse(decodeURIComponent(exported.split(',')[1])).at(-1).content.length,80001);
    assert.ok((await panel.innerText()).includes('Z'.repeat(100)));assert.ok((await panel.innerText()).includes('SYNTHETIC_OLD_A'));
   }else if(scenario==='decision-race'){
    await page.goto('/decision-evidence');await started.promise;await page.getByPlaceholder('如 600519').fill('600519');await page.getByText('NEW-SYNTHETIC',{exact:true}).waitFor();const oldResponse=page.waitForResponse(r=>r.url().includes('/api/decision-evidence?')&&!r.url().includes('code='));release.resolve();await oldResponse;await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));assert.equal(await page.getByText('OLD-SYNTHETIC',{exact:true}).count(),0);assert.equal(await page.getByText('NEW-SYNTHETIC',{exact:true}).count(),1);
   }else{
    await page.goto('/thesis/A/revision/1');await page.getByText('SYNTHETIC-REVISION-A',{exact:true}).first().waitFor();await page.evaluate(()=>{history.pushState({},'', '/thesis/B/revision/2');window.dispatchEvent(new PopStateEvent('popstate'))});await started.promise;assert.equal(await page.getByText('SYNTHETIC-REVISION-A',{exact:true}).count(),0);const newResponse=page.waitForResponse(r=>r.url().includes('/api/thesis/B/revisions/2'));release.resolve();await newResponse;await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));assert.equal(await page.getByText('SYNTHETIC-REVISION-A',{exact:true}).count(),0);
   }
   assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);assert.deepEqual(external,[]);await page.screenshot({path:join(evidence,`${scenario}-${width}.png`),fullPage:false});results.push({scenario,width,status:'PASS',requests});console.log(`[RECOVERY] ${scenario} ${width} PASS`);
  }catch(error){results.push({scenario,width,status:'FAIL',error:error.message,errors,unexpected,external,requests});await page.screenshot({path:join(evidence,`${scenario}-${width}-failure.png`)}).catch(()=>{});throw error}
  finally{release.resolve();await context.close()}
 }
}finally{writeFileSync(join(evidence,'results.json'),JSON.stringify({...provenance,results},null,2));await browser?.close();server.closeAllConnections();await new Promise(done=>server.close(done))}
