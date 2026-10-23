import { replayResearchCalculation } from './researchCheck.ts';
import {
  canonicalJson, parseLegacyResearchNotes, record, researchContentHash, ResearchWorkflowError,
  RESEARCH_BACKUP_SCHEMA, RESEARCH_DEFAULT_BUDGET_BYTES, utf8Bytes,
  validateResearchChains, validateResearchQuestion, validateResearchRound,
  type JsonValue, type LegacyResearchNote, type ResearchQuestion, type ResearchQuestionStatus, type ResearchRound,
} from './researchWorkflow.ts';

export const RESEARCH_DATABASE_NAME = 'vr-research-workflow';
export const RESEARCH_DATABASE_VERSION = 1;
const stores = ['questions', 'rounds', 'operations', 'legacySources'] as const;
type StoreName = typeof stores[number];
interface Operation { id: string; requestHash: string; request: JsonValue; response: JsonValue }
interface LegacySource { id: string; raw: string; notes: LegacyResearchNote[] }
interface Snapshot { questions: ResearchQuestion[]; rounds: ResearchRound[]; operations: Operation[]; legacySources: LegacySource[] }
export interface ResearchStoreOptions {
  dbName?: string;
  budgetBytes?: number;
  blockedTimeoutMs?: number;
  /** Schema lifecycle test / future compatible upgrade seam; production uses the exported version. */
  databaseVersion?: number;
}
export interface ResearchWriteOptions { signal?: AbortSignal }
export type NewResearchQuestion = Omit<ResearchQuestion, 'revision' | 'headRoundId' | 'reviewedMaterialKeys' | 'updatedAt' | 'status'> & { status?: ResearchQuestionStatus };
export interface CreateQuestionRequest { operationId: string; question: NewResearchQuestion; initialRound?: ResearchRound }
export interface AppendRoundRequest {
  operationId: string;
  questionId: string;
  expectedRevision: number;
  expectedHeadRoundId: string | null;
  round: ResearchRound;
  status?: ResearchQuestionStatus;
}
export interface SetQuestionStatusRequest {
  operationId: string;
  questionId: string;
  expectedRevision: number;
  expectedHeadRoundId: string | null;
  status: ResearchQuestionStatus;
}
export interface ResearchImportResult { addedQuestions: number; addedRounds: number }
export interface ResearchQuestionContext { question: ResearchQuestion; rounds: ResearchRound[] }
export interface LegacySourceState { sourceHash: string | null; imported: boolean; changed: boolean }
export interface LegacyImportPreview { sourceHash: string; notes: LegacyResearchNote[]; changed: boolean }
interface BackupPayload { schemaVersion: typeof RESEARCH_BACKUP_SCHEMA; exportedAt: string; data: Snapshot; manifest: { sha256: string; questionIds: string[]; roundIds: string[] } }
const emptySnapshot = (): Snapshot => ({ questions: [], rounds: [], operations: [], legacySources: [] });
const clone = <T>(value: T): T => JSON.parse(canonicalJson(value)) as T;
function validation(message: string): never { throw new ResearchWorkflowError('VALIDATION', message); }
function mapError(error: unknown): ResearchWorkflowError {
  if (error instanceof ResearchWorkflowError) return error;
  const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : '';
  if (name === 'QuotaExceededError') return new ResearchWorkflowError('BUDGET', '浏览器存储配额不足，已有研究与复核基线未更改；请保留草稿并导出备份');
  if (name === 'AbortError') return new ResearchWorkflowError('ABORT', '研究保存已撤销，已有研究与复核基线未更改');
  if (name === 'VersionError') return new ResearchWorkflowError('UNAVAILABLE', '研究库已由较新版本升级，请刷新到兼容版本；未降级或覆盖数据');
  return new ResearchWorkflowError('UNAVAILABLE', '无法访问浏览器研究库，未显示为空库或覆盖已有数据');
}
function operationId(value: string): string {
  if (typeof value !== 'string' || !value.trim() || value.length > 256) return validation('保存操作身份无效');
  return value;
}
function assertExpected(question: ResearchQuestion | undefined, request: { expectedRevision: number; expectedHeadRoundId: string | null }): asserts question is ResearchQuestion {
  if (!question || !Number.isSafeInteger(request.expectedRevision) || request.expectedRevision < 0 || question.revision !== request.expectedRevision || question.headRoundId !== request.expectedHeadRoundId) {
    throw new ResearchWorkflowError('CONFLICT', '此问题已在其他页面更新，请保留草稿、读取最新轮次后再决定如何保存；未自动改接研究链');
  }
}
function nextQuestion(question: ResearchQuestion, round: ResearchRound, status?: ResearchQuestionStatus): ResearchQuestion {
  if (round.questionId !== question.id || round.securityCode !== question.securityCode || round.parentRoundId !== question.headRoundId || round.createdAt < question.updatedAt) return validation('新轮次的问题、证券、父轮或时间不匹配');
  return validateResearchQuestion({ ...question, revision: question.revision + 1, headRoundId: round.id, updatedAt: round.createdAt, status: status ?? question.status,
    reviewedMaterialKeys: [...new Set([...question.reviewedMaterialKeys, ...round.reviewedMaterialKeys, ...round.ignoredMaterialKeys])].sort() });
}
/** The caller has already validated the complete snapshot, including every chain link. */
function questionRounds(state: Snapshot, question: ResearchQuestion): ResearchRound[] {
  const ordered: ResearchRound[] = [];
  let next = question.headRoundId;
  while (next !== null) { const round = state.rounds.find(entry => entry.id === next)!; ordered.unshift(round); next = round.parentRoundId; }
  return ordered;
}
function validateSnapshot(value: unknown): Snapshot {
  const v = record(value);
  if (Object.keys(v).some(key => !stores.includes(key as StoreName)) || stores.some(key => !Array.isArray(v[key]))) return validation('研究库备份集合不完整');
  const questions = (v.questions as unknown[]).map(validateResearchQuestion);
  const rounds = (v.rounds as unknown[]).map(validateResearchRound);
  validateResearchChains(questions, rounds);
  for (const round of rounds) if (round.calculation?.comparable) {
    let replayed;
    try { replayed = replayResearchCalculation(round.securityCode, round.calculation, round.materials); } catch { return validation('计算快照无法按所存输入重算'); }
    if (!replayed.comparable || ['kind', 'inputs', 'formula', 'result', 'unitConversionConfirmed'].some(key => canonicalJson((replayed as unknown as Record<string, unknown>)[key] ?? null) !== canonicalJson((round.calculation as unknown as Record<string, unknown>)[key] ?? null))) return validation('计算快照与所存输入重算结果不一致');
  }
  const operations = (v.operations as unknown[]).map(entry => {
    const op = record(entry);
    if (Object.keys(op).some(key => !['id', 'requestHash', 'request', 'response'].includes(key)) || typeof op.id !== 'string' || typeof op.requestHash !== 'string' || !/^[a-f0-9]{64}$/.test(op.requestHash) || !('response' in op) || !('request' in op)) return validation('操作收据无效');
    return { id: operationId(op.id), requestHash: op.requestHash, request: clone(op.request) as JsonValue, response: clone(op.response) as JsonValue };
  });
  const legacySources = (v.legacySources as unknown[]).map(entry => {
    const source = record(entry);
    if (Object.keys(source).some(key => !['id', 'raw', 'notes'].includes(key)) || typeof source.id !== 'string' || !/^[a-f0-9]{64}$/.test(source.id) || typeof source.raw !== 'string') return validation('旧记录导入收据无效');
    const notes = parseLegacyResearchNotes(source.raw);
    if (canonicalJson(source.notes) !== canonicalJson(notes)) return validation('旧记录原文与归档不一致');
    return { id: source.id, raw: source.raw, notes };
  });
  if (new Set(operations.map(op => op.id)).size !== operations.length || new Set(legacySources.map(source => source.id)).size !== legacySources.length) return validation('备份含重复操作或导入身份');
  const result = { questions, rounds, operations, legacySources };
  const context = receiptContext(result);
  for (const op of operations) validateReceipt(op, result, context);
  return result;
}

