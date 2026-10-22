/** Native IndexedDB tests in isolated Chromium pages. No backend/model/user store is used.
 * Synthetic AbortError/QuotaExceeded injection proves transaction rollback, not physical-disk durability.
 * Sources are transpiled into test-only ES modules by TypeScript, with no production window hooks.
 */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { chromium } from 'playwright';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = resolve(process.env.RESEARCH_WORKFLOW_STORAGE_OUTPUT_DIR || join(frontend, 'test-results/research-workflow-storage'));
mkdirSync(output, { recursive: true });
const checks = [];
const mark = name => { checks.push({ name, status: 'PASS' }); console.log(`PASS ${name}`); };
function executablePath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH && existsSync(process.env.PLAYWRIGHT_CHROMIUM_PATH) && !readDirectory(process.env.PLAYWRIGHT_CHROMIUM_PATH)) return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  for (const root of [process.env.PLAYWRIGHT_CHROMIUM_PATH, join(process.env.HOME || '', '.cache/ms-playwright'), join(process.env.LOCALAPPDATA || '', 'ms-playwright')]) {
    if (!root || !readDirectory(root)) continue;
    for (const folder of readdirSync(root).sort().reverse()) for (const tail of ['chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-headless-shell-linux64/chrome-headless-shell', 'chrome-win64/chrome.exe', 'chrome-win/chrome.exe', 'chrome-headless-shell-win64/chrome-headless-shell.exe']) {
      const candidate = join(root, folder, tail);
      if (/^chromium/.test(folder) && existsSync(candidate)) return candidate;
    }
  }
}
function readDirectory(path) { try { readdirSync(path); return true; } catch { return false; } }
const fixtureMaterial = (version = 'v1') => ({ id: 'disclosure', version, securityCode: '301213', title: '合成存储原文', content: version === 'v1' ? '2024年归母净利润预计 648.13 至 753.93 万元。' : '2024年归母净利润修订为亏损 594.25 至 891.37 万元。', sourceUrl: 'https://example.org/synthetic.pdf', sourceKind: 'evidence_excerpt', sourceHash: null, publishedAt: '2025-01-24', capturedAt: 100, readRange: { pages: [], totalPages: null, truncated: false, ocr: false, description: '存储测试摘录，未声明阅读全文' }, availability: 'partial', provenance: { fixture: true, readReceipt: { pages: [], unknown: null } } });
const fixtureRound = (id, parentRoundId = null, createdAt = 101, version = 'v1', questionId = 'question') => ({ id, questionId, securityCode: '301213', parentRoundId, createdAt, materials: [fixtureMaterial(version)], calculation: null, judgement: '仅保存当时依据，不等同实际业绩或正式决定。', limitations: '合成存储案例。', nextMaterial: '实际年度报告', reviewedMaterialKeys: [`disclosure@${version}`], ignoredMaterialKeys: [], coverage: 'partial' });
const fixtureQuestion = (id = 'question') => ({ id, securityCode: '301213', question: '盈利预告是否被修订？', origin: { kind: 'candidate', label: '合成研究来由', url: '/candidates/301213', capturedAt: 100 }, createdAt: 100 });
async function invoke(page, method, args) {
  return page.evaluate(async ({ method, args }) => {
    try { return { ok: true, value: await window.store[method](...args) }; }
    catch (error) { return { ok: false, code: error.code, message: error.message }; }
  }, { method, args });
}
const ok = result => { assert.equal(result.ok, true, JSON.stringify(result)); return result.value; };
let server, browser, context, page;
try {
  server = createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url || '/', 'http://localhost').pathname);
    if (pathname === '/') { response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.end('<!doctype html><title>Research storage acceptance</title><body>Isolated native IndexedDB acceptance</body>'); return; }
    const path = resolve(frontend, `.${pathname}`);
    if (!path.startsWith(`${resolve(frontend, 'src')}${sep}`) || !path.endsWith('.ts') || !existsSync(path)) { response.writeHead(404); response.end(); return; }
    response.setHeader('Content-Type', 'text/javascript; charset=utf-8');
    response.end(ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText);
  });
  await new Promise((resolveListen, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolveListen); });
  const origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, ...(executablePath() ? { executablePath: executablePath() } : {}) });
  context = await browser.newContext();
  page = await context.newPage();
  const peer = await context.newPage();
  for (const target of [page, peer]) {
    await target.goto(origin);
    await target.evaluate(async () => {
      window.api = await import('/src/lib/researchWorkflowStore.ts');
      window.domain = await import('/src/lib/researchWorkflow.ts');
      window.store = window.api.createResearchWorkflowStore({ dbName: 'research-storage-acceptance' });
    });
  }
  const oldRaw = JSON.stringify([{ id: 'old', kind: '问AI', title: '旧记录', content: '旧回答仅有链接，不能追造当时全文。', ts: 50, research: { securityCode: '301213', sourceLinks: [{ title: '来源', url: 'https://example.org' }] }, unknownMetadata: { retained: true } }]);
  await page.evaluate(raw => localStorage.setItem('vr-notes', raw), oldRaw);
  assert.deepEqual(ok(await invoke(page, 'listQuestions', [])), []);
  const initialRequest = { operationId: 'create-question', question: fixtureQuestion(), initialRound: fixtureRound('T0') };
  const initial = ok(await invoke(page, 'createQuestion', [initialRequest]));
  assert.equal(initial.headRoundId, 'T0');
  assert.equal(initial.revision, 1);
  assert.equal((await peer.evaluate(() => localStorage.getItem('vr-notes'))), oldRaw);
  assert.equal((ok(await invoke(peer, 'getQuestion', ['question']))).headRoundId, 'T0');
  mark('atomic first question + immutable T0 + cross-connection readback');

  const requests = ['left', 'right'].map(side => ({ operationId: `append-${side}`, questionId: 'question', expectedRevision: 1, expectedHeadRoundId: 'T0', round: fixtureRound(`T1-${side}`, 'T0', 102, 'v2') }));
  const raced = await Promise.all([invoke(page, 'appendRound', [requests[0]]), invoke(peer, 'appendRound', [requests[1]])]);
  assert.equal(raced.filter(result => result.ok).length, 1);
  assert.equal(raced.filter(result => result.code === 'CONFLICT').length, 1);
  const winnerIndex = raced.findIndex(result => result.ok);
  const winner = ok(raced[winnerIndex]);
  assert.equal(ok(await invoke(page, 'getRounds', ['question'])).length, 2);
  assert.deepEqual(winner.question.reviewedMaterialKeys, ['disclosure@v1', 'disclosure@v2']);
  mark('two actual tabs same expected head: exactly one commits, loser conflict');

  const paused = ok(await invoke(peer, 'setStatus', [{ operationId: 'pause', questionId: 'question', expectedRevision: 2, expectedHeadRoundId: winner.round.id, status: 'paused' }]));
  assert.equal(paused.revision, 3);
  assert.deepEqual(ok(await invoke(page, 'appendRound', [requests[winnerIndex]])), winner);
  const changedRetry = structuredClone(requests[winnerIndex]); changedRetry.round.judgement = '不同内容';
  assert.equal((await invoke(page, 'appendRound', [changedRetry])).code, 'IDEMPOTENCY');
  assert.equal(ok(await invoke(page, 'getQuestion', ['question'])).status, 'paused');
  mark('lost-response same-op retry returns original result; changed payload rejected');

  const beforeFailure = ok(await invoke(page, 'exportBackup', []));
  for (const errorName of ['AbortError', 'QuotaExceededError']) {
    const failure = await page.evaluate(async ({ errorName, request }) => {
      const original = IDBObjectStore.prototype.add;
      IDBObjectStore.prototype.add = function (value, key) {
        const queued = key === undefined ? original.call(this, value) : original.call(this, value, key);
        if (this.name === 'rounds') throw new DOMException('Synthetic fault after native add was queued', errorName);
        return queued;
      };
      try { await window.store.appendRound(request); return { ok: true }; }
      catch (error) { return { ok: false, code: error.code }; }
      finally { IDBObjectStore.prototype.add = original; }
    }, { errorName, request: { operationId: `fault-${errorName}`, questionId: 'question', expectedRevision: 3, expectedHeadRoundId: winner.round.id, round: fixtureRound(`aborted-${errorName}`, winner.round.id, 103, 'v3') } });
    assert.equal(failure.ok, false);
    assert.equal(failure.code, errorName === 'AbortError' ? 'ABORT' : 'BUDGET');
    assert.deepEqual(JSON.parse(ok(await invoke(page, 'exportBackup', []))).data, JSON.parse(beforeFailure).data);
  }
  mark('native transaction rollback after queued writes on synthetic abort/quota fault; baseline unchanged');

  const firstFailure = await page.evaluate(async request => {
    const original = IDBObjectStore.prototype.add;
    IDBObjectStore.prototype.add = function (value) { const queued = original.call(this, value); if (this.name === 'rounds') throw new DOMException('abort first round', 'AbortError'); return queued; };
    try { await window.store.createQuestion(request); return 'unexpected'; } catch (error) { return error.code; } finally { IDBObjectStore.prototype.add = original; }
  }, { operationId: 'aborted-create', question: fixtureQuestion('atomic-new'), initialRound: fixtureRound('new-T0', null, 101, 'v1', 'atomic-new') });
  assert.equal(firstFailure, 'ABORT');
  assert.equal(ok(await invoke(page, 'getQuestion', ['atomic-new'])), null);
  mark('first-save abort leaves neither question nor orphan initial round');

  const legacyResult = ok(await invoke(page, 'importLegacy', [oldRaw, 'import-legacy']));
  assert.equal(legacyResult.added, 1);
  assert.deepEqual(ok(await invoke(page, 'importLegacy', [oldRaw, 'import-legacy'])), legacyResult);
  assert.equal(await page.evaluate(() => localStorage.getItem('vr-notes')), oldRaw);
  await peer.evaluate(async () => { const oldClient = await import('/src/lib/notes.ts'); oldClient.addNote('普通笔记', '旧页新增', '不能覆盖独立研究链'); });
  const changedRaw = await peer.evaluate(() => localStorage.getItem('vr-notes'));
  assert.equal(ok(await invoke(page, 'checkLegacySource', [changedRaw])).changed, true);
  assert.equal(ok(await invoke(page, 'getQuestion', ['question'])).headRoundId, winner.round.id);
  await peer.evaluate(async () => { const oldClient = await import('/src/lib/notes.ts'); oldClient.clearNotes(); });
  assert.equal(ok(await invoke(page, 'getRounds', ['question'])).length, 2);
  assert.deepEqual(ok(await invoke(page, 'listLegacyNotes', []))[0].payload.unknownMetadata, { retained: true });
  mark('explicit legacy read-only import preserves raw; old-client writes/clear cannot affect new domain');

  const exported = ok(await invoke(page, 'exportBackup', []));
  const exportedData = JSON.parse(exported).data;
  const restorePage = await context.newPage();
  await restorePage.goto(origin);
  await restorePage.evaluate(async () => { window.api = await import('/src/lib/researchWorkflowStore.ts'); window.store = window.api.createResearchWorkflowStore({ dbName: 'research-empty-restore' }); });
  assert.deepEqual(ok(await invoke(restorePage, 'listQuestions', [])), []);
  assert.deepEqual(ok(await invoke(restorePage, 'importBackup', [exported, 'restore'])), { addedQuestions: 1, addedRounds: 2 });
  assert.deepEqual(ok(await invoke(restorePage, 'getRounds', ['question'])), exportedData.rounds.sort((a, b) => a.createdAt - b.createdAt));
  assert.deepEqual(ok(await invoke(restorePage, 'getQuestion', ['question'])), paused);
  assert.deepEqual(ok(await invoke(restorePage, 'listLegacyNotes', [])), exportedData.legacySources[0].notes);
  assert.deepEqual(ok(await invoke(restorePage, 'appendRound', [requests[winnerIndex]])), winner);
  assert.deepEqual(ok(await invoke(restorePage, 'importBackup', [exported, 'restore-again'])), { addedQuestions: 0, addedRounds: 0 });
  await restorePage.reload();
  await restorePage.evaluate(async () => { window.api = await import('/src/lib/researchWorkflowStore.ts'); window.store = window.api.createResearchWorkflowStore({ dbName: 'research-empty-restore' }); });
  assert.deepEqual(ok(await invoke(restorePage, 'getQuestion', ['question'])), paused);
  mark('validated full backup restores empty native store, immutable payloads and retry receipts survive reload');

  for (const fault of ['missing-parent', 'wrong-head', 'cross-stock', 'forged-receipt', 'changed-same-id']) {
    const malformed = structuredClone(JSON.parse(exported));
    if (fault === 'missing-parent') malformed.data.rounds = malformed.data.rounds.filter(round => round.id !== 'T0');
    if (fault === 'wrong-head') malformed.data.questions[0].headRoundId = 'not-present';
    if (fault === 'cross-stock') malformed.data.rounds[0].securityCode = '688041';
    if (fault === 'forged-receipt') malformed.data.operations[0].response.headRoundId = 'not-present';
    if (fault === 'changed-same-id') { malformed.data.rounds[0].judgement = '改写不可变正文'; malformed.data.operations = []; }
    const raw = await page.evaluate(async data => {
      data.manifest = { sha256: await window.domain.researchContentHash(window.domain.canonicalJson(data.data)), questionIds: data.data.questions.map(q => q.id).sort(), roundIds: data.data.rounds.map(r => r.id).sort() };
      return JSON.stringify(data);
    }, malformed);
    const rejected = await invoke(restorePage, 'importBackup', [raw, `bad-${fault}`]);
    assert.equal(rejected.ok, false, fault);
    assert.deepEqual(ok(await invoke(restorePage, 'getQuestion', ['question'])), paused);
  }
  mark('complete-chain preflight rejects recomputed-checksum orphan/head/stock/receipt/conflicting-ID attacks atomically');

  const budgetResult = await page.evaluate(async raw => {
    const store = window.api.createResearchWorkflowStore({ dbName: 'budget-empty', budgetBytes: 128 });
    try { await store.importBackup(raw, 'budget-import'); return { ok: true }; } catch (error) { return { code: error.code, questions: await store.listQuestions() }; } finally { store.close(); }
  }, exported);
  assert.equal(budgetResult.code, 'BUDGET'); assert.deepEqual(budgetResult.questions, []);
  mark('serialized byte budget rejects entire import without truncating chains');

  const calculationCheck = await page.evaluate(async ({ question, round, materials }) => {
    const { compareForecast } = await import('/src/lib/researchCheck.ts');
    const common = { subject: '301213', metric: '归母净利润', periodStart: '2024-01-01', periodEnd: '2024-12-31', periodType: 'annual', currency: 'CNY', unit: '万元', basis: 'consolidated', valueType: 'forecast', confirmed: true };
    const forecast = { ...common, materialKey: 'disclosure@v1', sourceExcerpt: materials[0].content, low: '648.13', high: '753.93' };
    const revision = { ...common, materialKey: 'disclosure@v2', sourceExcerpt: materials[1].content, low: '-594.25', high: '-891.37' };
    const calculation = compareForecast('301213', 'revision', forecast, revision, materials);
    const store = window.api.createResearchWorkflowStore({ dbName: 'native-calculation' });
    await store.createQuestion({ operationId: 'calc-first', question, initialRound: { ...round, materials, reviewedMaterialKeys: ['disclosure@v1', 'disclosure@v2'], calculation } });
    const read = (await store.getRounds(question.id))[0];
    const backup = JSON.parse(await store.exportBackup());
    backup.data.rounds[0].calculation.result = '伪造：实际业绩已兑现';
    backup.data.operations = []; // Force the arithmetic validator, not a mismatched historical operation receipt.
    backup.manifest.sha256 = await window.domain.researchContentHash(window.domain.canonicalJson(backup.data));
    const target = window.api.createResearchWorkflowStore({ dbName: 'reject-forged-calculation' });
    let rejected;
    try { await target.importBackup(JSON.stringify(backup), 'tampered-calc'); rejected = 'unexpected'; } catch (error) { rejected = error.code; }
    const after = await target.listQuestions();
    store.close(); target.close();
    return { result: read.calculation.result, originalText: read.materials[0].content, rejected, after };
  }, { question: fixtureQuestion('calculated'), round: fixtureRound('calc-T0', null, 101, 'v1', 'calculated'), materials: [fixtureMaterial('v1'), fixtureMaterial('v2')] });
  assert.match(calculationCheck.result, /修订预告不是实际业绩/);
  assert.equal(calculationCheck.originalText, fixtureMaterial('v1').content);
  assert.equal(calculationCheck.rejected, 'VALIDATION');
  assert.deepEqual(calculationCheck.after, []);
  mark('native calculated-round save retains operands and original text; checksum-recomputed forged result cannot import');

  for (const count of [100, 200, 1000]) {
    const rounds = Array.from({ length: count }, (_, index) => fixtureRound(`bulk-${count}-${index}`, index ? `bulk-${count}-${index - 1}` : null, 101 + index, 'v1', `bulk-${count}`));
    const question = { ...fixtureQuestion(`bulk-${count}`), updatedAt: 100 + count, revision: count, headRoundId: `bulk-${count}-${count - 1}`, status: 'watching', reviewedMaterialKeys: ['disclosure@v1'] };
    const accepted = await page.evaluate(async ({ count, question, rounds }) => {
      const data = { questions: [question], rounds, operations: [], legacySources: [] };
      const manifest = { sha256: await window.domain.researchContentHash(window.domain.canonicalJson(data)), questionIds: [question.id], roundIds: rounds.map(round => round.id).sort() };
      const raw = JSON.stringify({ schemaVersion: window.domain.RESEARCH_BACKUP_SCHEMA, exportedAt: new Date().toISOString(), data, manifest });
      const store = window.api.createResearchWorkflowStore({ dbName: `bulk-native-${count}` });
      const result = await store.importBackup(raw, `bulk-${count}`);
      const read = await store.getRounds(question.id);
      const backup = JSON.parse(await store.exportBackup());
      store.close();
      return { result, readCount: read.length, backupCount: backup.data.rounds.length, first: read[0].id, last: read.at(-1).id };
    }, { count, question, rounds });
    assert.equal(accepted.result.addedRounds, count);
    assert.equal(accepted.readCount, count);
    assert.equal(accepted.backupCount, count);
    assert.equal(accepted.first, `bulk-${count}-0`);
    assert.equal(accepted.last, `bulk-${count}-${count - 1}`);
  }
  mark('native 100 / 200 / 1000 round import and export preserve every complete chain without count truncation');

  const lifecycle = await page.evaluate(async () => {
    const old = window.api.createResearchWorkflowStore({ dbName: 'upgrade-cooperative' });
    await old.listQuestions();
    const upgraded = window.api.createResearchWorkflowStore({ dbName: 'upgrade-cooperative', databaseVersion: 2, blockedTimeoutMs: 250 });
    await upgraded.listQuestions(); // Sends versionchange; cooperative old closes automatically.
    let downgrade;
    try { await old.listQuestions(); downgrade = 'unexpected'; } catch (error) { downgrade = error.code; }
    upgraded.close(); old.close();
    const rawOld = await new Promise((resolveOpen, reject) => { const request = indexedDB.open('upgrade-blocked', 1); request.onsuccess = () => resolveOpen(request.result); request.onerror = () => reject(request.error); });
    // Deliberately non-cooperative old tab retains its connection.
    const blocked = window.api.createResearchWorkflowStore({ dbName: 'upgrade-blocked', databaseVersion: 2, blockedTimeoutMs: 80 });
    const started = performance.now();
    let blockedCode;
    try { await blocked.listQuestions(); blockedCode = 'unexpected'; } catch (error) { blockedCode = error.code; }
    const elapsed = performance.now() - started;
    rawOld.close();
    // Timed-out open may receive upgradeneeded later: it must abort instead of writing in background.
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
    const probe = await new Promise((resolveOpen, reject) => { const request = indexedDB.open('upgrade-blocked'); request.onsuccess = () => resolveOpen(request.result); request.onerror = () => reject(request.error); });
    const versionAfterTimeout = probe.version; probe.close();
    await blocked.listQuestions(); // New explicit retry can now perform its intended upgrade.
    blocked.close();
    return { downgrade, blockedCode, elapsed, versionAfterTimeout };
  });
  assert.equal(lifecycle.downgrade, 'UNAVAILABLE');
  assert.equal(lifecycle.blockedCode, 'BLOCKED');
  assert.ok(lifecycle.elapsed < 2000);
  assert.equal(lifecycle.versionAfterTimeout, 1);
  mark('versionchange closes cooperative client; blocked is bounded, late upgrade aborts, explicit retry recovers');

  await page.evaluate(checks => { document.body.innerText = ['Native IndexedDB acceptance', ...checks.map(check => `PASS ${check.name}`), 'Scope: synthetic data; no actual quota pressure, OS crash, private-mode retention or power-loss durability claim.'].join('\n\n'); }, checks);
  await page.screenshot({ path: join(output, 'native-indexeddb-acceptance.png'), fullPage: true });
  writeFileSync(join(output, 'results.json'), JSON.stringify({ status: 'PASS', engine: 'Chromium native IndexedDB', checks, limitations: ['Synthetic quota/abort faults, not physical storage exhaustion', 'No OS crash/power-loss or private-mode retention proof', 'No real user migration or paid model call'] }, null, 2));
} catch (error) {
  writeFileSync(join(output, 'results.json'), JSON.stringify({ status: 'FAIL', checks, error: String(error?.stack || error) }, null, 2));
  if (page) await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await context?.close();
  await browser?.close();
  if (server?.listening) await new Promise(resolveClose => server.close(resolveClose));
}
