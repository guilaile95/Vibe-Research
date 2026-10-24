/** Browser-local research snapshots. Never Evidence, Campaign, Thesis or Decision authority. */
import { parseLocalReportOcrReceipt, validateReportPageOcrResponse } from './localReportOcr.ts';
import { parseDiscoveryResearchOrigin, type DiscoveryResearchOrigin } from './discoveryResearchOrigin.ts';
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type ResearchQuestionStatus = 'watching' | 'resolved' | 'paused' | 'archived';
export interface ResearchOrigin {
  kind: 'candidate' | 'discovery' | 'manual' | 'legacy';
  label: string;
  url?: string;
  capturedAt: number;
  snapshot?: DiscoveryResearchOrigin;
}
export interface ResearchQuestion {
  id: string;
  securityCode: string;
  question: string;
  origin: ResearchOrigin;
  createdAt: number;
  updatedAt: number;
  revision: number;
  headRoundId: string | null;
  status: ResearchQuestionStatus;
  /** Processed baseline: explicitly reviewed OR explicitly ignored in committed rounds only. */
  reviewedMaterialKeys: string[];
}
export interface ResearchMaterial {
  id: string;
  version: string;
  securityCode: string;
  title: string;
  /** Exact selected/read payload, never regenerated from a URL on restore. */
  content: string;
  sourceUrl: string | null;
  sourceKind: 'evidence_excerpt' | 'report_pages' | 'manual' | 'legacy';
  /** Original file/version hash if supplied by the source; null means unknown. */
  sourceHash: string | null;
  publishedAt: string | null;
  capturedAt: number;
  readRange: { pages: number[]; totalPages: number | null; truncated: boolean; ocr: boolean; description: string };
  availability: 'full' | 'partial' | 'link_only' | 'unavailable';
  /** Versioned source receipt or page-specific receipt with request coverage. Not independent verification. */
  provenance?: Record<string, JsonValue>;
}
export interface ResearchCalculationInput {
  label: string;
  value: string;
  unit: string;
  currency: string;
  period: string;
  subject: string;
  metric: string;
  basis: string;
  valueType: 'forecast' | 'actual';
  materialKey: string;
  page: number | null;
  sourceExcerpt: string;
  confirmed: boolean;
}
/** A frozen calculation record, not a claim of independent input/result verification. */
export interface ResearchCalculation {
  kind: 'interval_contains' | 'yoy' | 'profit_cashflow';
  inputs: ResearchCalculationInput[];
  formula: string;
  result: string;
  comparable: boolean;
  reason: string;
  unitConversionConfirmed?: boolean;
}
export interface ResearchRound {
  id: string;
  questionId: string;
  securityCode: string;
  parentRoundId: string | null;
  createdAt: number;
  materials: ResearchMaterial[];
  calculation: ResearchCalculation | null;
  judgement: string;
  limitations: string;
  nextMaterial: string;
  reviewedMaterialKeys: string[];
  ignoredMaterialKeys: string[];
  coverage: 'partial' | 'complete';
}
export interface LegacyResearchNote {
  id: string;
  kind: string;
  title: string;
  content: string;
  ts: number;
  securityCode: string | null;
  /** Preserve all legacy fields, including metadata unknown to the old whitelist parser. */
  payload: Record<string, JsonValue>;
}
export type ResearchWorkflowErrorCode = 'VALIDATION' | 'CONFLICT' | 'IDEMPOTENCY' | 'BUDGET' | 'ABORT' | 'BLOCKED' | 'UNAVAILABLE';
export class ResearchWorkflowError extends Error {
  readonly code: ResearchWorkflowErrorCode;
  constructor(code: ResearchWorkflowErrorCode, message: string) {
    super(message);
    this.name = 'ResearchWorkflowError';
    this.code = code;
  }
}
export const RESEARCH_BACKUP_SCHEMA = 'vibe-research.backup.v1';
export const RESEARCH_DEFAULT_BUDGET_BYTES = 16 * 1024 * 1024;
export const RESEARCH_ROUND_BUDGET_BYTES = 2 * 1024 * 1024;
export const researchMaterialKey = (material: Pick<ResearchMaterial, 'id' | 'version'>): string => `${encodeURIComponent(material.id)}@${encodeURIComponent(material.version)}`;
export const materialKey = researchMaterialKey;
export const utf8Bytes = (value: string): number => new TextEncoder().encode(value).byteLength;
function fail(message: string): never { throw new ResearchWorkflowError('VALIDATION', message); }
export const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail('研究记录对象格式无效');
  return value as Record<string, unknown>;
};
const keys = (value: Record<string, unknown>, allowed: string[]) => {
  if (Object.keys(value).some(key => !allowed.includes(key))) fail('研究记录含未知字段，未静默丢弃');
};
const str = (value: unknown, label: string, allowEmpty = false, max = 100_000): string => {
  if (typeof value !== 'string' || (!allowEmpty && !value.trim()) || value.length > max) return fail(`${label}无效`);
  return value;
};
const num = (value: unknown, label: string, integer = false): number => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || (integer && !Number.isSafeInteger(value))) return fail(`${label}无效`);
  return value;
};
const bool = (value: unknown): boolean => typeof value === 'boolean' ? value : fail('研究记录布尔字段无效');
const oneOf = <T extends string>(value: unknown, choices: readonly T[]): T => choices.includes(value as T) ? value as T : fail('研究记录枚举值无效');
const code = (value: unknown): string => typeof value === 'string' && /^\d{6}$/.test(value) ? value : fail('研究证券代码无效');
const id = (value: unknown): string => str(value, '研究身份', false, 256);
const nullableId = (value: unknown) => value === null ? null : id(value);
const stringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) return fail('材料身份集合无效');
  const parsed = value.map(entry => str(entry, '材料身份', false, 2048));
  if (new Set(parsed).size !== parsed.length) fail('材料身份重复');
  return parsed;
};
export function safeWorkflowUrl(value: string): boolean {
  if (value.startsWith('/')) return !value.startsWith('//') && !/[\\\u0000-\u0020]/.test(value);
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password; } catch { return false; }
}
/** Canonical JSON is for equality/checksums, not a digital signature or authenticity claim. */
export function canonicalJson(value: unknown): string {
  const visit = (entry: unknown, depth: number): string => {
    if (depth > 32) return fail('研究记录嵌套过深');
    if (entry === null || typeof entry === 'string' || typeof entry === 'boolean') return JSON.stringify(entry);
    if (typeof entry === 'number') return Number.isFinite(entry) ? JSON.stringify(entry) : fail('研究记录包含非有限数字');
    if (Array.isArray(entry)) return `[${entry.map(item => visit(item, depth + 1)).join(',')}]`;
    if (entry && typeof entry === 'object' && Object.getPrototypeOf(entry) === Object.prototype) {
      return `{${Object.keys(entry).sort().map(key => `${JSON.stringify(key)}:${visit((entry as Record<string, unknown>)[key], depth + 1)}`).join(',')}}`;
    }
    return fail('研究记录必须是完整 JSON 数据');
  };
  return visit(value, 0);
}
export async function researchContentHash(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new ResearchWorkflowError('UNAVAILABLE', '当前环境缺少安全校验能力，未保存研究记录');
  const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
}
export function validateResearchQuestion(value: unknown): ResearchQuestion {
  const v = record(value);
  keys(v, ['id', 'securityCode', 'question', 'origin', 'createdAt', 'updatedAt', 'revision', 'headRoundId', 'status', 'reviewedMaterialKeys']);
  const o = record(v.origin);
  keys(o, ['kind', 'label', 'url', 'capturedAt', 'snapshot']);
  const securityCode = code(v.securityCode);
  const origin: ResearchOrigin = { kind: oneOf(o.kind, ['candidate', 'discovery', 'manual', 'legacy']), label: str(o.label, '问题来由', false, 20_000), capturedAt: num(o.capturedAt, '来由时间') };
  if (o.snapshot !== undefined) {
    const snapshot = parseDiscoveryResearchOrigin(o.snapshot, securityCode);
    if (!snapshot || origin.kind !== 'discovery' || snapshot.capturedAt > origin.capturedAt) fail('原发现来由快照无效、跨证券或时间不匹配');
    origin.snapshot = snapshot;
  }
  if (o.url !== undefined) {
    origin.url = str(o.url, '问题来由链接', false, 4096);
    if (!safeWorkflowUrl(origin.url)) fail('问题来由链接不安全');
    const candidate = origin.url.match(/^\/candidates\/(\d{6})(?:[/?#]|$)/);
    if (candidate && candidate[1] !== securityCode) fail('问题来由与证券不一致');
  }
  const question: ResearchQuestion = { id: id(v.id), securityCode, question: str(v.question, '研究问题'), origin,
    createdAt: num(v.createdAt, '问题创建时间'), updatedAt: num(v.updatedAt, '问题更新时间'), revision: num(v.revision, '问题版本', true),
    headRoundId: nullableId(v.headRoundId), status: oneOf(v.status, ['watching', 'resolved', 'paused', 'archived']), reviewedMaterialKeys: stringArray(v.reviewedMaterialKeys) };
  if (question.updatedAt < question.createdAt || question.origin.capturedAt > question.createdAt) fail('问题时间顺序无效');
  return question;
}
/** Structural consistency only: the original receipt digest is not an authenticity proof. */
function validatePageProvenance(material: ResearchMaterial): void {
  const provenance = material.provenance;
  if (!provenance || provenance.page_receipt === undefined) return; // Historical generic provenance.
  const receipt = record(provenance.page_receipt), report = record(provenance.report), assignment = record(provenance.security_assignment);
  const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  if (material.sourceKind !== 'report_pages' || !hash(material.sourceHash) || report.file_sha256 !== material.sourceHash
    || assignment.code !== material.securityCode || assignment.basis !== 'USER_CONFIRMED_FROM_ORIGINAL_PAGE' || assignment.automatically_verified !== false) fail('原页来源或证券归属不一致');
  const reportId = str(report.id, '报告身份');
  let reportUrl: string | null = null;
  if (typeof report.source_url === 'string' && report.source_url) {
    try { const url = new URL(report.source_url); if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) reportUrl = url.href; } catch { /* Unsafe original URL is preserved only as provenance. */ }
  }
  if (material.sourceUrl !== reportUrl || typeof report.title !== 'string') fail('报告链接或标题无效');
  let request: Record<string, unknown>, item: Record<string, unknown>;
  if (receipt.schema_version !== undefined || receipt.request !== undefined || receipt.item !== undefined || receipt.original_receipt_sha256 !== undefined) {
    keys(receipt, ['schema_version', 'original_receipt_sha256', 'request', 'item']);
    if (receipt.schema_version !== 'report-page-projection.v2' || !hash(receipt.original_receipt_sha256)) fail('原页投影版本或摘要无效');
    request = record(receipt.request); item = record(receipt.item);
    keys(request, ['report_id', 'file_sha256', 'scope', 'full_report_read', 'requested', 'returned_chars', 'complete_requested_text', 'coverage', 'extraction']);
  } else {
    // Original full receipts remain readable without rewriting their representation.
    request = receipt;
    const requested = request.requested;
    if (!Array.isArray(requested) || !requested.length) fail('原页请求范围无效');
    validateReportPageOcrResponse(receipt, reportId, material.sourceHash!, Number(requested[0]), Number(requested[requested.length - 1]));
    const found = (receipt.items as unknown[]).find(value => material.id === `report:${reportId}:page:${record(value).page}`);
    item = record(found);
  }
  if (request.report_id !== reportId || request.file_sha256 !== material.sourceHash || request.scope !== 'INDEXED_PAGE_TEXT_ONLY' || request.full_report_read !== false
    || typeof request.complete_requested_text !== 'boolean' || !Array.isArray(request.requested) || !request.requested.length || request.requested.length > 200
    || request.requested.some((page, index, pages) => !Number.isInteger(page) || Number(page) < 1 || Number(page) > 1000000 || (index > 0 && page !== Number(pages[index - 1]) + 1))
    || !Number.isInteger(request.returned_chars) || Number(request.returned_chars) < 0 || Number(request.returned_chars) > 12000) fail('原页请求来源或范围无效');
  const requested = request.requested as unknown[];
  const statuses = ['readable', 'omitted', 'invalid', 'unreadable', 'error'];
  const coverage = record(request.coverage);
  keys(coverage, statuses);
  const covered: number[] = [];
  for (const status of statuses) {
    const pages = coverage[status];
    if (!Array.isArray(pages) || pages.some((page, index) => !requested.includes(page) || (index > 0 && Number(page) <= Number(pages[index - 1])))) fail('原页覆盖无效');
    covered.push(...pages as number[]);
  }
  if (covered.length !== request.requested.length || new Set(covered).size !== covered.length) fail('原页覆盖不完整或重复');
  keys(item, ['page', 'status', 'reason', 'text', 'returned_chars', 'indexed_chars', 'truncated']);
  if (!Number.isInteger(item.page) || !statuses.includes(String(item.status)) || !(coverage[String(item.status)] as unknown[]).includes(item.page)
    || typeof item.reason !== 'string' || !/^[A-Z_]+$/.test(item.reason)
    || (item.text !== undefined && (typeof item.text !== 'string' || item.text.length > 12000))
    || (item.truncated !== undefined && typeof item.truncated !== 'boolean')
    || [item.returned_chars, item.indexed_chars].some(value => value !== undefined && (!Number.isInteger(value) || Number(value) < 0))) fail('原页内容字段无效');
  if (material.title !== `${report.title} · 第 ${item.page} 页`) fail('报告标题与材料不一致');
  const readable = item.status === 'readable', content = readable ? item.text || '' : '';
  if (material.id !== `report:${reportId}:page:${item.page}` || material.content !== content
    || canonicalJson(material.readRange.pages) !== canonicalJson(readable ? [item.page] : [])
    || material.readRange.truncated !== (item.truncated === true) || material.readRange.ocr !== Boolean(request.extraction)
    || material.availability !== (readable && String(content).trim() ? 'partial' : 'unavailable')) fail('原页投影与材料正文或读取状态不一致');
  if (request.complete_requested_text && (covered.length !== (coverage.readable as unknown[]).length || item.truncated === true)) fail('原页完整读取声明不一致');
  if (request.extraction !== undefined && request.extraction !== null) {
    const extraction = record(request.extraction);
    if (!['eng', 'chi_sim+eng'].includes(String(extraction.language))) fail('OCR 页语言无效');
    parseLocalReportOcrReceipt({ schema_version: 'local_ocr_report_receipt.v1', report_id: reportId, file_sha256: material.sourceHash,
      status: 'SEARCHABLE', indexed_at: '2000-01-01T00:00:00Z', extraction }, reportId, material.sourceHash!, String(extraction.language));
  }
}
export function validateResearchMaterial(value: unknown): ResearchMaterial {
  const v = record(value);
  keys(v, ['id', 'version', 'securityCode', 'title', 'content', 'sourceUrl', 'sourceKind', 'sourceHash', 'publishedAt', 'capturedAt', 'readRange', 'availability', 'provenance']);
  const r = record(v.readRange);
  keys(r, ['pages', 'totalPages', 'truncated', 'ocr', 'description']);
  if (!Array.isArray(r.pages)) return fail('原页范围无效');
  const pages = r.pages.map(page => num(page, '原页页码', true));
  if (pages.some(page => page < 1) || new Set(pages).size !== pages.length) fail('原页页码重复或无效');
  const totalPages = r.totalPages === null ? null : num(r.totalPages, '原文总页数', true);
  if (totalPages !== null && (totalPages < 1 || pages.some(page => page > totalPages))) fail('原页超出总页数');
  const sourceUrl = v.sourceUrl === null ? null : str(v.sourceUrl, '原文链接', false, 4096);
  if (sourceUrl && !safeWorkflowUrl(sourceUrl)) fail('原文链接不安全');
  const result: ResearchMaterial = { id: id(v.id), version: id(v.version), securityCode: code(v.securityCode), title: str(v.title, '材料标题', false, 20_000),
    content: str(v.content, '材料正文', true, RESEARCH_ROUND_BUDGET_BYTES), sourceUrl,
    sourceKind: oneOf(v.sourceKind, ['evidence_excerpt', 'report_pages', 'manual', 'legacy']), sourceHash: v.sourceHash === null ? null : str(v.sourceHash, '原件哈希', false, 512),
    publishedAt: v.publishedAt === null ? null : str(v.publishedAt, '披露时间', false, 128), capturedAt: num(v.capturedAt, '材料读取时间'),
    readRange: { pages, totalPages, truncated: bool(r.truncated), ocr: bool(r.ocr), description: str(r.description, '读取范围描述', true) },
    availability: oneOf(v.availability, ['full', 'partial', 'link_only', 'unavailable']) };
  if (['full', 'partial'].includes(result.availability) && !result.content.trim()) fail('可读材料缺少实际正文');
  if (result.sourceKind === 'report_pages' && result.content && pages.length === 0) fail('原页正文缺少页码');
  if (result.availability === 'full' && (result.readRange.truncated || (result.sourceKind === 'report_pages' && (totalPages === null || pages.length !== totalPages)))) fail('读取不完整，不能声称全文已读取');
  if (v.provenance !== undefined) result.provenance = JSON.parse(canonicalJson(record(v.provenance))) as Record<string, JsonValue>;
  validatePageProvenance(result);
  return result;
}
export function validateResearchRound(value: unknown): ResearchRound {
  const v = record(value);
  keys(v, ['id', 'questionId', 'securityCode', 'parentRoundId', 'createdAt', 'materials', 'calculation', 'judgement', 'limitations', 'nextMaterial', 'reviewedMaterialKeys', 'ignoredMaterialKeys', 'coverage']);
  if (!Array.isArray(v.materials)) return fail('研究轮次材料列表无效');
  const securityCode = code(v.securityCode);
  const materials = v.materials.map(validateResearchMaterial);
  const byKey = new Map(materials.map(material => [researchMaterialKey(material), material]));
  if (byKey.size !== materials.length || materials.some(material => material.securityCode !== securityCode)) fail('研究轮次材料重复或跨证券');
  const reviewedMaterialKeys = stringArray(v.reviewedMaterialKeys);
  const ignoredMaterialKeys = stringArray(v.ignoredMaterialKeys);
  if (reviewedMaterialKeys.some(key => !byKey.has(key) || ignoredMaterialKeys.includes(key)) || ignoredMaterialKeys.some(key => !byKey.has(key))) fail('复核或忽略材料不在本轮快照中，或重复处理');
  if (reviewedMaterialKeys.some(key => !['full', 'partial'].includes(byKey.get(key)!.availability))) fail('未取得正文的材料不能标为已读复核');
  let calculation: ResearchCalculation | null = null;
  if (v.calculation !== null) {
    const c = record(v.calculation);
    keys(c, ['kind', 'inputs', 'formula', 'result', 'comparable', 'reason', 'unitConversionConfirmed']);
    if (!Array.isArray(c.inputs) || c.inputs.length > 100) fail('计算输入列表无效');
    const inputs = (c.inputs as unknown[]).map(entry => {
      const i = record(entry);
      keys(i, ['label', 'value', 'unit', 'currency', 'period', 'subject', 'metric', 'basis', 'valueType', 'materialKey', 'page', 'sourceExcerpt', 'confirmed']);
      const input: ResearchCalculationInput = { label: str(i.label, '输入名称', false, 1000), value: str(i.value, '输入数值', false, 100), unit: str(i.unit, '输入单位', true, 100), currency: str(i.currency, '输入币种', true, 100),
        period: str(i.period, '输入期间', true, 256), subject: code(i.subject), metric: str(i.metric, '输入指标', true, 1000), basis: str(i.basis, '输入口径', true, 1000),
        valueType: oneOf(i.valueType, ['forecast', 'actual']), materialKey: str(i.materialKey, '输入材料身份', false, 2048), page: i.page === null ? null : num(i.page, '输入页码', true), sourceExcerpt: str(i.sourceExcerpt, '输入原文', true), confirmed: bool(i.confirmed) };
      const source = byKey.get(input.materialKey);
      if (!/^[+-]?\d{1,24}(?:\.\d{1,12})?$/.test(input.value.trim()) || input.subject !== securityCode || !source || (input.page !== null && !source.readRange.pages.includes(input.page))) fail('计算输入数值、证券或材料页码不匹配');
      if (input.confirmed && (!input.sourceExcerpt.trim() || !source.content.includes(input.sourceExcerpt) || !reviewedMaterialKeys.includes(input.materialKey))) fail('计算确认缺少本轮已读原文支持');
      return input;
    });
    calculation = { kind: oneOf(c.kind, ['interval_contains', 'yoy', 'profit_cashflow']), inputs, formula: str(c.formula, '计算公式', true), result: str(c.result, '计算结果', true), comparable: bool(c.comparable), reason: str(c.reason, '计算限制', true) };
    if (c.unitConversionConfirmed !== undefined) calculation.unitConversionConfirmed = bool(c.unitConversionConfirmed);
    if (calculation.comparable && (calculation.kind !== 'interval_contains' || ![3, 4].includes(inputs.length))) fail('该计算尚不支持可复核比较');
    if (calculation.comparable && inputs.some(input => !input.confirmed || !input.unit || !input.currency || !input.period || !input.metric || !input.basis)) fail('比较口径尚未确认');
  }
  const result: ResearchRound = { id: id(v.id), questionId: id(v.questionId), securityCode, parentRoundId: nullableId(v.parentRoundId), createdAt: num(v.createdAt, '轮次时间'), materials, calculation,
    judgement: str(v.judgement, '本轮判断', true), limitations: str(v.limitations, '限制与反证', true), nextMaterial: str(v.nextMaterial, '下一材料', true), reviewedMaterialKeys, ignoredMaterialKeys, coverage: oneOf(v.coverage, ['partial', 'complete']) };
  if (!result.judgement.trim() && !result.nextMaterial.trim()) fail('请至少保留一句判断或下一问题');
  if (materials.some(material => material.capturedAt > result.createdAt)) fail('材料读取时间晚于保存轮次');
  if (result.coverage === 'complete' && (!materials.length || materials.some(material => material.availability !== 'full' || material.readRange.truncated) || reviewedMaterialKeys.length + ignoredMaterialKeys.length !== materials.length)) fail('部分读取或未处理材料不能标为全范围复核');
  if (utf8Bytes(canonicalJson(result)) > RESEARCH_ROUND_BUDGET_BYTES) throw new ResearchWorkflowError('BUDGET', '单轮研究超过 2 MiB 预算，未截断或删除材料');
  return result;
}
/** All accepted rounds must belong to exactly one complete, linear same-security chain. */
export function validateResearchChains(questions: readonly ResearchQuestion[], rounds: readonly ResearchRound[]): void {
  const qs = new Map(questions.map(question => [question.id, validateResearchQuestion(question)]));
  const rs = new Map(rounds.map(round => [round.id, validateResearchRound(round)]));
  if (qs.size !== questions.length || rs.size !== rounds.length) fail('研究备份有重复身份');
  const versions = new Map<string, string>();
  for (const round of rs.values()) for (const material of round.materials) {
    const key = `${material.securityCode}:${researchMaterialKey(material)}`;
    // Observation receipts can legitimately differ when the same page is read in another
    // requested range. The original content identity must not silently change.
    const frozen = canonicalJson({ content: material.content, sourceHash: material.sourceHash, sourceKind: material.sourceKind, securityCode: material.securityCode });
    if (versions.has(key) && versions.get(key) !== frozen) fail('同一材料版本包含不同正文或读取依据');
    versions.set(key, frozen);
  }
  const visited = new Set<string>();
  for (const question of qs.values()) {
    const processed = new Set<string>();
    let next = question.headRoundId;
    let count = 0;
    let childTime = question.updatedAt;
    while (next !== null) {
      const round = rs.get(next);
      if (!round || visited.has(next) || round.questionId !== question.id || round.securityCode !== question.securityCode || round.createdAt < question.createdAt || round.createdAt > childTime) fail('研究链缺父、成环、跨证券或时间无效');
      visited.add(next);
      count++;
      for (const key of [...round.reviewedMaterialKeys, ...round.ignoredMaterialKeys]) processed.add(key);
      next = round.parentRoundId;
      childTime = round.createdAt;
    }
    if (question.headRoundId === null && question.status !== 'paused') fail('空研究问题只能作为暂停草稿，不能激活跟踪');
    if (question.revision < count || canonicalJson([...processed].sort()) !== canonicalJson([...question.reviewedMaterialKeys].sort())) fail('研究链头、版本或复核基线不匹配');
  }
  if (visited.size !== rs.size) fail('备份含未接入完整研究链的孤立轮次');
}
export function parseLegacyResearchNotes(raw: string | null): LegacyResearchNote[] {
  let parsed: unknown;
  try { parsed = JSON.parse(raw ?? '[]'); } catch { return fail('旧研究记录不是有效 JSON，原始数据未变更'); }
  let items: unknown[];
  if (Array.isArray(parsed)) items = parsed;
  else {
    const p = record(parsed);
    if (!['vibe-notes.backup.v1', 'vibe-notes.backup.v2'].includes(String(p.schema_version)) || !Array.isArray(p.notes)) return fail('不支持的旧记录备份');
    items = p.notes;
  }
  const notes = items.map(entry => {
    const p = record(entry);
    const research = p.research === undefined ? null : record(p.research);
    const securityCode = research?.securityCode === undefined ? null : code(research.securityCode);
    return { id: id(p.id), kind: str(p.kind, '旧记录类型', true), title: str(p.title, '旧记录标题', true), content: str(p.content, '旧记录正文', true, RESEARCH_DEFAULT_BUDGET_BYTES), ts: num(p.ts, '旧记录时间'), securityCode,
      payload: JSON.parse(canonicalJson(p)) as Record<string, JsonValue> };
  });
  if (new Set(notes.map(note => note.id)).size !== notes.length) fail('旧记录有重复身份，未执行部分导入');
  return notes;
}
