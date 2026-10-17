import { get } from './api.ts';
import { streamNdjson } from './ndjson.ts';
import type { LlmConfig } from './llm.ts';
import { parseResearchBundle, type ResearchBundle, type Subject } from './companyResearch.ts';
export type ComparisonRef = Subject & { bundle_id: string; expected_bundle_sha256: string };
export type ComparisonSource = { evidence_id: string; source: string; status: string; source_as_of: string | null; captured_at: string; payload_sha256: string; units: 'NOT_VERIFIED'; period: 'NOT_VERIFIED'; fixture: boolean };
export type ComparisonOutput = Subject & { summary: string; citations: (Subject & { evidence_id: string })[]; missingness: string[]; caveats: string[] };
export type ComparisonRecord = { schema_version: 'company_comparison.v1'; run_id: string; pair_sha256: string; subjects: ComparisonRef[]; as_of: string; status: 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'; started_at: string; finished_at?: string; model: { provider: string; name: string }; classification: 'NON_AUTHORITATIVE_AI_DRAFT'; numeric_claim_verification: 'NOT_EVALUATED'; comparability: 'NOT_ESTABLISHED'; numeric_ranking: 'NOT_PERFORMED'; evidence: (Subject & { sources: ComparisonSource[] })[]; output: { subjects: ComparisonOutput[] } | null; result_sha256?: string };
const sameRefs = (a: unknown, b: ComparisonRef[]) => Array.isArray(a) && a.length === b.length && a.every((x, i) => keys(x, ["market","symbol","bundle_id","expected_bundle_sha256"]) && same(x, b[i]) && x.bundle_id === b[i].bundle_id && x.expected_bundle_sha256 === b[i].expected_bundle_sha256);
const same = (a: Subject, b: Subject) => a.market === b.market && a.symbol === b.symbol;
const keys = (v: unknown, names: string[]) => !!v && typeof v === 'object' && !Array.isArray(v) && JSON.stringify(Object.keys(v).sort()) === JSON.stringify([...names].sort());
const text = (v: unknown, max = 200): v is string => typeof v === 'string' && !!v.trim() && v.length <= max;
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
const texts = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 30 && v.every(x => text(x, 1000));
export const comparisonSubjectValid = (v: Subject) => !!v && typeof v.symbol === 'string' && ({ A: /^[0-9]{6}$/, HK: /^[0-9]{5}$/, US: /^[A-Z][A-Z0-9.-]{0,14}$/ }[v.market]?.test(v.symbol) ?? false);
export const comparisonDayValid = (v: unknown): v is string => typeof v === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(v) && Number(v.slice(0, 4)) >= 1 && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const timestamp = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v) && comparisonDayValid(v.slice(0, 10)) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const byteLength = (v: unknown) => new TextEncoder().encode(JSON.stringify(v)).byteLength;
const instant = (v: string) => v.slice(0,19) + "." + (v.includes(".") ? v.slice(20,-1) : "").padEnd(6,"0") + "Z";
const proseTexts = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 20 && v.every(x => text(x,500));
export const comparisonRefs = (bundles: ResearchBundle[]): ComparisonRef[] => bundles.map(b => ({ ...b.subject, bundle_id: b.bundle_id, expected_bundle_sha256: b.bundle_sha256 }));
export function parseComparisonRecord(v: ComparisonRecord): ComparisonRecord {
  const fail = () => { throw new Error('对比记录身份、来源或结构无效'); };
  if (!keys(v, ['schema_version','run_id','pair_sha256','subjects','as_of','status','started_at','model','classification','numeric_claim_verification','comparability','numeric_ranking','evidence','output', ...(v?.status !== 'RUNNING' ? ['finished_at'] : []), ...(v?.status === 'COMPLETED' ? ['result_sha256'] : [])]) || byteLength(v) > 80 * 1024 || v.schema_version !== 'company_comparison.v1' || !id(v.run_id) || !hash(v.pair_sha256) || !comparisonDayValid(v.as_of) || !timestamp(v.started_at) || v.as_of > v.started_at.slice(0,10) || !['RUNNING','COMPLETED','FAILED','CANCELLED'].includes(v.status) || (v.status !== 'RUNNING' && (!timestamp(v.finished_at) || instant(v.finished_at) < instant(v.started_at))) || v.classification !== 'NON_AUTHORITATIVE_AI_DRAFT' || v.numeric_claim_verification !== 'NOT_EVALUATED' || v.comparability !== 'NOT_ESTABLISHED' || v.numeric_ranking !== 'NOT_PERFORMED' || !keys(v.model, ['provider','name']) || !text(v.model.provider) || v.model.provider.startsWith('cli-') || !text(v.model.name) || !Array.isArray(v.subjects) || v.subjects.length !== 2 || !Array.isArray(v.evidence) || v.evidence.length !== 2) fail();
  v.subjects.forEach((s, i) => {
    if (!keys(s, ['market','symbol','bundle_id','expected_bundle_sha256']) || !comparisonSubjectValid(s) || !id(s.bundle_id) || !hash(s.expected_bundle_sha256) || (i === 1 && (same(s, v.subjects[0]) || s.bundle_id === v.subjects[0].bundle_id))) fail();
    const ledger = v.evidence[i];
    if (!keys(ledger, ['market','symbol','sources']) || !same(ledger, s) || !Array.isArray(ledger.sources) || ledger.sources.length < 1 || ledger.sources.length > 20 || !ledger.sources.some(r => r.status === 'AVAILABLE')) fail();
    const seen = new Set();
    for (const r of ledger.sources) {
      if (!keys(r, ['evidence_id','source','status','source_as_of','captured_at','payload_sha256','units','period','fixture']) || !text(r.evidence_id, 100) || !/^[a-z][a-z0-9_]*$/.test(r.evidence_id) || seen.has(r.evidence_id) || !text(r.source) || !['AVAILABLE','MISSING','ERROR','UNSUPPORTED'].includes(r.status) || !(r.source_as_of === null || comparisonDayValid(r.source_as_of) || timestamp(r.source_as_of)) || !timestamp(r.captured_at) || !hash(r.payload_sha256) || r.units !== 'NOT_VERIFIED' || r.period !== 'NOT_VERIFIED' || typeof r.fixture !== 'boolean' || (r.fixture && r.source !== 'immutable_public_source_archive')) fail();
      seen.add(r.evidence_id);
    }
  });
  if (v.status !== 'COMPLETED') { if (v.output !== null) fail(); return v; }
  if (!hash(v.result_sha256) || !keys(v.output, ['subjects']) || byteLength(v.output) > 16000 || !Array.isArray(v.output?.subjects) || v.output.subjects.length !== 2) fail();
  v.output!.subjects.forEach((s, i) => {
    if (!keys(s, ['market','symbol','summary','citations','missingness','caveats']) || !same(s, v.subjects[i]) || !text(s.summary, 3500) || !proseTexts(s.missingness) || !proseTexts(s.caveats) || !s.caveats.length || (v.evidence[i].sources.some(r => r.status !== 'AVAILABLE') && !s.missingness.length) || !Array.isArray(s.citations) || s.citations.length > 20) fail();
    const available = new Set(v.evidence[i].sources.filter(r => r.status === 'AVAILABLE').map(r => r.evidence_id));
    const seen = new Set();
    for (const c of s.citations) { if (!keys(c, ['market','symbol','evidence_id']) || !same(c, s) || !available.has(c.evidence_id) || seen.has(c.evidence_id)) fail(); seen.add(c.evidence_id); }
    if (available.size && !s.citations.length) fail();
  });
  return v;
}
export type ComparisonBundleChoice = Subject & { bundle_id: string; bundle_sha256: string; archive_cutoff: string; captured_at: string; available_source_count: number; missing_source_count: number; limitations: string[] };
export async function readComparisonBundles(subject: Subject, asOf: string, signal: AbortSignal): Promise<ComparisonBundleChoice[]> {
  if (!comparisonSubjectValid(subject) || !comparisonDayValid(asOf)) throw new Error('请输入有效股票身份和归档截止日');
  const rows = await get<ComparisonBundleChoice[]>(`/company-comparison/bundles?${new URLSearchParams({ ...subject, as_of: asOf })}`, { signal });
  if (!Array.isArray(rows) || rows.length > 20) throw new Error('归档资料列表无效');
  const seen = new Set();
  for (const b of rows) {
    if (!keys(b, ['market','symbol','bundle_id','bundle_sha256','archive_cutoff','captured_at','available_source_count','missing_source_count','limitations']) || !same(b, subject) || !id(b.bundle_id) || seen.has(b.bundle_id) || !hash(b.bundle_sha256) || b.archive_cutoff !== asOf || !timestamp(b.captured_at) || b.archive_cutoff > b.captured_at.slice(0,10) || !Number.isInteger(b.available_source_count) || b.available_source_count < 0 || !Number.isInteger(b.missing_source_count) || b.missing_source_count < 0 || b.available_source_count + b.missing_source_count < 1 || b.available_source_count + b.missing_source_count > 20 || !texts(b.limitations)) throw new Error('归档资料身份或截止日无效');
    seen.add(b.bundle_id);
  }
  return rows;
}
export async function readComparisonBundle(choice: ComparisonBundleChoice, signal: AbortSignal): Promise<ResearchBundle> {
  const bundle = parseResearchBundle(await get<ResearchBundle>(`/company-research/bundles/${choice.bundle_id}`, { signal }), { market: choice.market, symbol: choice.symbol }, choice.archive_cutoff);
  if (bundle.bundle_id !== choice.bundle_id || bundle.bundle_sha256 !== choice.bundle_sha256 || bundle.archive_cutoff !== choice.archive_cutoff) throw new Error('归档资料版本已变化');
  return bundle;
}
export async function generateComparison(bundles: ResearchBundle[], asOf: string, llm: LlmConfig, signal: AbortSignal): Promise<ComparisonRecord> {
  if (signal.aborted) throw new Error('已取消对比');
  if (bundles.length !== 2 || same(bundles[0].subject, bundles[1].subject) || bundles[0].bundle_id === bundles[1].bundle_id || !comparisonDayValid(asOf)) throw new Error('对比需要两只不同股票及共同截止日');
  bundles.forEach(b => { parseResearchBundle(b, b.subject, asOf); if (b.archive_cutoff !== asOf) throw new Error('资料截止日不一致'); });
  if (llm.provider.startsWith('cli-')) throw new Error('两股对比仅支持 API 模型，订阅运行时暂不支持');
  const subjects = comparisonRefs(bundles); let runId = '', pairHash = ''; let terminal: ComparisonRecord | null = null;
  await streamNdjson('/api/company-comparison/generate', { subjects, as_of: asOf, confirm_model_calls: true, llm }, event => {
    if (signal.aborted) throw new Error('已取消对比');
    if (terminal) throw new Error('对比完成后收到多余事件');
    if (event.type === 'run_started') {
      if (!keys(event, ['type','run_id','pair_sha256','subjects','as_of','max_model_calls']) || runId || !id(event.run_id) || !hash(event.pair_sha256) || event.as_of !== asOf || !sameRefs(event.subjects, subjects) || event.max_model_calls !== 1) throw new Error('对比运行身份不匹配');
      runId = event.run_id; pairHash = event.pair_sha256;
    } else if (event.type === 'done') {
      if (!keys(event, ['type','record'])) throw new Error('对比完成事件无效');
      const record = parseComparisonRecord(event.record as ComparisonRecord);
      if (!runId || record.status !== 'COMPLETED' || record.run_id !== runId || record.pair_sha256 !== pairHash || record.as_of !== asOf || !sameRefs(record.subjects, subjects) || record.model.provider !== (llm.provider || 'api').trim() || record.model.name !== llm.model) throw new Error('对比完成回执不匹配');
      record.evidence.forEach((ledger, i) => {
        const sources = bundles[i].sources;
        if (ledger.sources.length !== sources.length || ledger.sources.some((r, j) => {
          const s = sources[j];
          const payload = s.payload as { block?: { fixture?: boolean } } | null;
          return r.evidence_id !== s.evidence_id || r.source !== s.source || r.status !== s.status || r.source_as_of !== s.source_as_of || r.captured_at !== s.captured_at || r.payload_sha256 !== s.payload_sha256 || r.fixture !== (s.source === 'immutable_public_source_archive' && payload?.block?.fixture === true);
        })) throw new Error('对比来源回执与冻结资料不一致');
      });
      terminal = record;
    } else if (event.type === 'error') throw new Error('对比未完成；没有可用的完整报告，请检查资料后手动重试');
    else throw new Error('未知对比事件');
  }, signal, { strict: true, maxBytes: 256 * 1024 });
  if (signal.aborted) throw new Error('已取消对比');
  if (!terminal) throw new Error('对比响应中断，未收到完整报告');
  return terminal;
}
export async function readComparisonRuns(signal: AbortSignal): Promise<ComparisonRecord[]> {
  const rows = await get<ComparisonRecord[]>('/company-comparison/runs', { signal });
  if (!Array.isArray(rows) || rows.length > 50) throw new Error('对比历史响应无效');
  const records = rows.map(parseComparisonRecord);
  if (new Set(records.map(r => r.run_id)).size !== records.length) throw new Error('对比历史运行身份重复');
  return records;
}