/** Imported idempotency receipts cannot manufacture a success for missing persisted work. */
function receiptContext(state: Snapshot) {
  const rounds = new Map(state.rounds.map(round => [round.id, round]));
  const questions = new Map(state.questions.map(question => [question.id, question]));
  const prefix = new Map<string, { count: number; baseline: string }>();
  for (const question of state.questions) {
    const chain: ResearchRound[] = [];
    let next = question.headRoundId;
    while (next !== null) { const round = rounds.get(next)!; chain.unshift(round); next = round.parentRoundId; }
    const processed = new Set<string>();
    for (const [index, round] of chain.entries()) {
      for (const key of [...round.reviewedMaterialKeys, ...round.ignoredMaterialKeys]) processed.add(key);
      prefix.set(round.id, { count: index + 1, baseline: canonicalJson([...processed].sort()) });
    }
  }
  return { rounds, questions, prefix };
}
function validateReceipt(op: Operation, state: Snapshot, context: ReturnType<typeof receiptContext>): void {
  const request = record(op.request);
  const response = record(op.response);
  const requestFields: Record<string, string[]> = { create: ['kind', 'question', 'initialRound'], append: ['kind', 'questionId', 'expectedRevision', 'expectedHeadRoundId', 'round', 'status'], status: ['kind', 'operationId', 'questionId', 'expectedRevision', 'expectedHeadRoundId', 'status'], import: ['kind', 'manifest'], legacy: ['kind', 'sourceHash'] };
  if (typeof request.kind !== 'string' || !requestFields[request.kind] || Object.keys(request).some(key => !requestFields[String(request.kind)].includes(key))) return validation('操作请求收据格式无效');
  if (['append', 'status'].includes(request.kind) && (!Number.isSafeInteger(request.expectedRevision) || Number(request.expectedRevision) < 0 || typeof request.questionId !== 'string' || (request.expectedHeadRoundId !== null && typeof request.expectedHeadRoundId !== 'string'))) return validation('操作请求的预期版本或链头无效');
  if (request.kind === 'status' && request.operationId !== op.id) return validation('状态操作身份不匹配');
  const verifyQuestion = (value: unknown): ResearchQuestion => {
    const q = validateResearchQuestion(value);
    const current = context.questions.get(q.id);
    if (!current || q.revision > current.revision || q.updatedAt > current.updatedAt || ['securityCode', 'question', 'origin', 'createdAt'].some(key => canonicalJson(q[key as keyof ResearchQuestion]) !== canonicalJson(current[key as keyof ResearchQuestion]))) return validation('操作收据引用了不存在或不同的问题');
    const head = q.headRoundId === null ? null : context.rounds.get(q.headRoundId);
    const prefix = q.headRoundId === null ? null : context.prefix.get(q.headRoundId);
    if (q.headRoundId === null) { if (q.status !== 'paused' || q.reviewedMaterialKeys.length) return validation('操作收据包含无效空链'); }
    else if (!head || !prefix || head.questionId !== q.id || head.securityCode !== q.securityCode || q.revision < prefix.count || q.updatedAt < head.createdAt || canonicalJson([...q.reviewedMaterialKeys].sort()) !== prefix.baseline) return validation('操作收据引用了缺失轮次或不匹配基线');
    return q;
  };
  if (request.kind === 'create') {
    const q = verifyQuestion(response);
    const base = validateResearchQuestion(request.question);
    if (base.id !== q.id || base.headRoundId !== null || base.revision !== 0 || base.reviewedMaterialKeys.length) return validation('创建收据与请求不匹配');
    const expected = request.initialRound === null ? base : nextQuestion(base, validateResearchRound(request.initialRound));
    if (canonicalJson(q) !== canonicalJson(expected)) validation('创建收据与原始提交不匹配');
  } else if (request.kind === 'append') {
    if (Object.keys(response).some(key => !['question', 'round'].includes(key))) validation('追加收据格式无效');
    const q = verifyQuestion(response.question);
    const round = validateResearchRound(response.round);
    const stored = context.rounds.get(round.id);
    if (!stored || canonicalJson(stored) !== canonicalJson(round) || canonicalJson(round) !== canonicalJson(request.round) || q.id !== request.questionId || q.headRoundId !== round.id || round.parentRoundId !== request.expectedHeadRoundId || q.revision !== Number(request.expectedRevision) + 1 || (request.status !== null && q.status !== request.status)) validation('追加收据与已保存轮次不匹配');
  } else if (request.kind === 'status') {
    const q = verifyQuestion(response);
    if (q.id !== request.questionId || q.revision !== Number(request.expectedRevision) + 1 || q.headRoundId !== request.expectedHeadRoundId || q.status !== request.status) validation('状态收据与请求不匹配');
  } else if (request.kind === 'legacy') {
    const source = state.legacySources.find(entry => entry.id === request.sourceHash);
    if (!source || response.sourceHash !== request.sourceHash || (response.added !== 0 && response.added !== source.notes.length) || Object.keys(response).some(key => !['sourceHash', 'added'].includes(key))) validation('旧记录收据引用缺失或不匹配的快照');
  } else if (request.kind === 'import') {
    const manifest = record(request.manifest);
    if (!Array.isArray(manifest.questionIds) || !Array.isArray(manifest.roundIds) || manifest.questionIds.some(id => !state.questions.some(q => q.id === id)) || manifest.roundIds.some(id => !state.rounds.some(r => r.id === id)) || Object.keys(response).some(key => !['addedQuestions', 'addedRounds'].includes(key))) validation('导入收据引用缺失研究');
    for (const [key, limit] of [['addedQuestions', manifest.questionIds.length], ['addedRounds', manifest.roundIds.length]] as const) if (!Number.isSafeInteger(response[key]) || Number(response[key]) < 0 || Number(response[key]) > limit) validation('导入收据计数无效');
  } else validation('操作收据类型未知');
}

