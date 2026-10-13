import assert from 'node:assert/strict';
const stages = ['profile', 'financials', 'estimates', 'valuation', 'risk', 'report'];
const H = 'a'.repeat(64), B = 'b'.repeat(32), R = 'c'.repeat(32);
export async function runCompanyResearch({ page, baseUrl, fillCode, clickQuery, waitForStockHeader }) {
  let captures = 0, generations = 0;
  const bundle = {schema_version:'company_research.v1',classification:'PUBLIC_ADAPTER_INPUT_UNVERIFIED',bundle_id:B,bundle_sha256:H,subject:{market:'A',symbol:'000001'},captured_at:'2026-10-12T00:00:00Z',limitations:['Synthetic fixture'],sources:[{evidence_id:'facts',source:'synthetic fixture',status:'AVAILABLE',captured_at:'2026-10-12T00:00:00Z',source_as_of:null,payload_sha256:H,stages,payload:{value:0},scope:'fixture'}]};
  await page.addInitScript(() => localStorage.setItem('vr-llm', JSON.stringify({provider:'deepseek',model:'synthetic',baseURL:'https://fixture.example',apiKey:'synthetic'})));
  await page.route('**/api/company-research/**', async route => {
    const p = new URL(route.request().url()).pathname;
    if (p.endsWith('/capture')) { captures++; assert.equal(route.request().postDataJSON().confirm_public_fetch,true); return route.fulfill({json:{data:bundle}}); }
    if (p.endsWith('/generate')) {
      generations++; assert.equal(route.request().postDataJSON().expected_bundle_sha256,H);
      const outputs=[]; const events=[{type:'run_started',run_id:R,bundle_sha256:H,subject:bundle.subject,max_model_calls:6}];
      for (const stage of stages) { events.push({type:'stage_started',run_id:R,stage}); const output={stage,summary:'Synthetic research draft',evidence_ids:['facts'],gaps:['Not verified'],output_sha256:H,input_bundle_sha256:H,previous_stage_hashes:outputs.map(x=>x.output_sha256),source_gaps:[],classification:'NON_AUTHORITATIVE_AI_DRAFT',numeric_claim_verification:'NOT_EVALUATED'}; outputs.push(output); events.push({type:'stage_done',run_id:R,stage,output}); }
      events.push({type:'done',record:{schema_version:'company_research.v1',run_id:R,bundle_id:B,bundle_sha256:H,subject:bundle.subject,status:'COMPLETED',started_at:'2026-10-12T00:00:00Z',finished_at:'2026-10-12T00:00:00Z',stages:outputs,completed_stage_count:6,model:{provider:'fixture',name:'fixture'},result_sha256:H,classification:'NON_AUTHORITATIVE_AI_DRAFT',numeric_claim_verification:'NOT_EVALUATED'}});
      return route.fulfill({contentType:'application/x-ndjson',body:events.map(x=>JSON.stringify(x)).join('\n')+'\n'});
    }
    throw new Error(`Unexpected company research request ${p}`);
  });
  await page.goto(`${baseUrl}/stock-data`); await fillCode(page,'000001'); await clickQuery(page); await waitForStockHeader(page,'000001','平安银行');
  const panel = page.getByTestId('company-research'); await panel.locator('summary').first().click();
  assert.equal(captures,0); assert.equal(generations,0);
  await panel.getByRole('button',{name:'采集并冻结公开资料（不调用模型）',exact:true}).click();
  await panel.getByText(`资料包 ${B} · SHA256 ${H}`,{exact:true}).waitFor(); assert.equal(captures,1); assert.equal(generations,0);
  page.once('dialog', dialog => dialog.dismiss()); await panel.getByRole('button',{name:'确认预算并开始六阶段研究',exact:true}).click(); assert.equal(generations,0);
  page.once('dialog', dialog => dialog.accept()); await panel.getByRole('button',{name:'确认预算并开始六阶段研究',exact:true}).click();
  await panel.getByText(`六阶段流程完成，事实与数字仍未核验 · ${R}`,{exact:true}).waitFor(); assert.equal(generations,1); assert.equal(await panel.locator('section').count(),6);
  await page.setViewportSize({width:390,height:844}); await panel.getByRole('button',{name:'保存完整草稿到研究记录',exact:true}).click(); await panel.getByRole('button',{name:'已保存到研究记录',exact:true}).waitFor();
}