export type ComparisonRunPage = { records: ComparisonRecord[]; next_cursor: string | null };
export async function readComparisonRunPage(first: Subject, second: Subject, asOf: string, signal: AbortSignal, before?: string): Promise<ComparisonRunPage> {
  if (!comparisonSubjectValid(first) || !comparisonSubjectValid(second) || same(first, second) || !comparisonDayValid(asOf) || (before !== undefined && !/^[1-9][0-9]{0,18}$/.test(before))) throw new Error('对比历史查询无效');
  const query = new URLSearchParams({ first_market: first.market, first_symbol: first.symbol, second_market: second.market, second_symbol: second.symbol, as_of: asOf, ...(before ? { before } : {}) });
  const page = await get<ComparisonRunPage>(`/company-comparison/runs?${query}`, { signal });
  if (!keys(page, ['records','next_cursor']) || !Array.isArray(page.records) || page.records.length > 50 || !(page.next_cursor === null || (typeof page.next_cursor === 'string' && /^[1-9][0-9]{0,18}$/.test(page.next_cursor) && (!before || BigInt(page.next_cursor) < BigInt(before))))) throw new Error('对比历史分页响应无效');
  const records = page.records.map(parseComparisonRecord);
  if (new Set(records.map(r => r.run_id)).size !== records.length || records.some(r => r.as_of !== asOf || !same(r.subjects[0], first) || !same(r.subjects[1], second)) || (page.next_cursor !== null && !records.length)) throw new Error('对比历史配对身份无效');
  return { records, next_cursor: page.next_cursor };
}
