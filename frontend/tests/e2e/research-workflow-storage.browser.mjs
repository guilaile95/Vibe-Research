/** Native IndexedDB tests in isolated Chromium pages. No backend/model/user store is used.
 * Synthetic AbortError/QuotaExceeded injection proves transaction rollback, not physical-disk durability.
 * Lost-response recovery is simulated by retrying the same operation, not by dropping an actual response.
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

  assert.deepEqual(ok(await invoke(page, 'getQuestionContext', ['question'])), { question: initial, rounds: [initialRequest.initialRound] });
  assert.equal(ok(await invoke(page, 'getQuestionContext', ['missing-question'])), null);
  mark('question context returns saved question and ordered rounds together; missing question is null');

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
  mark('simulated lost-response idempotency: same-op retry returns original result; changed payload rejected');

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
  await peer.evaluate(async () => { const oldClient = await import('/src/lib/notes.ts'); await oldClient.addNote('普通笔记', '旧页新增', '不能覆盖独立研究链'); });
  const changedRaw = await peer.evaluate(async () => (await import('/src/lib/notes.ts')).notesSourceRaw());
  assert.equal(ok(await invoke(page, 'checkLegacySource', [changedRaw])).changed, true);
  assert.equal(ok(await invoke(page, 'getQuestion', ['question'])).headRoundId, winner.round.id);
  await peer.evaluate(async () => { const oldClient = await import('/src/lib/notes.ts'); await oldClient.clearNotes(); });
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
  // These assertions deliberately run after reload/reopen, not just after import.
  const reopenedBeforeRetry = JSON.parse(ok(await invoke(restorePage, 'exportBackup', []))).data;
  assert.deepEqual(ok(await invoke(restorePage, 'getRounds', ['question'])), exportedData.rounds);
  assert.deepEqual(ok(await invoke(restorePage, 'createQuestion', [initialRequest])), initial);
  assert.deepEqual(ok(await invoke(restorePage, 'appendRound', [requests[winnerIndex]])), winner);
  assert.equal((await invoke(restorePage, 'appendRound', [changedRetry])).code, 'IDEMPOTENCY');
  assert.deepEqual(ok(await invoke(restorePage, 'getQuestion', ['question'])), paused);
  assert.deepEqual(ok(await invoke(restorePage, 'getRounds', ['question'])), exportedData.rounds);
  assert.deepEqual(JSON.parse(ok(await invoke(restorePage, 'exportBackup', []))).data, reopenedBeforeRetry);
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
    const raw = await new Promise((resolveOpen, reject) => { const request = indexedDB.open('native-calculation'); request.onsuccess = () => resolveOpen(request.result); request.onerror = () => reject(request.error); });
    await new Promise((resolveWrite, reject) => {
      const tx = raw.transaction(['rounds', 'operations'], 'readwrite');
      tx.objectStore('rounds').put(backup.data.rounds[0]);
      tx.objectStore('operations').clear();
      tx.oncomplete = resolveWrite; tx.onabort = () => reject(tx.error);
    });
    const contextRejected = [];
    for (const id of [question.id, 'missing']) {
      try { await store.getQuestionContext(id); contextRejected.push('unexpected'); } catch (error) { contextRejected.push(error.code); }
    }
    raw.close();
    store.close(); target.close();
    return { result: read.calculation.result, originalText: read.materials[0].content, rejected, after, contextRejected };
  }, { question: fixtureQuestion('calculated'), round: fixtureRound('calc-T0', null, 101, 'v1', 'calculated'), materials: [fixtureMaterial('v1'), fixtureMaterial('v2')] });
  assert.match(calculationCheck.result, /修订预告不是实际业绩/);
  assert.equal(calculationCheck.originalText, fixtureMaterial('v1').content);
  assert.equal(calculationCheck.rejected, 'VALIDATION');
  assert.deepEqual(calculationCheck.after, []);
  mark('native calculated-round save retains operands and original text; checksum-recomputed forged result cannot import');
  assert.deepEqual(calculationCheck.contextRejected, ['VALIDATION', 'VALIDATION']);
  mark('context validates persisted calculation replay before returning either an existing question or not-found');

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

  const contextReads = await page.evaluate(async ({ question, round }) => {
    const store = window.api.createResearchWorkflowStore({ dbName: 'context-readonly' });
    await store.createQuestion({ operationId: 'context-create', question, initialRound: round });
    for (const status of ['paused', 'resolved', 'archived']) {
      const id = `context-${status}`;
      await store.createQuestion({ operationId: `create-${id}`, question: { ...question, id, status }, ...(status === 'paused' ? {} : { initialRound: { ...round, id: `${id}-T0`, questionId: id } }) });
    }
    const before = JSON.parse(await store.exportBackup()).data;
    const originalTransaction = IDBDatabase.prototype.transaction;
    const mutators = Object.fromEntries(['add', 'put', 'delete', 'clear'].map(method => [method, IDBObjectStore.prototype[method]]));
    const transactions = [], writes = [], reads = [];
    IDBDatabase.prototype.transaction = function (...args) {
      const tx = originalTransaction.apply(this, args);
      transactions.push({ mode: tx.mode, stores: [...tx.objectStoreNames] });
      return tx;
    };
    for (const [method, original] of Object.entries(mutators)) IDBObjectStore.prototype[method] = function (...args) {
      writes.push({ method, store: this.name });
      return original.apply(this, args);
    };
    try {
      for (const id of [question.id, 'context-paused', 'context-resolved', 'context-archived', 'missing']) {
        const start = transactions.length;
        reads.push({ id, value: await store.getQuestionContext(id), transactions: transactions.slice(start) });
      }
      // Mutating the read projection cannot change any persisted question or immutable round.
      const detached = await store.getQuestionContext(question.id);
      detached.question.question = 'Only a detached view changed';
      detached.rounds[0].materials[0].content = 'Not persisted';
      detached.rounds.push({ ...detached.rounds[0], id: 'not-saved' });
    } finally {
      IDBDatabase.prototype.transaction = originalTransaction;
      for (const [method, original] of Object.entries(mutators)) IDBObjectStore.prototype[method] = original;
    }
    const after = JSON.parse(await store.exportBackup()).data;
    store.close();
    return { before, after, writes, reads };
  }, { question: fixtureQuestion('context-question'), round: fixtureRound('context-T0', null, 101, 'v1', 'context-question') });
  assert.deepEqual(contextReads.before, contextReads.after);
  assert.deepEqual(contextReads.writes, []);
  for (const read of contextReads.reads) assert.deepEqual(read.transactions, [{ mode: 'readonly', stores: ['legacySources', 'operations', 'questions', 'rounds'] }]);
  assert.equal(contextReads.reads[0].value.question.id, 'context-question');
  assert.deepEqual(contextReads.reads[0].value.rounds.map(round => round.id), ['context-T0']);
  assert.equal(contextReads.reads[1].value.question.status, 'paused');
  assert.equal(contextReads.reads[1].value.question.headRoundId, null);
  assert.deepEqual(contextReads.reads[1].value.rounds, []);
  assert.equal(contextReads.reads[2].value.question.status, 'resolved');
  assert.equal(contextReads.reads[3].value.question.status, 'archived');
  assert.equal(contextReads.reads[4].value, null);
  mark('context reads use one readonly full-snapshot transaction each, preserve paused headless/resolved/archived states and issue zero writes');

  const contextRace = await page.evaluate(async ({ question, first, next }) => {
    const dbName = 'context-concurrent';
    const store = window.api.createResearchWorkflowStore({ dbName });
    const initial = await store.createQuestion({ operationId: 'race-context-create', question, initialRound: first });
    const writer = await new Promise((resolveOpen, reject) => { const request = indexedDB.open(dbName); request.onsuccess = () => resolveOpen(request.result); request.onerror = () => reject(request.error); });
    const newer = { ...initial, revision: 2, headRoundId: next.id, updatedAt: next.createdAt };
    const original = IDBObjectStore.prototype.getAll;
    let queuedWriter, captured = false;
    IDBObjectStore.prototype.getAll = function (...args) {
      const request = original.apply(this, args);
      if (!captured && this.transaction.mode === 'readonly') {
        captured = true;
        // Queue a real second-connection transaction after the first read request.
        // Native IndexedDB serializes it after that entire readonly snapshot. A
        // split getQuestion/getRounds implementation instead observes mixed heads.
        queuedWriter = new Promise((resolveWrite, reject) => {
          const tx = writer.transaction(['questions', 'rounds'], 'readwrite');
          tx.objectStore('questions').put(newer);
          tx.objectStore('rounds').add(next);
          tx.oncomplete = resolveWrite;
          tx.onabort = () => reject(tx.error);
        });
      }
      return request;
    };
    let during;
    try { during = await store.getQuestionContext(question.id); }
    finally { IDBObjectStore.prototype.getAll = original; }
    await queuedWriter;
    const after = await store.getQuestionContext(question.id);
    writer.close(); store.close();
    return { captured, initial, newer, during, after };
  }, { question: fixtureQuestion('context-race'), first: fixtureRound('z-context-first', null, 101, 'v1', 'context-race'), next: fixtureRound('a-context-next', 'z-context-first', 102, 'v1', 'context-race') });
  assert.equal(contextRace.captured, true);
  assert.deepEqual(contextRace.during.question, contextRace.initial);
  assert.deepEqual(contextRace.during.rounds.map(round => round.id), ['z-context-first']);
  assert.deepEqual(contextRace.after.question, contextRace.newer);
  assert.deepEqual(contextRace.after.rounds.map(round => round.id), ['z-context-first', 'a-context-next']);
  mark('native concurrent writer cannot split question/head/history across snapshots; rounds follow the parent chain, not ID order');

  const contextFailures = await page.evaluate(async ({ question, round }) => {
    const dbName = 'context-invalid';
    const store = window.api.createResearchWorkflowStore({ dbName });
    await store.createQuestion({ operationId: 'invalid-context-create', question, initialRound: round });
    const baseline = JSON.parse(await store.exportBackup()).data;
    const raw = await new Promise((resolveOpen, reject) => { const request = indexedDB.open(dbName); request.onsuccess = () => resolveOpen(request.result); request.onerror = () => reject(request.error); });
    const names = ['questions', 'rounds', 'operations', 'legacySources'];
    const replaceFixture = data => new Promise((resolveWrite, reject) => {
      const tx = raw.transaction(names, 'readwrite');
      for (const name of names) { const target = tx.objectStore(name); target.clear(); for (const entry of data[name]) target.add(entry); }
      tx.oncomplete = resolveWrite; tx.onabort = () => reject(tx.error);
    });
    const rawSnapshot = () => new Promise((resolveRead, reject) => {
      const tx = raw.transaction(names, 'readonly'), data = {};
      for (const name of names) { const request = tx.objectStore(name).getAll(); request.onsuccess = () => { data[name] = request.result; }; }
      tx.oncomplete = () => resolveRead(data); tx.onabort = () => reject(tx.error);
    });
    const outcome = async id => { try { return { value: await store.getQuestionContext(id) }; } catch (error) { return { code: error.code }; } };
    const invalid = [];
    for (const fault of ['wrong-head', 'cross-stock', 'forged-receipt', 'invalid-legacy']) {
      const data = structuredClone(baseline);
      if (fault === 'wrong-head') data.questions[0].headRoundId = 'not-present';
      if (fault === 'cross-stock') data.rounds[0].securityCode = '688041';
      if (fault === 'forged-receipt') data.operations[0].response.headRoundId = 'not-present';
      if (fault === 'invalid-legacy') data.legacySources.push({ id: 'a'.repeat(64), raw: '[]', notes: [{ forged: true }] });
      await replaceFixture(data);
      const before = await rawSnapshot();
      invalid.push({ fault, existing: await outcome(question.id), missing: await outcome('missing'), unchanged: window.domain.canonicalJson(before) === window.domain.canonicalJson(await rawSnapshot()) });
    }
    await replaceFixture(baseline);
    const originalTransaction = IDBDatabase.prototype.transaction;
    let unavailable;
    IDBDatabase.prototype.transaction = function () { throw new DOMException('Synthetic unavailable transaction', 'InvalidStateError'); };
    try { unavailable = await outcome(question.id); }
    finally { IDBDatabase.prototype.transaction = originalTransaction; }
    const originalGetAll = IDBObjectStore.prototype.getAll;
    let aborted, abortQueued = false;
    IDBObjectStore.prototype.getAll = function (...args) {
      const request = originalGetAll.apply(this, args);
      if (!abortQueued) { abortQueued = true; const tx = this.transaction; queueMicrotask(() => tx.abort()); }
      return request;
    };
    try { aborted = await outcome('missing'); }
    finally { IDBObjectStore.prototype.getAll = originalGetAll; }
    const recovered = await store.getQuestionContext(question.id);
    const after = await rawSnapshot();
    raw.close(); store.close();
    return { invalid, unavailable, aborted, recovered, unchanged: window.domain.canonicalJson(baseline) === window.domain.canonicalJson(after) };
  }, { question: fixtureQuestion('context-invalid'), round: fixtureRound('invalid-T0', null, 101, 'v1', 'context-invalid') });
  for (const result of contextFailures.invalid) {
    assert.deepEqual(result.existing, { code: 'VALIDATION' }, result.fault);
    assert.deepEqual(result.missing, { code: 'VALIDATION' }, result.fault);
    assert.equal(result.unchanged, true, result.fault);
  }
  assert.deepEqual(contextFailures.unavailable, { code: 'UNAVAILABLE' });
  assert.deepEqual(contextFailures.aborted, { code: 'ABORT' });
  assert.equal(contextFailures.recovered.question.id, 'context-invalid');
  assert.equal(contextFailures.unchanged, true);
  mark('context fails closed on full-snapshot chain/stock/receipt/legacy corruption and transaction errors, never disguising them as not-found or writing repairs');

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

  // P1-04: native cross-tab locks, not simulated hooks or storage events.
  const notesContext = await browser.newContext();
  const noteTabs = await Promise.all([notesContext.newPage(), notesContext.newPage()]);
  for (const tab of noteTabs) { await tab.goto(origin); await tab.evaluate(async () => { window.notesApi = await import('/src/lib/notes.ts'); }); }
  const retainedLegacy = JSON.stringify([{ id:'retained', kind:'manual', title:'Legacy raw', content:'synthetic', ts:1 }]);
  await noteTabs[0].evaluate(raw => localStorage.setItem('vr-notes', raw), retainedLegacy);
  // Queue both writers behind a genuinely held origin lock, then release together.
  await noteTabs[0].evaluate(() => { window.noteLock = navigator.locks.request(window.notesApi.NOTES_WRITE_LOCK, () => new Promise(resolve => { window.releaseNoteLock = resolve; })); });
  await noteTabs[0].waitForFunction(() => Boolean(window.releaseNoteLock));
  const additions = noteTabs.map((tab, i) => tab.evaluate(async i => { window.addQueued = true; return window.notesApi.addNote('manual', `Tab ${i}`, `body ${i}`); }, i));
  for (const tab of noteTabs) await tab.waitForFunction(() => window.addQueued);
  await noteTabs[0].evaluate(() => window.releaseNoteLock());
  await Promise.all(additions);
  const both = await noteTabs[1].evaluate(() => window.notesApi.loadNotesState());
  assert.equal(both.error, ''); assert.equal(both.notes.length, 3);
  assert.equal(await noteTabs[1].evaluate(() => localStorage.getItem('vr-notes')), retainedLegacy);
  const newBackup = JSON.stringify({ schema_version:'vibe-notes.backup.v1', exported_at:'2026-10-23T00:00:00Z', notes:[{id:'imported',kind:'manual',title:'Imported',content:'synthetic',ts:2}] });
  await Promise.all([noteTabs[0].evaluate(() => window.notesApi.deleteNote('retained')), noteTabs[1].evaluate(raw => window.notesApi.importNotesBackupJson(raw), newBackup)]);
  assert.deepEqual((await noteTabs[0].evaluate(() => window.notesApi.loadNotesState().notes.map(n=>n.id))).sort(), [...both.notes.filter(n=>n.id!=='retained').map(n=>n.id),'imported'].sort());
  await noteTabs[0].evaluate(() => window.notesApi.clearNotes());
  await noteTabs[1].evaluate(() => window.notesApi.addNote('manual','After clear','synthetic'));
  await noteTabs[1].reload(); await noteTabs[1].evaluate(async () => { window.notesApi=await import('/src/lib/notes.ts'); });
  assert.deepEqual(await noteTabs[1].evaluate(() => window.notesApi.loadNotesState().notes.map(n=>n.title)), ['After clear']);
  const acknowledged = await noteTabs[0].evaluate(() => localStorage.getItem('vr-notes.v2'));
  await noteTabs[0].evaluate(() => localStorage.setItem('vr-notes','[]')); // Deliberately non-cooperating historical client.
  const conflictState = await noteTabs[1].evaluate(async () => { let rejected=false; try {await window.notesApi.addNote('manual','Blocked','synthetic');} catch {rejected=true;} return {rejected,state:window.notesApi.loadNotesState(),raw:localStorage.getItem('vr-notes.v2'),archive:JSON.parse(window.notesApi.notesRecoveryArchive())}; });
  assert.equal(conflictState.rejected,true); assert.match(conflictState.state.error,/旧版本页面/); assert.equal(conflictState.raw,acknowledged); assert.equal(conflictState.archive.legacyRaw,'[]');assert.equal(conflictState.archive.currentRaw,acknowledged);
  await notesContext.close();
  mark('native notes multi-tab add/delete/import/clear serialize; legacy bytes preserved and old-version conflict fails closed');

  const largeReceipt = await page.evaluate(async () => {
    const {reportPageMaterials}=await import('/src/lib/researchCheck.ts');
    const report={id:'many-pages',name:'synthetic.pdf',size:1,industry:'synthetic',ext:'.pdf',ts:1,file_sha256:'a'.repeat(64),page_count:200};
    const requested=Array.from({length:200},(_,i)=>i+1);
    const result={report_id:report.id,file_sha256:report.file_sha256,scope:'INDEXED_PAGE_TEXT_ONLY',full_report_read:false,requested,returned_chars:12000,complete_requested_text:false,coverage:{readable:requested.slice(0,8),omitted:requested.slice(8),invalid:[],unreadable:[],error:[]},items:requested.map(page=>page<=8?{page,status:'readable',reason:'AVAILABLE',text:'中'.repeat(1500),returned_chars:1500,indexed_chars:1500,truncated:false}:{page,status:'omitted',reason:'PAGE_BUDGET'})};
    const materials=await reportPageMaterials(report,result,'600001',1,200);
    const now=Date.now();const question={id:'large-q',securityCode:'600001',question:'bounded receipt',createdAt:now,origin:{kind:'manual',label:'synthetic',capturedAt:now}};
    const round={id:'large-r',questionId:question.id,securityCode:'600001',parentRoundId:null,createdAt:now,materials,calculation:null,judgement:'partial',limitations:'not full report',nextMaterial:'next',reviewedMaterialKeys:[],ignoredMaterialKeys:[],coverage:'partial'};
    const store=window.api.createResearchWorkflowStore({dbName:'many-pages'});await store.createQuestion({operationId:'large-op',question,initialRound:round});
    let reads=0;const original=IDBObjectStore.prototype.getAll;IDBObjectStore.prototype.getAll=function(...args){reads++;return original.apply(this,args);};
    let readback;try {await store.readWorkspace('600001',null);readback=await store.getQuestionContext('large-q');}finally{IDBObjectStore.prototype.getAll=original;}
    const backup=await store.exportBackup();const restored=window.api.createResearchWorkflowStore({dbName:'many-pages-restored'});await restored.importBackup(backup,'import-large');
    const restoredRound=(await restored.getQuestionContext('large-q')).rounds[0];
    const matches=JSON.stringify(restoredRound)===JSON.stringify(readback.rounds[0]);store.close();restored.close();return {reads,matches,materials:restoredRound.materials.length,bytes:new TextEncoder().encode(JSON.stringify(restoredRound)).length};
  });
  assert.deepEqual({...largeReceipt,bytes:0},{reads:8,matches:true,materials:200,bytes:0});assert.ok(largeReceipt.bytes<2*1024*1024);
  mark('200 requested pages/12000 text characters save, reopen and backup/import with v2 provenance; workspace reads use 8 getAll calls');

  await page.evaluate(checks => { document.body.innerText = ['Native IndexedDB acceptance', ...checks.map(check => `PASS ${check.name}`), 'Scope: synthetic data; lost-response is a same-operation retry simulation, not an injected delivery failure. Abort/quota faults are injected; no actual quota pressure, OS crash, private-mode retention or power-loss durability claim.'].join('\n\n'); }, checks);
  await page.screenshot({ path: join(output, 'native-indexeddb-acceptance.png'), fullPage: true });
  writeFileSync(join(output, 'results.json'), JSON.stringify({ status: 'PASS', engine: 'Chromium native IndexedDB', checks, limitations: ['Lost-response is a same-operation idempotency simulation, not an injected delivery failure', 'Synthetic quota/abort faults, not physical storage exhaustion', 'No OS crash/power-loss or private-mode retention proof', 'No real user migration or paid model call'] }, null, 2));
} catch (error) {
  writeFileSync(join(output, 'results.json'), JSON.stringify({ status: 'FAIL', checks, error: String(error?.stack || error) }, null, 2));
  if (page) await page.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await context?.close();
  await browser?.close();
  if (server?.listening) await new Promise(resolveClose => server.close(resolveClose));
}
