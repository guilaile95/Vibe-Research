/** Rendered UI contract smoke with fixture responses; no external provider/model. */
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { chromium } from 'playwright';
const server = await createServer({ server:{host:'127.0.0.1',port:0}, logLevel:'error' });
await server.listen();
const port = server.httpServer.address().port;
const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {})});
try {
  const page = await browser.newPage();
  const evidence = {id:'e1', edit_token:'token', source_title:'报告原文', claim:'收入增长'};
  let reviews = []; let binds = 0; let judgments = 0;
  await page.route('**/api/research-events/reviews**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET') {
      if (path.endsWith('campaign-a')) await new Promise(resolve => setTimeout(resolve,300));
      return route.fulfill({json:{data:{thesis:{id:'t1',title:path.endsWith('campaign-a')?'旧选择逻辑':'当前逻辑',current_revision:4}, evidence:[evidence],reviews}}});
    }
    const body = request.postDataJSON();
    if (path.endsWith('/judgment')) {
      judgments++; assert.equal(body.expected_version,1); assert.equal(body.outcome,'support');
      assert.deepEqual(body.evidence,[{id:'e1',edit_token:'token'}]);
      reviews = [{...reviews[0], status:'support', version:2,judgment:{reason:body.reason, evidence:[evidence],reviewed_at:'2026-10-19T00:00:00Z'}}];
    } else {
      binds++; assert.equal(body.campaign_id,'campaign-b'); assert.equal(body.observation_receipt,'receipt');
      reviews = [{id:'r1',campaign_id:body.campaign_id,thesis_id:body.thesis_id,thesis_revision:4,expectation:body.expectation,observation:{event_id:'event-1'},observation_hash:'hash',version:1,status:'review_required',judgment:null}];
    }
    return route.fulfill({json:{data:reviews[0]}});
  });
  await page.goto(`http://127.0.0.1:${port}/tests/e2e/event-review-harness.html`);
  await page.getByText('绑定研究预期 / 事件复核',{exact:true}).click();
  await page.getByLabel('选择复核 Campaign').selectOption('campaign-a');
  await page.getByLabel('选择复核 Campaign').selectOption('campaign-b');
  await page.getByText(/正式绑定逻辑：当前逻辑/).waitFor();
  await page.waitForTimeout(400);
  assert.equal(await page.getByText(/旧选择逻辑/).count(),0);
  await page.getByLabel('待验证预期').fill('本期收入同比增长');
  await page.getByRole('button',{name:'明确绑定此事件版本并待复核'}).click();
  await page.getByLabel('复核结论').selectOption('support');
  await page.getByRole('checkbox').check();
  await page.getByLabel('复核说明').fill('报告原文与预期一致');
  await page.getByRole('button',{name:'确认并保存不可改写的判断'}).click();
  await page.getByText('支持预期 · 已确认，不可改写').waitFor();
  await page.getByRole('button',{name:'重新读取逻辑与证据'}).click();
  await page.getByText('支持预期 · 已确认，不可改写').waitFor();
  assert.equal(binds,1); assert.equal(judgments,1);
  assert.equal(await page.getByLabel('复核结论').count(),0);
  console.log('PASS rendered explicit bind → evidence review → immutable judgment → refresh; late Campaign context ignored');
} finally { await browser.close(); await server.close(); }
