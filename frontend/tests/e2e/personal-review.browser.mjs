/** CI-only mocked-API browser acceptance of the production review components.
 * Real temporary-SQLite API/numeric tests live in backend/tests/test_personal_review.py.
 * This is not real-market or browser-to-real-database acceptance. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "playwright";
if (process.env.CI !== "true") throw new Error("Actual-browser acceptance is CI-only; local browser launch is not authorized");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const temporary = process.env.PERSONAL_REVIEW_BROWSER_OUTPUT_DIR || mkdtempSync(path.join(tmpdir(), "personal-review-browser-"));
mkdirSync(temporary, { recursive: true });
const bundled = await build({ stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client'; import {MemoryRouter} from 'react-router-dom'; import {PersonalReviewPanel} from './src/components/personal-review/PersonalReviewPanel'; const trade={trade_id:'${"a".repeat(32)}',executed_at:'2026-07-21T02:00:00Z',execution_status:'full'};createRoot(document.getElementById('root')).render(<MemoryRouter><main style={{padding:16,maxWidth:1100,margin:'auto'}}><PersonalReviewPanel/><PersonalReviewPanel trade={trade}/></main></MemoryRouter>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "esm", platform: "browser", tsconfig: path.join(root, "tsconfig.json"), define: { "process.env.NODE_ENV": '"production"' } });
const js = bundled.outputFiles[0].text;
const css = readdirSync(path.join(root, "dist/assets")).filter(x => x.endsWith(".css")).map(x => readFileSync(path.join(root, "dist/assets", x))).join("\n");
const summary = { requested: 10, closed_count: 0, insufficient_samples: true, money_scored: 0, wins: 0, losses: 0, flat: 0, win_rate_excluding_flat: null, net_pnl: null, self_assessed_count: 0, self_reported_deviations: 0, self_reported_violations: 0 };
const blank = () => ({ schema_version: "personal-review.v1", privacy: "LOCAL_ONLY_EXCLUDED_FROM_MODEL_CONTEXT", as_of: "2026-07-28T00:00:00Z", data_time: null, trade_count: 1, closed_episodes: [], diagnostics: [{ code: null, reason: "OPENING_INVENTORY_UNKNOWN" }], windows: [10,20,50].map(n => ({...summary,requested:n})), patterns: [], risk: { open_episodes: [], equity_reference: null, equity_effective_at: null, equity_confirmation: "UNKNOWN", boundary: "SELF_REPORTED" }, assessment_history: {}, limitations: ["仅本地个人复查；不是正式决策或硬风险。"] });
let origin;
const forbidden = [], errors = [], results = [];
const server = createServer((req, res) => {
  if (req.method !== "GET" || req.headers.host !== new URL(origin).host || !["/", "/app.js", "/app.css"].includes(req.url)) { forbidden.push(`server ${req.method} ${req.url}`); res.writeHead(403).end(); return; }
  res.setHeader("Content-Type", req.url === "/app.js" ? "text/javascript" : req.url === "/app.css" ? "text/css" : "text/html");
  res.end(req.url === "/app.js" ? js : req.url === "/app.css" ? css : '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>');
});
await new Promise(resolve => server.listen(0,"127.0.0.1",resolve)); origin = `http://127.0.0.1:${server.address().port}`;
let browser, activePage, activeWidth;
let status="FAIL";
try {
  browser = await chromium.launch({ headless:true, args:["--disable-background-networking", "--disable-component-update", "--disable-sync"] });
  for (const viewport of [{width:1365,height:900},{width:390,height:844}]) {
    activeWidth=viewport.width;
    let fixture = blank(), writes = [], fail = true, malformedRead = true, assessmentWrites = 0;
    const context = await browser.newContext({ viewport, serviceWorkers:"block" });
    await context.route("**/*", async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== origin) { forbidden.push(req.url()); return route.abort("blockedbyclient"); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname === "/api/personal-review" && req.method() === "GET") { if(malformedRead){malformedRead=false;return route.fulfill({json:{data:{...fixture,windows:null}}});} return route.fulfill({json:{data:fixture}}); }
      if (url.pathname.startsWith("/api/personal-review/assessments/") && req.method() === "PUT") {
        const body = req.postDataJSON(); writes.push(body); assessmentWrites++;
        if (fail) { fail=false; return route.fulfill({status:503,json:{detail:"临时保存失败，请重试"}}); }
        const {revision,...content}=body;
        fixture.assessment_history["a".repeat(32)] = [{revision:revision+1,content,saved_at:"2026-07-28T00:00:00Z",stop_recorded_at:null,classification:"RETROSPECTIVE_SELF_ASSESSMENT"}];
        return route.fulfill({json:{data:assessmentWrites===3?{}:fixture.assessment_history["a".repeat(32)][0]}});
      }
      if (url.pathname.startsWith("/api/personal-review/patterns/") && req.method() === "PUT") {
        const {revision,...content}=req.postDataJSON(); writes.push(content);
        fixture.patterns.push({pattern_id:url.pathname.split("/").at(-1),revision:revision+1,content,saved_at:"2026-07-28T00:00:00Z",effective_from:"2026-07-29",effective_rule:"NEXT_SHANGHAI_CALENDAR_DAY",effective_until:null,statistics:summary});
        return route.fulfill({json:{data:fixture.patterns.at(-1)}});
      }
      forbidden.push(`api ${req.method()} ${url.pathname}`); return route.abort("blockedbyclient");
    });
    const page = await context.newPage(); activePage=page; page.on("pageerror",e=>errors.push(e.message));
    await page.goto(origin);
    const panels=page.getByTestId("personal-review-panel"), overview=panels.nth(0), editor=panels.nth(1);
    await overview.getByRole("alert").waitFor();
    await overview.getByRole("button",{name:"重新加载",exact:true}).click();
    await overview.getByText("期初持仓边界未知",{exact:false}).waitFor();
    assert.match(await overview.innerText(),/净收益 未知/);
    await editor.getByLabel("环境描述（事后自评）").fill("Synthetic after-close environment");
    await editor.getByLabel("判断自评").selectOption("correct");
    await editor.getByLabel("执行自评").selectOption("deviated");
    await editor.getByRole("button",{name:"保存自评修订"}).click();
    await editor.getByRole("alert").getByText("临时保存失败",{exact:false}).waitFor();
    assert.equal(await editor.getByLabel("环境描述（事后自评）").inputValue(),"Synthetic after-close environment");
    await editor.getByRole("button",{name:"保存自评修订"}).click();
    await editor.getByText("自评修订历史（1）",{exact:false}).waitFor();
    assert.equal(writes.filter(w=>w.judgment).length,2);
    await editor.getByLabel("复查笔记",{exact:true}).fill("Synthetic uncertain saved note");
    await editor.getByRole("button",{name:"保存自评修订"}).click();
    await editor.getByText("写入结果待核验",{exact:false}).waitFor();
    assert.equal(await editor.getByRole("button",{name:"保存自评修订"}).isDisabled(),true);
    assert.equal(await editor.getByLabel("复查笔记",{exact:true}).inputValue(),"Synthetic uncertain saved note");
    const writesBeforeReload = writes.length;
    await Promise.all([
      page.waitForResponse(response => response.url() === `${origin}/api/personal-review` && response.request().method() === "GET" && response.status() === 200),
      editor.getByRole("button",{name:"重新加载",exact:true}).click(),
    ]);
    await editor.getByRole("button",{name:"保存自评修订"}).and(editor.locator("button:enabled")).waitFor({state:"visible",timeout:10000});
    await editor.getByText("自评修订历史（1）",{exact:false}).waitFor();
    assert.equal(writes.length,writesBeforeReload,"explicit readback must not repeat an uncertain write");
    assert.equal(await editor.getByRole("button",{name:"保存自评修订"}).isDisabled(),false);
    assert.equal(await editor.getByLabel("复查笔记",{exact:true}).inputValue(),"Synthetic uncertain saved note");
    await overview.getByText("模式卡 · 版本历史与复用",{exact:true}).click();
    for (const [label,value] of [["名称","Synthetic mode"],["适用环境","Synthetic setup"],["入场规则","Synthetic entry"],["退出规则","Synthetic exit"],["失效条件","Synthetic invalidation"]]) await overview.getByLabel(label,{exact:true}).fill(value);
    const patternReads = page.waitForResponse(response => response.url() === `${origin}/api/personal-review` && response.request().method() === "GET" && response.status() === 200);
    const patternWrite = page.waitForResponse(response => response.url().startsWith(`${origin}/api/personal-review/patterns/`) && response.request().method() === "PUT" && response.status() === 200);
    await Promise.all([patternReads,patternWrite,overview.getByRole("button",{name:"发布新版本到本地"}).click()]);
    const savedMode = overview.getByRole("heading",{name:"Synthetic mode v1",exact:true,includeHidden:true});
    await savedMode.waitFor({state:"attached",timeout:10000});
    const modeDisclosure = overview.locator("details").filter({has:overview.getByText("模式卡 · 版本历史与复用",{exact:true})});
    if (!await modeDisclosure.evaluate(element => element.open)) await modeDisclosure.locator(":scope > summary").click();
    await overview.getByRole("heading",{name:"Synthetic mode v1",exact:true}).waitFor();
    await overview.getByRole("button",{name:"复制为新模式草稿"}).click();
    await page.waitForFunction(element => element.value === "Synthetic mode（副本）", await overview.getByLabel("名称",{exact:true}).elementHandle(), {timeout:10000});
    assert.equal(await overview.getByLabel("名称",{exact:true}).inputValue(),"Synthetic mode（副本）");
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
    assert.equal(overflow,false,"review controls fit desktop/mobile viewport");
    await page.screenshot({path:path.join(temporary,`${viewport.width}-review.png`),fullPage:true});
    results.push({viewport,writes:writes.length,unknownBoundary:true,retry:true,history:true,versionReuse:true,malformedReadRecovery:true,malformedWriteDraftRetained:true});
    await context.close(); activePage=null;
  }
  assert.deepEqual(forbidden,[]); assert.deepEqual(errors,[]);
  status="PASS";
  console.log(JSON.stringify({status:"passed",results,evidence:temporary}));
} catch(error) {
  if(activePage){
    await activePage.screenshot({path:path.join(temporary,`${activeWidth}-failure.png`),fullPage:false}).catch(()=>{});
    await activePage.getByTestId("personal-review-panel").nth(1).screenshot({path:path.join(temporary,`${activeWidth}-failure-editor.png`)}).catch(()=>{});
    writeFileSync(path.join(temporary,`${activeWidth}-failure.html`),await activePage.content().catch(()=>""));
    const labels=await activePage.locator("label").evaluateAll(nodes=>nodes.map(label=>({text:label.textContent,htmlFor:label.htmlFor,controls:[...label.querySelectorAll("input,textarea,select")].map(x=>({tag:x.tagName,value:x.value,id:x.id}))}))).catch(()=>[]);
    const aria=await activePage.getByTestId("personal-review-panel").nth(1).ariaSnapshot().catch(()=>"");
    writeFileSync(path.join(temporary,`${activeWidth}-failure-labels.json`),JSON.stringify({error:String(error),labels,aria},null,2));
  }
  throw error;
} finally {
  writeFileSync(path.join(temporary,"results.json"),JSON.stringify({status,results,forbidden,errors},null,2));
  await browser?.close(); await new Promise(resolve=>server.close(resolve));
}
