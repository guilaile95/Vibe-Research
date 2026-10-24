import assert from 'node:assert/strict';
import {readFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {ancillaryReply} from './final-families.fixture.mjs';
import {readReply} from './ai-settings-storage.fixture.mjs';

export async function runNoteGeneration(browser, frontend) {
  for (const width of [1440,390]) {
    const context=await browser.newContext({viewport:{width,height:960},serviceWorkers:'block'});
    const external=[],writes=[],unavailable=[],errors=[];
    await context.routeWebSocket('**/*',socket=>{external.push(socket.url());socket.close()});
    const generation={schemaVersion:'note-generation.v1',resultType:'daily_review_ai',resultSchemaVersion:'daily_review_ai.v1',tradeDate:'2026-10-08',generatedAt:'2026-10-21T08:00:00Z',modelProvider:'synthetic',modelName:'fixture',sourceReviewGeneratedAt:'2026-10-21T07:00:00Z',sourceDataCutoff:null,staleAtSave:true};
    await context.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      if(request.method()==='GET' && url.href==='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap')return route.fulfill({contentType:'text/css',body:''});
      if(url.origin!==frontend){external.push(url.origin);return route.abort()}
      if(!url.pathname.startsWith('/api/'))return route.continue();
      if(request.method()!=='GET'){writes.push(`${request.method()} ${url.pathname}`);return route.abort()}
      if(url.pathname==='/api/ai-results/daily_review_ai')return route.fulfill({json:{data:{result_type:generation.resultType,schema_version:generation.resultSchemaVersion,trade_date:generation.tradeDate,generated_at:generation.generatedAt,model_provider:generation.modelProvider,model_name:generation.modelName,stale:true,payload:{markdown:'新原文不变',source_review_generated_at:generation.sourceReviewGeneratedAt,source_data_cutoff:null}}}});
      if(url.pathname==='/api/daily-review/history')return route.fulfill({json:{data:{items:[],count:0,limit:20,offset:0}}});
      const reply=ancillaryReply(request.method(),url.pathname,url.search)??readReply(request.method(),url.pathname,url.search);
      if(reply!==null)return route.fulfill({json:reply});
      unavailable.push(`${request.method()} ${url.pathname}${url.search}`);return route.fulfill({status:503,json:{detail:'Synthetic unavailable read'}});
    });
    let page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`${frontend}/daily-review`);
    const review=page.getByTestId('today-ai-review');await review.locator('summary').click();
    await review.getByText('新原文不变',{exact:true}).waitFor();
    await review.getByRole('button',{name:'存入沉淀',exact:true}).click();
    await review.getByRole('button',{name:'已存入沉淀',exact:true}).waitFor();
    const saved=await page.evaluate(()=>(JSON.parse(localStorage.getItem("vr-notes.v2") || "null")?.notes ?? JSON.parse(localStorage.getItem("vr-notes") || "[]"))[0]);
    assert.deepEqual(saved.generation,generation);assert.equal(saved.research,undefined);assert.equal(saved.content,'新原文不变');
    await page.close();page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`${frontend}/notes`);await page.getByRole('button',{name:/每日复盘 2026-10-08/}).click();
    await page.getByTestId('note-generation').waitFor();
    const notes=[{id:'old',kind:'问AI',title:'旧单股',content:'旧原文',ts:1,research:{securityCode:'600000'}},saved];
    await page.evaluate(notes=>{localStorage.removeItem('vr-notes.v2');localStorage.setItem('vr-notes',JSON.stringify(notes));},notes);await page.reload();
    await page.getByRole('button',{name:/每日复盘 2026-10-08/}).click();
    await page.getByTestId('note-generation').locator('summary').click();
    await page.getByText(/原结果可能已被替换或删除/).waitFor();
    await page.getByText(/非服务唯一 ID/).waitFor();
    await page.getByText('新原文不变',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    if(process.env.NOTE_GENERATION_EVIDENCE_DIR){mkdirSync(process.env.NOTE_GENERATION_EVIDENCE_DIR,{recursive:true});await page.screenshot({path:join(process.env.NOTE_GENERATION_EVIDENCE_DIR,`note-generation-${width}.png`)});}
    const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出备份',exact:true}).click();
    const path=await (await downloading).path();const backup=JSON.parse(readFileSync(path,'utf8'));assert.equal(backup.schema_version,'vibe-notes.backup.v2');assert.deepEqual(backup.notes,notes);
    await page.evaluate(()=>{localStorage.removeItem('vr-notes.v2');localStorage.removeItem('vr-notes');});await page.reload();
    await page.getByTestId('notes-backup-input').setInputFiles(path);
    await page.getByRole('status').getByText('已导入 2 条研究记录。',{exact:true}).waitFor();
    assert.deepEqual(await page.evaluate(()=>(JSON.parse(localStorage.getItem("vr-notes.v2") || "null")?.notes ?? JSON.parse(localStorage.getItem("vr-notes") || "[]"))),[notes[1],notes[0]]);
    await page.getByRole('button',{name:/旧单股/}).click();await page.getByText(/历史记录未保存此信息/).waitFor();
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
    console.log('note generation synthetic browser audit',JSON.stringify({width,writes,external,unavailable}));
    await context.close();
  }
}
