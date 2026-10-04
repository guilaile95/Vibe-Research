/**
 * 研究记录备份真实浏览器路径：
 * localStorage 记录 → 下载 JSON → 清空浏览器记录 → 导入恢复。
 * 损坏记录 → 原文下载 → 无效/取消/配额失败保留原文 → 确认替换 → 恢复普通合并。
 * 不启动后端，不接触 Owner 数据，也不导出密钥或 AI 对话。
 */

import assert from "node:assert/strict";
import { createReadStream, existsSync, readFileSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = join(fileURLToPath(import.meta.url), "..");
const dist = resolve(here, "../../dist");

function findChromium() {
  const roots = [
    process.env.PLAYWRIGHT_CHROMIUM_PATH,
    join(process.env.LOCALAPPDATA || "", "ms-playwright"),
    join(process.env.HOME || "", ".cache", "ms-playwright"),
  ];
  const candidates = [];
  for (const base of roots) {
    if (!base || !existsSync(base)) continue;
    for (const item of readdirSync(base)) {
      if (!/^chromium(_headless_shell)?-\d+$/.test(item)) continue;
      candidates.push(
        join(base, item, "chrome-win64", "chrome.exe"),
        join(base, item, "chrome-win", "chrome.exe"),
        join(base, item, "chrome-linux", "chrome"),
        join(base, item, "chrome-headless-shell-linux64", "chrome-headless-shell"),
        join(base, item, "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
        join(base, item, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      );
    }
  }
  return candidates.filter((candidate) => existsSync(candidate)).sort().at(-1);
}

function staticServer(directory, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
  };
  const root = resolve(directory);
  const server = createServer((request, response) => {
    let pathname = decodeURIComponent((request.url || "/").split("?")[0]);
    if (pathname === "/") pathname = "/index.html";
    let target = resolve(root, `.${pathname}`);
    if (target !== root && !target.startsWith(`${root}${sep}`)) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }
    if (!existsSync(target) || extname(target) === "") target = join(root, "index.html");
    response.setHeader("Content-Type", mime[extname(target)] || "application/octet-stream");
    createReadStream(target).pipe(response);
  });
  return new Promise((resolveServer, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolveServer(server));
  });
}

async function freePort() {
  const server = createServer();
  const port = await new Promise((resolvePort, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolvePort(server.address().port));
  });
  await new Promise((resolveClose) => server.close(resolveClose));
  return port;
}

