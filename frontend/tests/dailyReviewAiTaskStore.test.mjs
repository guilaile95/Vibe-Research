import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { create } from 'zustand';
import * as duration from '../src/lib/portfolioAdviceDuration.ts';
import * as metadata from '../src/stores/dailyReviewAiResultMetadata.ts';

const dateA = '2026-10-30', dateB = '2026-11-02';
const llm = { provider: 'openai-compatible', model: 'synthetic', revision: '1', baseURL: 'https://example.invalid', apiKey: 'synthetic' };
const key = 'vr-daily-review-duration-v1';
const result = date => ({ result_type: 'daily_review_ai', trade_date: date, schema_version: 'daily_review_ai.v2', generated_at: `${date} 16:00:00` });
const saved = date => ({ ...result(date), payload: { markdown: `Saved ${date}` } });
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
// Transpile the production store, with real Zustand and production helpers; only I/O is fake.
function harness(raw = null, storageThrows = false) {
  const streams = [], reads = [], values = new Map([[key, raw]]);
  const storage = {
    getItem(k) { if (storageThrows) throw new Error('Storage unavailable'); return values.get(k) ?? null; },
    setItem(k, v) { if (storageThrows) throw new Error('Storage unavailable'); values.set(k, v); },
  };
  class ApiError extends Error {}
  const modules = {
    zustand: { create }, '@/lib/portfolioAdviceDuration': duration,
    '@/stores/dailyReviewAiResultMetadata': metadata,
    '@/lib/api': { ApiError,
      dailyReviewAnalyzeStream: (body, handlers, signal) => { const d = deferred(); streams.push({ ...d, body, handlers, signal }); return d.promise; },
      api: { aiResult: (kind, date, signal) => { const d = deferred(); reads.push({ ...d, kind, date, signal }); return d.promise; } },
    },
  };
  const source = ts.transpileModule(readFileSync(new URL('../src/stores/dailyReviewAiTaskStore.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(source, { exports, AbortController, Date, localStorage: storage,
    require(name) { assert.ok(name in modules, name); return modules[name]; } });
  return { ...exports, store: exports.useDailyReviewAiTaskStore, streams, reads, values };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
async function finish(h, task, date = dateA) {
  h.streams.at(-1).resolve({ content: 'streamed', result: result(date) }); await tick();
  assert.equal(h.reads.at(-1).date, date);
  h.reads.at(-1).resolve(saved(date)); await task;
  assert.equal(h.store.getState().status, 'success');
  assert.equal(h.store.getState().content, `Saved ${date}`);
}

test('same-date remount preserves the running stream, duplicate start and authoritative backend date', async () => {
  const h = harness(), task = h.store.getState().start(llm, dateA);
  h.streams[0].handlers.onDelta('partial');
  const before = h.store.getState();
  await h.store.getState().restore(dateA); await h.store.getState().restore(dateA);
  await h.store.getState().start(llm, dateA);
  assert.equal(h.store.getState(), before);
  assert.equal(h.streams.length, 1); assert.equal(h.reads.length, 0);
  assert.equal(h.streams[0].signal.aborted, false);
  // Backend owns the analysis date; never fabricate/read back the UI's stale date.
  await finish(h, task, dateB);
});

test('a genuinely changed date cancels the old task and ignores its late completion', async () => {
  const h = harness(), task = h.store.getState().start(llm, dateA);
  h.streams[0].handlers.onDelta('partial');
  const restore = h.store.getState().restore(dateB);
  assert.equal(h.streams[0].signal.aborted, true);
  assert.equal(h.store.getState().streamContent, '');
  h.reads[0].resolve(saved(dateB)); await restore;
  h.streams[0].handlers.onDelta('late');
  h.streams[0].resolve({ content: 'old', result: result(dateA) }); await task;
  assert.equal(h.reads.length, 1);
  assert.equal(h.store.getState().content, `Saved ${dateB}`);
  assert.equal(h.store.getState().status, 'restored');
});

test('clear aborts readback and a new provider request cannot be overwritten by old readback', async () => {
  const h = harness(), first = h.store.getState().start(llm, dateA);
  h.streams[0].resolve({ content: 'old', result: result(dateA) }); await tick();
  h.store.getState().clear();
  assert.equal(h.reads[0].signal.aborted, true);
  assert.equal(h.store.getState().activeTradeDate, null);
  const next = { ...llm, provider: 'cli-codex', model: 'codex', revision: '2' };
  const second = h.store.getState().start(next, dateA);
  h.reads[0].resolve(saved(dateB)); await first;
  assert.equal(h.store.getState().status, 'running');
  assert.equal(h.store.getState().providerKey, 'cli-codex:codex');
  assert.equal(h.streams[1].body.llm.revision, '2');
  await finish(h, second);
});

test('restore races cannot overwrite generation or a newer date', async () => {
  const h = harness(), first = h.store.getState().restore(dateB);
  const second = h.store.getState().restore(dateA);
  assert.equal(h.reads[0].signal.aborted, true);
  const task = h.store.getState().start(llm, dateA);
  h.reads[1].resolve(saved(dateA)); await second;
  h.reads[0].reject(new Error('late')); await first;
  assert.equal(h.store.getState().status, 'running');
  await finish(h, task);
});

for (const raw of ['null', '123', '[]', '"bad"', '{', '{"openai-compatible:synthetic":123}', '{"openai-compatible:synthetic":{"length":1}}', '{"openai-compatible:synthetic":[null,"50",-1,0]}']) {
  test(`optional malformed duration cache never blocks or falsely fails generation: ${raw}`, async () => {
    const h = harness(raw);
    assert.equal(h.getEstimatedDuration(llm), 90_000);
    const task = h.store.getState().start(llm, dateA);
    await finish(h, task);
    h.recordSuccessfulDuration(llm, 60_000);
    assert.ok(JSON.parse(h.values.get(key))['openai-compatible:synthetic'].every(n => Number.isFinite(n) && n > 0));
  });
}

test('timing sanitizes samples, caps history, ignores invalid elapsed values and tolerates storage failure', async () => {
  const h = harness('{"openai-compatible:synthetic":[40000,null,"bad",60000,-1]}');
  assert.equal(h.getEstimatedDuration(llm), 50_000);
  for (const bad of [NaN, Infinity, 0, -1]) h.recordSuccessfulDuration(llm, bad);
  assert.equal(h.getEstimatedDuration(llm), 50_000);
  for (let i = 0; i < 10; i++) h.recordSuccessfulDuration(llm, 500_000);
  assert.equal(JSON.parse(h.values.get(key))['openai-compatible:synthetic'].length, 5);
  assert.equal(h.getEstimatedDuration(llm), 300_000);
  const blocked = harness(null, true), task = blocked.store.getState().start(llm, dateA);
  await finish(blocked, task);
});
