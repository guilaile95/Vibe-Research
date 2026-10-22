import assert from 'node:assert/strict';
import {readFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';

export async function runNoteGeneration(browser, frontend) {
  for (const width of [1440,390]) {
    const context=await browser.newContext({viewport:{width,height:960},serviceWorkers:'block'});
    await context.route('**/*',route=>new URL(route.request().url()).origin===frontend ? route.continue() : route.abort());
    const page=await context.newPage();
    const generation={schemaVersion:'note-generation.v1',resultType:'daily_review_ai',resultSchemaVersion:'daily_review_ai.v1',tradeDate:'2026-10-21',generatedAt:'2026-10-21T08:00:00Z',modelProvider:'synthetic',modelName:'fixture',sourceReviewGeneratedAt:'2026-10-21T07:00:00Z',sourceDataCutoff:null,staleAtSave:true};
    const notes=[{id:'old',kind:'问AI',title:'旧单股',content:'旧原文',ts:1,research:{securityCode:'600000'}},{id:'new',kind:'复盘',title:'合成原结果',content:'新原文不变',ts:2,generation}];
    await page.goto(`${frontend}/notes`);
    await page.evaluate(notes=>localStorage.setItem('vr-notes',JSON.stringify(notes)),notes);await page.reload();
    await page.getByRole('button',{name:/合成原结果/}).click();
    await page.getByTestId('note-generation').locator('summary').click();
    await page.getByText(/原结果可能已被替换或删除/).waitFor();
    await page.getByText(/非服务唯一 ID/).waitFor();
    await page.getByText('新原文不变',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    if(process.env.NOTE_GENERATION_EVIDENCE_DIR){mkdirSync(process.env.NOTE_GENERATION_EVIDENCE_DIR,{recursive:true});await page.screenshot({path:join(process.env.NOTE_GENERATION_EVIDENCE_DIR,`note-generation-${width}.png`)});}
    const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出备份',exact:true}).click();
    const path=await (await downloading).path();const backup=JSON.parse(readFileSync(path,'utf8'));assert.equal(backup.schema_version,'vibe-notes.backup.v2');assert.deepEqual(backup.notes,notes);
    await page.evaluate(()=>localStorage.removeItem('vr-notes'));await page.reload();
    await page.getByTestId('notes-backup-input').setInputFiles(path);
    await page.getByRole('status').getByText('已导入 2 条研究记录。',{exact:true}).waitFor();
    assert.deepEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('vr-notes'))),[notes[1],notes[0]]);
    await page.getByRole('button',{name:/旧单股/}).click();await page.getByText(/历史记录未保存此信息/).waitFor();
    await context.close();
  }
}