async function launchBrowser() {
  const executablePath = findChromium();
  try {
    return await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

let server;
let browser;

try {
  assert.ok(existsSync(join(dist, "index.html")), "dist/index.html 缺失：先运行 npm run build");
  const port = await freePort();
  server = await staticServer(dist, port);
  browser = await launchBrowser();
  const page = await browser.newPage();
  const frontend = `http://127.0.0.1:${port}`;

  await page.goto(`${frontend}/notes`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    localStorage.setItem("vr-notes", JSON.stringify([{
      id: "note-backup-e2e",
      kind: "今日要点",
      title: "备份恢复验证",
      content: "这条研究记录必须可以恢复。",
      ts: 1788426000000,
    }]));
    localStorage.setItem("vr-llm", "SECRET_LLM_CONFIG");
    localStorage.setItem("vr-access-key", "SECRET_ACCESS_KEY");
    localStorage.setItem("vr-askai-chat:test", "SECRET_CHAT_HISTORY");
  });
  await page.reload({ waitUntil: "networkidle" });

  await page.getByText("研究记录只保存在当前浏览器中。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "导出备份", exact: true }).click(),
  ]);
  assert.match(download.suggestedFilename(), /^vibe-research-notes-.*\.json$/);
  const downloadPath = await download.path();
  assert.ok(downloadPath, "浏览器没有产生可读取的研究记录备份");
  const raw = readFileSync(downloadPath, "utf8");
  const payload = JSON.parse(raw);
  assert.equal(payload.schema_version, "vibe-notes.backup.v1");
  assert.equal(payload.notes.length, 1);
  assert.equal(payload.notes[0].title, "备份恢复验证");
  assert.doesNotMatch(raw, /SECRET_LLM_CONFIG|SECRET_ACCESS_KEY|SECRET_CHAT_HISTORY/);

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "清空", exact: true }).click();
  await page.getByText(/还没有记录/).waitFor();

  const input = page.getByTestId("notes-backup-input");
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已导入 1 条研究记录。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();

  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("没有新增记录；1 条记录已存在或超出上限。", { exact: true }).waitFor();
  assert.equal(await page.getByText("备份恢复验证", { exact: true }).count(), 1);

  const corruptedRaw = ' \n{"broken":"原始研究记录\n';
  await page.evaluate((value) => localStorage.setItem("vr-notes", value), corruptedRaw);
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("alert").getByText("本地研究记录格式无效，原始数据已保留", { exact: true }).waitFor();
  assert.equal(await page.getByText(/还没有记录/).count(), 0, "损坏数据不能伪装成空记录");
  assert.equal(await page.getByRole("button", { name: "导出备份", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "导入备份", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "从备份替换损坏记录", exact: true }).isEnabled(), true);

  const [rawDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "下载损坏原始数据", exact: true }).click(),
  ]);
  assert.match(rawDownload.suggestedFilename(), /^vibe-research-notes-corrupted-raw-.*\.txt$/);
  const rawDownloadPath = await rawDownload.path();
  assert.ok(rawDownloadPath);
  assert.deepEqual(readFileSync(rawDownloadPath), Buffer.from(corruptedRaw, "utf8"));
  assert.doesNotMatch(readFileSync(rawDownloadPath, "utf8"), /SECRET_LLM_CONFIG|SECRET_ACCESS_KEY|SECRET_CHAT_HISTORY/);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);

  let unexpectedDialog = false;
  const rejectUnexpectedDialog = (dialog) => { unexpectedDialog = true; void dialog.dismiss(); };
  page.on("dialog", rejectUnexpectedDialog);
  await input.setInputFiles({ name: "invalid.json", mimeType: "application/json", buffer: Buffer.from("not-json") });
  await page.getByRole("alert").getByText("备份文件不是有效的 JSON", { exact: true }).waitFor();
  assert.equal(unexpectedDialog, false, "必须先完成校验再询问替换");
  page.off("dialog", rejectUnexpectedDialog);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);
  await input.setInputFiles([]);
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw, "取消文件选择不得写入");

  page.once("dialog", (dialog) => {
    assert.match(dialog.message(), /备份已校验，共 1 条研究记录/);
    assert.match(dialog.message(), /完全替换/);
    assert.match(dialog.message(), /仅替换研究记录/);
    void dialog.dismiss();
  });
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已取消替换，原始研究记录保持不变。", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);

  await page.evaluate(() => {
    window.__notesOriginalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "vr-notes") throw new DOMException("Synthetic quota failure", "QuotaExceededError");
      return window.__notesOriginalSetItem.call(this, key, value);
    };
  });
  page.once("dialog", (dialog) => dialog.accept());
  await input.setInputFiles(downloadPath);
  await page.getByRole("alert").getByText("浏览器无法保存数据，请检查存储权限或空间", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem("vr-notes")), corruptedRaw);
  assert.equal(await page.getByRole("button", { name: "从备份替换损坏记录", exact: true }).isEnabled(), true);
  await page.evaluate(() => {
    Storage.prototype.setItem = window.__notesOriginalSetItem;
    delete window.__notesOriginalSetItem;
  });

  page.once("dialog", (dialog) => dialog.accept());
  await input.setInputFiles(downloadPath);
  await page.getByRole("status").getByText("已从备份恢复 1 条研究记录，损坏数据已替换。", { exact: true }).waitFor();
  await page.getByText("备份恢复验证", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "从备份替换损坏记录", exact: true }).count(), 0);
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("备份恢复验证", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "导入备份", exact: true }).isEnabled(), true);

  const mergePayload = { ...payload, notes: [
    { ...payload.notes[0], content: "不得覆盖已恢复记录" },
    { ...payload.notes[0], id: "after-recovery", title: "恢复后普通导入", ts: 1788426000001 },
  ] };
  await input.setInputFiles({ name: "merge.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(mergePayload)) });
  await page.getByRole("status").getByText("已导入 1 条研究记录，另有 1 条重复或超出上限。", { exact: true }).waitFor();
  const finalStorage = await page.evaluate(() => ({
    notes: JSON.parse(localStorage.getItem("vr-notes")),
    llm: localStorage.getItem("vr-llm"),
    key: localStorage.getItem("vr-access-key"),
    chat: localStorage.getItem("vr-askai-chat:test"),
  }));
  assert.equal(finalStorage.notes.length, 2);
  assert.equal(finalStorage.notes.find((item) => item.id === "note-backup-e2e").content, payload.notes[0].content);
  assert.equal(finalStorage.llm, "SECRET_LLM_CONFIG");
  assert.equal(finalStorage.key, "SECRET_ACCESS_KEY");
  assert.equal(finalStorage.chat, "SECRET_CHAT_HISTORY");

  // Synthetic Reflection responses exercise the production client and Notes UI.
  await page.evaluate(() => localStorage.setItem("vr-llm", JSON.stringify({provider:"cli-codex", model:"synthetic"})));
  let completeReflection = false;
  await page.route("**/api/reflect", route => route.fulfill({status:200, contentType:"application/x-ndjson", body:
    JSON.stringify({type:"delta", text:"SYNTHETIC_AUDIT"}) + "\n" + (completeReflection ? JSON.stringify({type:"done", content:"SYNTHETIC_AUDIT", truncated:true}) + "\n" : "")
  }));
  await page.getByText("备份恢复验证", {exact:true}).click();
  await page.getByRole("button", {name:"反思审计", exact:true}).click();
  await page.getByRole("alert").filter({hasText:"反思未完整结束"}).waitFor();
  await page.getByText("SYNTHETIC_AUDIT", {exact:true}).waitFor();
  assert.equal(await page.getByRole("button", {name:"把审计结果存为新记录", exact:true}).count(), 0);
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("vr-notes")).length), 2);
  completeReflection = true;
  await page.getByRole("button", {name:"反思审计", exact:true}).click();
  await page.getByRole("button", {name:"把审计结果存为新记录", exact:true}).click();
  await page.getByRole("button", {name:"已存为新记录", exact:true}).waitFor();
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("vr-notes")).length), 3);
  assert.match(await page.evaluate(() => JSON.parse(localStorage.getItem("vr-notes")).find(n=>n.kind==="反思审计").content), /未覆盖全文/);

  // The report archive shares the same research-persistence surface. Use only
  // intercepted synthetic API responses, never a real upload destination.
  let archived = [], uploadedNames = [], rejectSecond = true;
  await page.route("**/api/myreports", async route => {
    if (route.request().method() === "GET") return route.fulfill({json:{data:archived}});
    const body = route.request().postDataJSON();
    uploadedNames.push(body.name);
    if (rejectSecond && body.name === "second.txt") return route.fulfill({status:400,json:{detail:"SYNTHETIC_UPLOAD_REJECTED"}});
    const report={id:body.name,name:body.name,title:body.name,size:1,ts:1,sector_keys:[]};
    archived.push(report);
    await route.fulfill({json:{data:report}});
  });
  for (const width of [1440,390]) {
    archived=[];uploadedNames=[];rejectSecond=true;
    await page.setViewportSize({width,height:900});
    await page.goto(`${frontend}/my-reports`, {waitUntil:"networkidle"});
    const upload=page.locator('input[type="file"]');
    await upload.setInputFiles(["first.txt","second.txt","third.txt"].map(name=>({name,mimeType:"text/plain",buffer:Buffer.from("synthetic")})));
    await page.getByText(/已上传 1 份/).waitFor();
    await page.locator('[id="report-first.txt"]').waitFor();
    assert.deepEqual(uploadedNames,["first.txt","second.txt"]);
    rejectSecond=false;
    await upload.setInputFiles({name:"second.txt",mimeType:"text/plain",buffer:Buffer.from("synthetic retry")});
    await page.locator('[id="report-second.txt"]').waitFor();
    assert.deepEqual(uploadedNames,["first.txt","second.txt","second.txt"]);
  }

  // A slow initial archive list must not hide a subsequently confirmed upload.
  let releaseInitialList, initialListStarted;
  const initialListReady=new Promise(resolve=>{initialListStarted=resolve;});
  let archiveReads=0;
  const staleArchiveList=async route=>{
    if(route.request().method()!=="GET")return route.fallback();
    if(++archiveReads===1){initialListStarted();await new Promise(resolve=>{releaseInitialList=resolve;});return route.fulfill({json:{data:[]}});}
    return route.fallback();
  };
  await page.route("**/api/myreports",staleArchiveList);
  await page.goto(`${frontend}/my-reports`,{waitUntil:"domcontentloaded"});await initialListReady;
  await page.locator('input[type="file"]').setInputFiles({name:"fresh.txt",mimeType:"text/plain",buffer:Buffer.from("synthetic fresh")});
  await page.locator('[id="report-fresh.txt"]').waitFor();
  const staleArchiveResponse=page.waitForResponse(r=>new URL(r.url()).pathname==="/api/myreports"&&r.request().method()==="GET");
  releaseInitialList();await staleArchiveResponse;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('[id="report-fresh.txt"]').count(),1);
  assert.equal(await page.getByText(/还没有归档的研报/).count(),0);
  await page.unroute("**/api/myreports",staleArchiveList);

  let indexedSearchReady=false, archiveSearches=0;
  await page.route("**/api/myreports/fulltext-search?*",route=>{
    archiveSearches++;
    return route.fulfill({json:{data:indexedSearchReady?[{report_id:"fresh.txt",title:"INDEX_SEARCH_RESULT",snippet:"synthetic indexed text",page:1}]:[]}});
  });
  await page.route("**/api/myreports/text-index/preview",route=>route.fulfill({json:{data:{items:[{eligible:true,report_id:"fresh.txt"}]}}}));
  await page.route("**/api/myreports/text-index/batch",route=>{indexedSearchReady=true;return route.fulfill({json:{data:{}}});});
  await page.getByPlaceholder("搜索研报正文…").fill("synthetic");
  await page.getByText("没有匹配的研报。",{exact:true}).waitFor();
  page.once("dialog",dialog=>dialog.accept());
  await page.getByRole("button",{name:"索引旧研报",exact:true}).click();
  await page.getByText("INDEX_SEARCH_RESULT",{exact:true}).waitFor();
  assert.equal(archiveSearches,2);
  assert.equal(await page.getByPlaceholder("搜索研报正文…").inputValue(),"synthetic");

  let releaseOldSignal, signalStarted;
  const oldSignalStarted=new Promise(resolve=>{signalStarted=resolve;});
  await page.route("**/api/signal-ledger?*",async route=>{
    const stage=new URL(route.request().url()).searchParams.get("stage");
    if(stage==="schema"){signalStarted();await new Promise(resolve=>{releaseOldSignal=resolve;});}
    await route.fulfill({json:{items:stage?[{entry_id:stage,stage,severity:"info",code:"600519",payload_json:{marker:stage==="schema"?"STALE_SIGNAL":"CURRENT_SIGNAL"}}]:[],total:stage?1:0}});
  });
  await page.goto(`${frontend}/signal-ledger`,{waitUntil:"networkidle"});
  await page.locator("select").first().selectOption("schema");
  await page.getByRole("button",{name:"查询信号",exact:true}).click();await oldSignalStarted;
  await page.locator("select").first().selectOption("execution");
  await page.getByRole("button",{name:"查询信号",exact:true}).click();
  await page.getByText(/CURRENT_SIGNAL/).waitFor();
  const oldSignalResponse=page.waitForResponse(r=>r.url().includes("stage=schema"));
  releaseOldSignal();await oldSignalResponse;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.getByText(/STALE_SIGNAL/).count(),0);
  assert.equal(await page.locator("select").first().inputValue(),"execution");
  await page.getByText(/CURRENT_SIGNAL/).waitFor();

  // Product citation UI is separate from answer prose. These are synthetic
  // transport fixtures; backend tests separately verify real PDF extraction.
  archived=[
    {id:"selected-pdf",name:"selected.pdf",title:"Selected PDF",size:1,ts:1,sector_keys:[]},
    {id:"selected-text",name:"selected.txt",title:"Selected text",size:1,ts:1,sector_keys:[]},
    {id:"unselected",name:"unselected.txt",title:"UNSELECTED REPORT",size:1,ts:1,sector_keys:[]},
  ];
  let citationCalls=0;
  const citationErrors=[];
  page.on("pageerror",error=>citationErrors.push(error.message));
  await page.route("**/api/chat",route=>{
    const body=route.request().postDataJSON();
    assert.deepEqual([...body.report_ids].sort(),["selected-pdf","selected-text"]);
    citationCalls++;
    const events=[{type:"sources",items:[{report_id:"selected-pdf",title:"Selected PDF",page:2},{report_id:"selected-text",title:"Selected text",page:null}]},{type:"delta",text:"SYNTHETIC ANSWER; CITATIONS ARE SHOWN SEPARATELY"},{type:"done"}];
    return route.fulfill({status:200,contentType:"application/x-ndjson",body:events.map(event=>JSON.stringify(event)).join("\n")+"\n"});
  });
  for(const provider of ["api","cli-codex"]){
    await page.evaluate(provider=>localStorage.setItem("vr-llm",JSON.stringify({provider,model:"synthetic-citation",baseURL:"https://example.test",apiKey:"synthetic"})),provider);
    await page.goto(`${frontend}/my-reports`,{waitUntil:"networkidle"});
    const openSelectedChat=async()=>{
      await page.getByRole("checkbox",{name:"选择 Selected PDF",exact:true}).check();
      await page.getByRole("checkbox",{name:"选择 Selected text",exact:true}).check();
      await page.getByRole("button",{name:"基于所选资料提问（2）",exact:true}).click();
    };
    await openSelectedChat();
    await page.getByPlaceholder("询问 Vibe...").fill("synthetic citation question");
    await page.getByRole("button",{name:"发送",exact:true}).click();
    const pdfCitation="Selected PDF · report_id=selected-pdf · 第 2 页";
    const textCitation="Selected text · report_id=selected-text · 页码不可用";
    await page.getByText(pdfCitation,{exact:true}).waitFor();
    await page.getByText(textCitation,{exact:true}).waitFor();
    assert.equal(await page.getByRole("dialog",{name:"Vibe AI 对话"}).getByText(/report_id=unselected/).count(),0);
    const beforeReload=citationCalls;
    await page.reload({waitUntil:"networkidle"});await openSelectedChat();
    await page.getByText(pdfCitation,{exact:true}).waitFor();
    await page.getByText(textCitation,{exact:true}).waitFor();
    assert.equal(citationCalls,beforeReload,"restoring citations must not repeat model request");
  }
  assert.equal(citationCalls,2);
  assert.deepEqual(citationErrors,[]);

  // Explicit indexed-page viewer: synthetic transport only, no automatic AI call.
  archived[0].file_sha256="a".repeat(64);
  let pageReads=0;
  await page.route("**/api/myreports/page-read",route=>{
    pageReads++;
    const body=route.request().postDataJSON();
    assert.deepEqual(body.selected_report_ids,["selected-pdf"]);
    assert.equal(body.expected_file_sha256,"a".repeat(64));
    assert.equal(body.page_from,2);
    return route.fulfill({json:{data:{report_id:"selected-pdf",file_sha256:"a".repeat(64),scope:"INDEXED_PAGE_TEXT_ONLY",full_report_read:false,
      requested:[2,3],returned_chars:28,complete_requested_text:false,
      coverage:{readable:[2],omitted:[],invalid:[],unreadable:[3],error:[]},
      items:[{page:2,status:"readable",reason:"CHAR_TRUNCATED",text:"SYNTHETIC LATE CORRECTION: 80",returned_chars:28,indexed_chars:40,truncated:true},
        {page:3,status:"unreadable",reason:"NO_INDEXED_PAGE_TEXT"}]}}});
  });
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:900});
    await page.goto(`${frontend}/my-reports`,{waitUntil:"networkidle"});
    await page.getByRole("checkbox",{name:"选择 Selected PDF",exact:true}).check();
    const viewer=page.getByTestId("report-page-reader");
    await viewer.locator("summary").focus();await page.keyboard.press("Enter");
    await viewer.getByLabel("起始页",{exact:true}).fill("2");
    await viewer.getByLabel("结束页",{exact:true}).fill("3");
    await viewer.getByRole("button",{name:"读取指定页",exact:true}).click();
    await viewer.getByText("SYNTHETIC LATE CORRECTION: 80",{exact:true}).waitFor();
    await viewer.getByText(/第 2 页.*部分正文/).waitFor();
    await viewer.getByText(/第 3 页.*正文不可用/).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await viewer.getByLabel("结束页",{exact:true}).fill("4");
    assert.equal(await viewer.getByRole("region",{name:"指定页读取结果"}).count(),0);
    await page.getByRole("checkbox",{name:"选择 Selected PDF",exact:true}).uncheck();
    assert.equal(await page.getByTestId("report-page-reader").count(),0);
  }
  assert.equal(pageReads,2);
  assert.equal(citationCalls,2,"page reads must not invoke AI");

  console.log("notes backup browser E2E: PASS");
} finally {
  if (browser) await browser.close().catch(() => {});
  if (server) await new Promise((resolveClose) => server.close(resolveClose));
}
