import test from 'node:test';
import assert from 'node:assert/strict';
import { canonicalJson, materialKey, parseLegacyResearchNotes, researchContentHash, validateResearchChains, validateResearchMaterial, validateResearchQuestion, validateResearchRound, type ResearchMaterial, type ResearchQuestion, type ResearchRound } from '../src/lib/researchWorkflow.ts';
import { createResearchWorkflowStore } from '../src/lib/researchWorkflowStore.ts';

const material = (overrides: Partial<ResearchMaterial> = {}): ResearchMaterial => ({ id: 'source', version: 'v1', securityCode: '301213', title: '合成预告原文', content: '归母净利润 648.13 至 753.93 万元。', sourceUrl: 'https://example.org/report.pdf', sourceKind: 'evidence_excerpt', sourceHash: null, publishedAt: '2025-01-24', capturedAt: 1, readRange: { pages: [], totalPages: null, truncated: false, ocr: false, description: '仅所选摘录，不是公告全文' }, availability: 'partial', provenance: { provided: 'synthetic', receipt: { requestedPages: [1], unknown: null } }, ...overrides });
const round = (overrides: Partial<ResearchRound> = {}): ResearchRound => ({ id: 'r1', questionId: 'q1', securityCode: '301213', parentRoundId: null, createdAt: 2, materials: [material()], calculation: null, judgement: '当时预计盈利，尚非实际业绩。', limitations: '合成存储用例，不代表市场核验。', nextMaterial: '实际业绩披露', reviewedMaterialKeys: [materialKey(material())], ignoredMaterialKeys: [], coverage: 'partial', ...overrides });
const question = (overrides: Partial<ResearchQuestion> = {}): ResearchQuestion => ({ id: 'q1', securityCode: '301213', question: '预告是否修订？', origin: { kind: 'candidate', label: '手工研究', url: '/candidates/301213', capturedAt: 1 }, createdAt: 1, updatedAt: 2, revision: 1, headRoundId: 'r1', status: 'watching', reviewedMaterialKeys: [materialKey(material())], ...overrides });