export function createResearchWorkflowStore(options: ResearchStoreOptions = {}) {
  const dbName = options.dbName ?? RESEARCH_DATABASE_NAME;
  const version = options.databaseVersion ?? RESEARCH_DATABASE_VERSION;
  const budgetBytes = options.budgetBytes ?? RESEARCH_DEFAULT_BUDGET_BYTES;
  const blockedTimeoutMs = options.blockedTimeoutMs ?? 3000;
  if (!Number.isSafeInteger(budgetBytes) || budgetBytes < 1 || !Number.isSafeInteger(version) || version < 1 || !Number.isFinite(blockedTimeoutMs) || blockedTimeoutMs < 1) validation('研究库配置无效');
  let opening: Promise<IDBDatabase> | null = null;
  let connection: IDBDatabase | null = null;
  function database(): Promise<IDBDatabase> {
    if (opening) return opening;
    const promise = new Promise<IDBDatabase>((resolve, reject) => {
      if (!globalThis.indexedDB) { reject(new ResearchWorkflowError('UNAVAILABLE', '当前浏览器不支持独立研究库，未回退到旧笔记存储')); return; }
      let request: IDBOpenDBRequest;
      try { request = globalThis.indexedDB.open(dbName, version); } catch (error) { reject(mapError(error)); return; }
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const fail = (error: unknown) => { if (settled) return; settled = true; clearTimeout(timer); reject(mapError(error)); };
      request.onblocked = () => {
        if (timer || settled) return;
        timer = setTimeout(() => fail(new ResearchWorkflowError('BLOCKED', '其他研究页面阻止了数据库升级，请关闭旧研究页面后重试；草稿与旧数据未被删除')), blockedTimeoutMs);
      };
      request.onupgradeneeded = () => {
        if (settled) { request.transaction?.abort(); return; }
        const db = request.result;
        for (const name of stores) if (!db.objectStoreNames.contains(name)) {
          const store = db.createObjectStore(name, { keyPath: 'id' });
          if (name === 'questions') store.createIndex('securityCode', 'securityCode', { unique: false });
          if (name === 'rounds') store.createIndex('questionId', 'questionId', { unique: false });
        }
      };
      request.onerror = () => fail(request.error);
      request.onsuccess = () => {
        const db = request.result;
        if (settled) { db.close(); return; }
        settled = true;
        clearTimeout(timer);
        if (stores.some(name => !db.objectStoreNames.contains(name))) { db.close(); reject(new ResearchWorkflowError('UNAVAILABLE', '研究库结构不兼容，未覆盖数据')); return; }
        connection = db;
        db.onversionchange = () => { db.close(); if (connection === db) { connection = null; opening = null; } };
        db.onclose = () => { if (connection === db) { connection = null; opening = null; } };
        resolve(db);
      };
    });
    opening = promise;
    void promise.catch(() => { if (opening === promise) opening = null; });
    return promise;
  }
  /** All async hashing happens before this transaction. Request callbacks only perform synchronous work. */
  async function transact<T>(mode: IDBTransactionMode, work: (snapshot: Snapshot) => T, writeOptions: ResearchWriteOptions = {}): Promise<T> {
    if (writeOptions.signal?.aborted) throw new ResearchWorkflowError('ABORT', '研究保存已撤销，已有数据未更改');
    const db = await database();
    if (writeOptions.signal?.aborted) throw new ResearchWorkflowError('ABORT', '研究保存已撤销，已有数据未更改');
    return new Promise<T>((resolve, reject) => {
      let tx: IDBTransaction;
      try { tx = db.transaction([...stores], mode); } catch (error) { reject(mapError(error)); return; }
      let result: T;
      let failure: unknown;
      let loaded = 0;
      const snapshot = emptySnapshot();
      const abort = () => { failure = new ResearchWorkflowError('ABORT', '研究保存已撤销，已有研究与复核基线未更改'); try { tx.abort(); } catch { /* Already completed, the completion handler owns the outcome. */ } };
      const cleanup = () => writeOptions.signal?.removeEventListener('abort', abort);
      writeOptions.signal?.addEventListener('abort', abort, { once: true });
      tx.onabort = () => { cleanup(); reject(mapError(failure ?? tx.error ?? new DOMException('Transaction aborted', 'AbortError'))); };
      tx.onerror = () => { /* The request error aborts the whole transaction; onabort is the sole rejection path. */ };
      tx.oncomplete = () => { cleanup(); resolve(clone(result)); };
      for (const name of stores) {
        const request = tx.objectStore(name).getAll();
        request.onsuccess = () => {
          (snapshot[name] as unknown[]) = request.result;
          loaded++;
          if (loaded !== stores.length) return;
          try {
            // A corrupt store is an error, never an invitation to overwrite it with an empty array.
            validateSnapshot(snapshot);
            const before = new Map(stores.map(storeName => [storeName, new Map(snapshot[storeName].map(entry => [entry.id, canonicalJson(entry)]))]));
            result = work(snapshot);
            if (mode === 'readwrite') {
              validateSnapshot(snapshot);
              if (utf8Bytes(canonicalJson(snapshot)) > budgetBytes) throw new ResearchWorkflowError('BUDGET', `研究库超过 ${budgetBytes} 字节预算；本次整笔未保存，未截断研究链或删除旧轮次`);
              for (const storeName of stores) for (const entry of snapshot[storeName]) {
                const prior = before.get(storeName)!.get(entry.id);
                if (prior !== canonicalJson(entry)) {
                  const store = tx.objectStore(storeName);
                  if (prior === undefined) store.add(entry); else store.put(entry);
                }
              }
            }
          } catch (error) { failure = error; try { tx.abort(); } catch { reject(mapError(error)); } }
        };
      }
    });
  }
  async function mutate<T>(id: string, request: unknown, change: (state: Snapshot) => T, writeOptions?: ResearchWriteOptions): Promise<T> {
    const opId = operationId(id);
    const requestHash = await researchContentHash(canonicalJson(request));
    return transact('readwrite', state => {
      const previous = state.operations.find(op => op.id === opId);
      if (previous) {
        if (previous.requestHash !== requestHash) throw new ResearchWorkflowError('IDEMPOTENCY', '同一保存操作身份对应了不同内容，请保留原草稿并明确开始新的保存');
        return clone(previous.response) as T;
      }
      const response = change(state);
      state.operations.push({ id: opId, requestHash, request: clone(request) as JsonValue, response: clone(response) as JsonValue });
      return response;
    }, writeOptions);
  }
  async function sourceState(raw: string | null, state: Snapshot): Promise<LegacySourceState> {
    const sourceHash = raw === null ? null : await researchContentHash(raw);
    return { sourceHash, imported: sourceHash !== null && state.legacySources.some(source => source.id === sourceHash), changed: state.legacySources.length > 0 && !state.legacySources.some(source => source.id === sourceHash) };
  }
  return {
    async createQuestion(request: CreateQuestionRequest, writeOptions?: ResearchWriteOptions): Promise<ResearchQuestion> {
      const base = validateResearchQuestion({ ...request.question, updatedAt: request.question.createdAt, revision: 0, headRoundId: null, reviewedMaterialKeys: [], status: request.question.status ?? 'watching' });
      const firstRound = request.initialRound === undefined ? null : validateResearchRound(request.initialRound);
      const normalized = { kind: 'create', question: base, initialRound: firstRound };
      return mutate(request.operationId, normalized, state => {
        if (state.questions.some(question => question.id === base.id)) throw new ResearchWorkflowError('CONFLICT', '问题身份已存在，未覆盖原研究');
        const question = firstRound ? nextQuestion(base, firstRound) : base;
        if (firstRound) {
          if (state.rounds.some(round => round.id === firstRound.id)) throw new ResearchWorkflowError('CONFLICT', '研究轮次身份已存在');
          state.rounds.push(firstRound);
        }
        state.questions.push(question);
        return question;
      }, writeOptions);
    },
    async appendRound(request: AppendRoundRequest, writeOptions?: ResearchWriteOptions): Promise<{ question: ResearchQuestion; round: ResearchRound }> {
      const round = validateResearchRound(request.round);
      const normalized = { kind: 'append', questionId: request.questionId, expectedRevision: request.expectedRevision, expectedHeadRoundId: request.expectedHeadRoundId, round, status: request.status ?? null };
      return mutate(request.operationId, normalized, state => {
        const current = state.questions.find(question => question.id === request.questionId);
        assertExpected(current, request);
        if (state.rounds.some(existing => existing.id === round.id)) throw new ResearchWorkflowError('CONFLICT', '研究轮次身份已存在，未覆盖不可变轮次');
        const question = nextQuestion(current, round, request.status);
        state.questions[state.questions.indexOf(current)] = question;
        state.rounds.push(round);
        return { question, round };
      }, writeOptions);
    },
    async setStatus(request: SetQuestionStatusRequest, writeOptions?: ResearchWriteOptions): Promise<ResearchQuestion> {
      return mutate(request.operationId, { kind: 'status', ...request }, state => {
        const current = state.questions.find(question => question.id === request.questionId);
        assertExpected(current, request);
        const next = validateResearchQuestion({ ...current, status: request.status, revision: current.revision + 1 });
        state.questions[state.questions.indexOf(current)] = next;
        return next;
      }, writeOptions);
    },
    async listQuestions(securityCode?: string): Promise<ResearchQuestion[]> {
      return transact('readonly', state => state.questions.filter(question => securityCode === undefined || question.securityCode === securityCode).sort((a, b) => b.updatedAt - a.updatedAt || a.id.localeCompare(b.id)));
    },
    async getQuestion(id: string): Promise<ResearchQuestion | null> { return transact('readonly', state => state.questions.find(question => question.id === id) ?? null); },
    async getQuestionContext(questionId: string): Promise<ResearchQuestionContext | null> {
      return transact('readonly', state => {
        const question = state.questions.find(entry => entry.id === questionId);
        return question ? { question, rounds: questionRounds(state, question) } : null;
      });
    },
    async getRounds(questionId: string): Promise<ResearchRound[]> {
      return transact('readonly', state => {
        const question = state.questions.find(entry => entry.id === questionId);
        return question ? questionRounds(state, question) : [];
      });
    },
    async exportBackup(): Promise<string> {
      const data = await transact('readonly', state => state);
      const manifest = { sha256: await researchContentHash(canonicalJson(data)), questionIds: data.questions.map(question => question.id).sort(), roundIds: data.rounds.map(round => round.id).sort() };
      const payload: BackupPayload = { schemaVersion: RESEARCH_BACKUP_SCHEMA, exportedAt: new Date().toISOString(), data, manifest };
      return `${JSON.stringify(payload)}\n`;
    },
    async importBackup(raw: string, id: string, writeOptions?: ResearchWriteOptions): Promise<ResearchImportResult> {
      // A bounded parser rejects oversized files before parsing or opening a write transaction.
      if (utf8Bytes(raw) > budgetBytes * 4) throw new ResearchWorkflowError('BUDGET', '研究备份超过可验证预算，未执行部分导入');
      let parsed: unknown;
      try { parsed = JSON.parse(raw); } catch { return validation('研究备份不是有效 JSON'); }
      const p = record(parsed);
      if (Object.keys(p).some(key => !['schemaVersion', 'exportedAt', 'data', 'manifest'].includes(key)) || p.schemaVersion !== RESEARCH_BACKUP_SCHEMA || typeof p.exportedAt !== 'string' || !Number.isFinite(Date.parse(p.exportedAt))) return validation('不支持的研究备份版本或导出时间');
      const data = validateSnapshot(p.data);
      const manifest = record(p.manifest);
      const expectedManifest = { sha256: await researchContentHash(canonicalJson(data)), questionIds: data.questions.map(question => question.id).sort(), roundIds: data.rounds.map(round => round.id).sort() };
      if (canonicalJson(manifest) !== canonicalJson(expectedManifest)) return validation('研究备份校验不一致，未导入任何链');
      for (const op of data.operations) if (await researchContentHash(canonicalJson(op.request)) !== op.requestHash) return validation('操作收据请求哈希不一致');
      for (const source of data.legacySources) if (await researchContentHash(source.raw) !== source.id) return validation('旧记录原始快照哈希不一致');
      return mutate(id, { kind: 'import', manifest: expectedManifest }, state => {
        let addedQuestions = 0;
        let addedRounds = 0;
        // Do not splice an imported stale head into an existing live chain. Exact duplicate is safe.
        for (const name of stores) for (const incoming of data[name]) {
          const target = state[name] as Array<{ id: string }>;
          const existing = target.find(entry => entry.id === incoming.id);
          if (existing) {
            if (canonicalJson(existing) !== canonicalJson(incoming)) throw new ResearchWorkflowError('CONFLICT', '导入与已有同身份研究内容或链头冲突，整笔未导入');
          } else {
            if (name === 'operations' && incoming.id === id) throw new ResearchWorkflowError('IDEMPOTENCY', '导入操作身份与备份收据冲突');
            target.push(incoming);
            if (name === 'questions') addedQuestions++;
            if (name === 'rounds') addedRounds++;
          }
        }
        return { addedQuestions, addedRounds };
      }, writeOptions);
    },
    async previewLegacy(raw: string | null): Promise<LegacyImportPreview> {
      const notes = parseLegacyResearchNotes(raw);
      const state = await transact('readonly', snapshot => snapshot);
      const result = await sourceState(raw, state);
      return { sourceHash: result.sourceHash ?? await researchContentHash('[]'), notes, changed: result.changed };
    },
    async importLegacy(raw: string, id: string, writeOptions?: ResearchWriteOptions): Promise<{ sourceHash: string; added: number }> {
      if (utf8Bytes(raw) > budgetBytes) throw new ResearchWorkflowError('BUDGET', '旧记录超过研究库字节预算，未截断或修改旧记录');
      const notes = parseLegacyResearchNotes(raw);
      const sourceHash = await researchContentHash(raw);
      const result = await mutate(id, { kind: 'legacy', sourceHash }, state => {
        if (state.legacySources.some(source => source.id === sourceHash)) return { sourceHash, added: 0 };
        // Changed old pages are retained as a separate read-only source snapshot, never a new head.
        state.legacySources.push({ id: sourceHash, raw, notes });
        return { sourceHash, added: notes.length };
      }, writeOptions);
      const verified = await transact('readonly', state => state.legacySources.find(source => source.id === sourceHash)?.raw ?? null);
      if (verified !== raw) throw new ResearchWorkflowError('UNAVAILABLE', '旧记录导入已提交但读回无法确认，请保留原始数据并使用同一操作身份重试');
      return result;
    },
    async checkLegacySource(raw: string | null): Promise<LegacySourceState> {
      const state = await transact('readonly', snapshot => snapshot);
      return sourceState(raw, state);
    },
    async listLegacyNotes(): Promise<LegacyResearchNote[]> {
      return transact('readonly', state => state.legacySources.flatMap(source => source.notes));
    },
    close(): void { connection?.close(); connection = null; opening = null; },
  };
}
export type ResearchWorkflowStore = ReturnType<typeof createResearchWorkflowStore>;
/** No database is opened and no legacy localStorage is read until an explicit method is called. */
export const researchWorkflowStore = createResearchWorkflowStore();
