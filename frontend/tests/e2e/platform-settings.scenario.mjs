import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';import {join} from 'node:path';
import {readReply} from './ai-settings-storage.fixture.mjs';
import {platformFixture,CONTACT} from './platform-settings.fixture.mjs';
export async function platformScenario(browser,baseURL,width,evidenceDir){
 const f=platformFixture(),errors=[],external=[],unexpected=[],captures=[];let context,page,hold;
 const holds=[];
 const newHold=()=>{let entered,release,reject;const started=new Promise((r,j)=>{entered=r;reject=j;}),promise=new Promise(r=>release=r);const timer=setTimeout(()=>{errors.push('synthetic hold expired');reject(Error('expected read did not settle within bound'));release();},10000);const h={started,entered,promise,release:()=>{clearTimeout(timer);release();}};holds.push(h);return h;};
 const shot=async name=>{const card=page.getByTestId('platform-settings-card');await card.scrollIntoViewIfNeeded();await card.screenshot({path:join(evidenceDir,`platform-${width}-${name}.png`)});captures.push(name);};
 try{
  context=await browser.newContext({baseURL,viewport:{width,height:960},serviceWorkers:'block'});
  await context.routeWebSocket('**/*',s=>{external.push('websocket');s.close();});
  await context.route('**/*',async route=>{
   const r=route.request(),u=new URL(r.url()),method=r.method();
   if(method==='GET'&&r.resourceType()==='stylesheet'&&u.href==='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap')return route.fulfill({contentType:'text/css',body:''});
   if(u.origin!==baseURL){external.push(u.href);return route.abort();}if(!u.pathname.startsWith('/api/'))return route.continue();
   let body;if(r.postData()){try{body=r.postDataJSON();}catch{unexpected.push('invalid JSON');return route.abort();}}
   const reply=f.handle(method,u.pathname,u.search,body);
   if(reply){const h=hold;if(h&&u.pathname==='/api/settings/platform'&&method==='GET'){hold=null;h.entered();await h.promise;}return route.fulfill({status:reply.status,json:reply.body});}
   const ancillary=readReply(method,u.pathname,u.search);if(ancillary)return route.fulfill({json:ancillary});unexpected.push(method+' '+u.pathname+u.search);return route.abort();
  });
  page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));await page.clock.setFixedTime(new Date('2026-10-12T12:00:00Z'));await page.goto('/settings');
  const card=page.getByTestId('platform-settings-card'),field=card.getByTestId('sec-contact-draft'),save=card.getByRole('button',{name:'保存联系方式',exact:true}),reload=card.getByRole('button',{name:'重新读取状态',exact:true}),check=card.getByRole('button',{name:'手动检查正式版本',exact:true});
  const status=text=>card.getByRole('status').filter({hasText:text});
  const writes=()=>f.calls.filter(c=>c.method==='PUT').length;
  await status('读取设置失败，请重新读取').waitFor();assert.equal(await field.isDisabled(),true);assert.equal(await save.isDisabled(),true);assert.equal(writes(),0);await shot('initial-read-failure');
  f.readFailure=false;hold=newHold();const initialHold=hold;await reload.click();await initialHold.started;assert.equal(await field.isDisabled(),true);assert.equal(writes(),0);initialHold.release();await field.waitFor();await reload.click({trial:true});assert.equal(await field.isEnabled(),true);
  await field.fill(CONTACT);hold=newHold();const dirtyHold=hold;await reload.click();await dirtyHold.started;assert.equal(await field.inputValue(),CONTACT);assert.equal(await save.isDisabled(),true);dirtyHold.release();await reload.click({trial:true});await status('输入草稿保留').waitFor();assert.equal(await field.inputValue(),CONTACT);assert.equal(writes(),0);await shot('dirty-read-retained');
  f.writeMode='conflict';await save.evaluate(el=>{el.click();el.click();});await status('保存未确认').waitFor();assert.equal(writes(),1);assert.equal(await field.inputValue(),CONTACT);assert.equal(await save.isDisabled(),true);await shot('conflict-retained');
  await reload.click();await status('输入草稿保留').waitFor();await reload.click({trial:true});assert.equal(await field.inputValue(),CONTACT);
  f.writeMode='malformed';await save.click();await status('保存未确认').waitFor();assert.equal(writes(),2);assert.equal(await field.inputValue(),CONTACT);assert.equal(await save.isDisabled(),true);await shot('malformed-ack-retained');
  await reload.click();await status('输入草稿保留').waitFor();await reload.click({trial:true});assert.equal(await field.inputValue(),CONTACT);f.writeMode='normal';await save.click();await status('本地设置已保存并回读确认').waitFor();assert.equal(writes(),3);assert.equal(await field.inputValue(),'');await shot('saved-confirmed');
  await page.reload();await card.getByText('联系方式：已配置（不显示姓名和邮箱）',{exact:true}).waitFor();assert.equal(await field.inputValue(),'');assert.equal(await save.isDisabled(),true);assert.equal(writes(),3);
  const before=f.calls.filter(c=>c.method==='POST').length;assert.equal(before,0);await check.evaluate(el=>{el.click();el.click();});await status('更新检查未确认').waitFor();assert.equal(f.calls.filter(c=>c.method==='POST').length,1);await shot('update-malformed');
  f.updateMode='normal';await check.click();await card.getByText('有新的正式版本',{exact:false}).waitFor();assert.equal(f.calls.filter(c=>c.method==='POST').length,2);assert.equal(await card.getByRole('link',{name:'查看官方发布说明'}).getAttribute('href'),'https://github.com/guilaile95/Vibe-Research/releases/tag/v0.1.4');assert.equal(writes(),3);await shot('update-confirmed');
  assert.deepEqual(f.violations,[]);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(unexpected,[]);
  return {scenario:'platform-settings',width,status:'PASS',calls:f.calls,captures,boundary:'Synthetic contact only; intercepted local API; no real contact storage or GitHub/SEC call'};
 }catch(e){await shot('failure').catch(()=>{});if(page)writeFileSync(join(evidenceDir,`platform-${width}-failure.html`),await page.content().catch(()=>''));return{scenario:'platform-settings',width,status:'FAIL',error:String(e),calls:f.calls,captures,violations:f.violations,errors,external,unexpected};}
 finally{for(const h of holds)h.release();await context?.close();}
}