test('full snapshots retain actual text, original provenance and explicit partial read range', () => {
  const saved = validateResearchRound(round());
  assert.deepEqual(saved, round());
  assert.notEqual(saved, round());
  assert.equal(saved.materials[0].content, material().content);
  assert.deepEqual(saved.materials[0].provenance, material().provenance);
});
test('safe origin and material identity prevent cross-stock and unsafe link activation', () => {
  assert.throws(() => validateResearchQuestion(question({ origin: { kind: 'candidate', label: 'x', url: '/candidates/688041', capturedAt: 1 } })), /证券/);
  assert.throws(() => validateResearchRound(round({ materials: [material({ securityCode: '688041' })] })), /跨证券/);
  for (const sourceUrl of ['javascript:alert(1)', '//attacker.invalid', '/\\attacker.invalid', 'https://user:pass@example.org']) assert.throws(() => validateResearchMaterial(material({ sourceUrl })), /链接/);
  assert.notEqual(materialKey({ id: 'a@b', version: 'c' }), materialKey({ id: 'a', version: 'b@c' }));
});
test('partial, absent or truncated input cannot become completed or reviewed by a flag', () => {
  assert.throws(() => validateResearchRound(round({ coverage: 'complete' })), /部分读取/);
  assert.throws(() => validateResearchMaterial(material({ availability: 'full', readRange: { ...material().readRange, truncated: true } })), /不完整/);
  assert.throws(() => validateResearchMaterial(material({ availability: 'full', content: '' })), /正文/);
  assert.throws(() => validateResearchRound(round({ materials: [material({ availability: 'link_only', content: '' })] })), /不能标为已读/);
  assert.throws(() => validateResearchRound(round({ reviewedMaterialKeys: ['missing@v1'] })), /不在本轮/);
  assert.throws(() => validateResearchRound(round({ ignoredMaterialKeys: [materialKey(material())] })), /重复处理/);
});
test('complete chain validator rejects orphan, cycle, wrong head, cross-stock and forged baseline', () => {
  validateResearchChains([question()], [round()]);
  assert.throws(() => validateResearchChains([question()], [round({ parentRoundId: 'missing' })]), /缺父/);
  assert.throws(() => validateResearchChains([question()], [round({ parentRoundId: 'r1' })]), /成环/);
  assert.throws(() => validateResearchChains([question({ headRoundId: null })], [round()]), /空研究/);
  assert.throws(() => validateResearchChains([question()], [round(), round({ id: 'orphan' })]), /孤立/);
  assert.throws(() => validateResearchChains([question({ reviewedMaterialKeys: [] })], [round()]), /基线/);
  assert.throws(() => validateResearchChains([question({ securityCode: '688041', origin: { kind: 'manual', label: 'x', capturedAt: 1 } })], [round()]), /跨证券/);
  assert.throws(() => validateResearchChains([question()], [round(), round()]), /重复/);
});
test('explicit paused empty question is a draft, never an active imported empty chain', () => {
  validateResearchChains([question({ status: 'paused', headRoundId: null, revision: 0, reviewedMaterialKeys: [] })], []);
  assert.throws(() => validateResearchChains([question({ headRoundId: null, revision: 0, reviewedMaterialKeys: [] })], []), /暂停草稿/);
});
test('unknown future fields and malformed JSON fail closed, never whitelist truncate a new chain', () => {
  assert.throws(() => validateResearchQuestion({ ...question(), futureWorkflow: 'preserve me' }), /未知字段/);
  assert.throws(() => canonicalJson({ a: Infinity }), /非有限/);
  assert.throws(() => canonicalJson({ a: undefined }), /完整 JSON/);
  assert.throws(() => parseLegacyResearchNotes('[broken'), /原始数据未变更/);
});
test('explicit legacy parser preserves unknown fields and accepts more than 200 without slicing', () => {
  const raw = JSON.stringify(Array.from({ length: 250 }, (_, index) => ({ id: `old-${index}`, kind: '问AI', title: '旧记录', content: '原文', ts: index, research: { securityCode: '301213', question: '旧问题' }, unknownMetadata: { retain: [true, 'all'] } })));
  const notes = parseLegacyResearchNotes(raw);
  assert.equal(notes.length, 250);
  assert.deepEqual(notes[0].payload.unknownMetadata, { retain: [true, 'all'] });
  assert.equal(notes[0].securityCode, '301213');
  assert.deepEqual(JSON.parse(raw), notes.map(note => note.payload));
});
test('100 / 200 / 1000 synthetic immutable rounds validate without a record-count cutoff', () => {
  for (const count of [100, 200, 1000]) {
    const rounds = Array.from({ length: count }, (_, index) => round({ id: `r${index + 1}`, parentRoundId: index ? `r${index}` : null, createdAt: index + 2 }));
    validateResearchChains([question({ headRoundId: `r${count}`, revision: count, updatedAt: count + 1 })], rounds);
  }
});
test('per-round serialized byte budget rejects a full write rather than trimming selected material', () => {
  const sources = [material({ content: '中'.repeat(370_000) }), material({ id: 'second', content: '中'.repeat(370_000) })];
  assert.throws(() => validateResearchRound(round({ materials: sources })), error => (error as { code: string }).code === 'BUDGET');
});
test('unknown/refused calculation can be saved without claiming a completed calculation', () => {
  const refused = { kind: 'interval_contains' as const, inputs: [], formula: '', result: '不能比较', comparable: false, reason: '未取得原文' };
  assert.deepEqual(validateResearchRound(round({ calculation: refused })).calculation, refused);
  assert.throws(() => validateResearchRound(round({ calculation: { ...refused, comparable: true } })), /尚不支持/);
});
test('hashes are deterministic canonical checksums, not a claim that contents are authentic', async () => {
  assert.equal(await researchContentHash(canonicalJson({ b: 2, a: 1 })), await researchContentHash(canonicalJson({ a: 1, b: 2 })));
});
test('missing IndexedDB is an explicit error and never silently falls back to old localStorage', async () => {
  const store = createResearchWorkflowStore({ dbName: 'test-no-browser' });
  await assert.rejects(store.listQuestions(), error => (error as { code: string }).code === 'UNAVAILABLE');
});

test('the same material version cannot silently change original payload between rounds', () => {
  const newer = round({ id: 'r2', parentRoundId: 'r1', createdAt: 3, materials: [material({ content: 'same version but changed body' })] });
  assert.throws(() => validateResearchChains([question({ headRoundId: 'r2', revision: 2, updatedAt: 3 })], [round(), newer]), /同一材料版本/);
});

test('same source version may retain different per-read coverage receipts without rewriting past rounds', () => {
  const later = material({ capturedAt: 3, readRange: { ...material().readRange, description: '再次读取：不同的请求范围' }, provenance: { requestedPages: [1, 2] } });
  const newer = round({ id: 'r2', parentRoundId: 'r1', createdAt: 3, materials: [later] });
  validateResearchChains([question({ headRoundId: 'r2', revision: 2, updatedAt: 3 })], [round(), newer]);
  assert.notDeepEqual(newer.materials[0].provenance, round().materials[0].provenance);
});
