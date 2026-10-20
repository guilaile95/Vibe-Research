import { get, request } from "./api.ts";
import { streamNdjson } from "./ndjson.ts";
import type { LlmConfig } from "./llm.ts";
export const RESEARCH_STAGES = ["profile", "financials", "estimates", "valuation", "risk", "report"] as const;
export const STAGE_LABELS: Record<string, string> = { profile: "公司概况", financials: "财务", estimates: "盈利预期", valuation: "估值", risk: "风险", report: "报告" };
export type Subject = { market: "A" | "HK" | "US"; symbol: string };
export type SourceReceipt = { evidence_id: string; source: string; status: "AVAILABLE" | "MISSING" | "ERROR" | "UNSUPPORTED"; captured_at: string; source_as_of: string | null; payload_sha256: string; stages: string[]; payload: unknown; scope: string };
export type ResearchBundle = { schema_version: string; bundle_id: string; bundle_sha256: string; subject: Subject; captured_at: string; sources: SourceReceipt[]; limitations: string[]; classification: string; archive_cutoff?: string };
export type ResearchStage = { stage: string; summary: string; evidence_ids: string[]; gaps: string[]; output_sha256: string; input_bundle_sha256: string; previous_stage_hashes: string[]; source_gaps: { evidence_id: string; status: string }[]; classification: string; numeric_claim_verification: string };
export type ResearchRecord = { schema_version: string; run_id: string; bundle_id: string; bundle_sha256: string; subject: Subject; status: "COMPLETED" | "FAILED" | "CANCELLED" | "RUNNING"; started_at: string; finished_at?: string; stages: ResearchStage[]; completed_stage_count: number; model: { provider: string; name: string }; result_sha256?: string; classification: string; numeric_claim_verification: string };
const hash = (s: unknown) => typeof s === "string" && /^[a-f0-9]{64}$/.test(s);
const id = (s: unknown) => typeof s === "string" && /^[a-f0-9]{32}$/.test(s);
const texts = (v: unknown, max = 30): v is string[] => Array.isArray(v) && v.length <= max && v.every(x => typeof x === "string" && x.length <= 1000);
const keys = (v: unknown, expected: string[]) => v !== null && typeof v === "object" && !Array.isArray(v) && JSON.stringify(Object.keys(v).sort()) === JSON.stringify([...expected].sort());
const text = (v: unknown, max = 200): v is string => typeof v === "string" && v.length > 0 && v.length <= max;
const timestamp = (v: unknown): v is string => {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v)) return false;
  const d = new Date(v); return Number.isFinite(d.getTime()) && d.getUTCFullYear() >= 1 && d.toISOString().slice(0,19) === v.slice(0,19);
};
const canonicalTimestamp = (v: string) => v.slice(0,19) + "." + (v.includes(".") ? v.slice(20,-1) : "").padEnd(6,"0") + "Z";
const sourceDate = (v: unknown) => timestamp(v) || (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && timestamp(v+"T00:00:00Z"));
const validSubject = (v: Subject) => keys(v,["market","symbol"]) && typeof v.symbol === "string" && ({A:/^[0-9]{6}$/,HK:/^[0-9]{5}$/,US:/^[A-Z][A-Z0-9.-]{0,14}$/}[v.market]?.test(v.symbol) ?? false);
const stageKeys = ["stage","summary","evidence_ids","gaps","output_sha256","input_bundle_sha256","previous_stage_hashes","source_gaps","classification","numeric_claim_verification"];
const sameSubject = (a: Subject, b: Subject) => a?.market === b.market && a?.symbol === b.symbol;
export function parseResearchBundle(v: ResearchBundle, subject: Subject, expectedAsOf?: string): ResearchBundle {
  if (!keys(v,["schema_version","bundle_id","bundle_sha256","subject","captured_at","sources","limitations","classification",...("archive_cutoff" in v ? ["archive_cutoff"] : [])]) || v.classification !== "PUBLIC_ADAPTER_INPUT_UNVERIFIED" || !validSubject(v.subject) || v.schema_version !== "company_research.v1" || !id(v.bundle_id) || !hash(v.bundle_sha256) || !sameSubject(v.subject, subject) || !texts(v.limitations) || !Array.isArray(v.sources) || v.sources.length > 20 || !v.sources.length || !timestamp(v.captured_at)) throw new Error("研究证据回执无效，请重新采集");
  if (v.archive_cutoff !== undefined && (!sourceDate(v.archive_cutoff) || v.archive_cutoff.length !== 10 || v.archive_cutoff > v.captured_at.slice(0,10) || (expectedAsOf !== undefined && v.archive_cutoff !== expectedAsOf))) throw new Error("研究归档截止日回执无效");
  const ids = new Set<string>();
  for (const row of v.sources) {
    if (!keys(row,["evidence_id","source","status","captured_at","source_as_of","payload_sha256","stages","payload","scope",...("error_code" in row ? ["error_code"] : [])]) || !text(row.evidence_id,100) || !/^[a-z][a-z0-9_]*$/.test(row.evidence_id) || ids.has(row.evidence_id) || !hash(row.payload_sha256) || !["AVAILABLE", "MISSING", "ERROR", "UNSUPPORTED"].includes(row.status) || !texts(row.stages, 6) || row.stages.some(s => !RESEARCH_STAGES.includes(s as typeof RESEARCH_STAGES[number])) || !row.stages.length || new Set(row.stages).size !== row.stages.length || !text(row.source) || !text(row.scope) || !timestamp(row.captured_at) || (row.source_as_of !== null && !sourceDate(row.source_as_of)) || ("error_code" in row && (row.status !== "ERROR" || row.error_code !== "SOURCE_UNAVAILABLE_OR_INVALID"))) throw new Error("研究来源身份或状态无效");
    const native = row.payload as { schema_version?: string; adapter?: string; requested_subject?: Subject; identity_basis?: string; payload?: unknown } | null;
    if (native?.schema_version === "company-native-request.v1") {
      if (!keys(native,["schema_version","adapter","requested_subject","identity_basis","payload"]) || !["astock.financials","astock.announcements","astock.lockup_expiry"].includes(row.source) || native.adapter !== row.source || !native.requested_subject || !validSubject(native.requested_subject) || !sameSubject(native.requested_subject,subject) || native.identity_basis !== "ADAPTER_REQUEST_CONTRACT_NOT_PROVIDER_IDENTITY" || native.payload === null || typeof native.payload !== "object") throw new Error("原生资料请求绑定回执无效");
    }
    if (row.source === "immutable_public_source_archive") {
      const receipt = row.payload as { as_of: string; subject: Subject; market: string; symbol: string; source_id: string; schema_version: string; point_in_time_claim: string; provider_fetch_performed: boolean; qualification: string; status: string; capture_time: string | null; source_time: string | null; source_artifact_hash: string | null; reason_codes: string[]; block: { source_id: string; subject: string; requested_as_of: string; captured_at: string; point_in_time_claim: string; status: string; fixture: boolean; rows: unknown[]; evidence: { raw_payload_hash: string } } | null };
      if (!keys(receipt,["schema_version","subject","market","symbol","source_id","status","qualification","as_of","source_time","capture_time","source_artifact_hash","point_in_time_claim","provider_fetch_performed","block","reason_codes"]) || receipt.schema_version !== "company-public-source.v1" || !validSubject(receipt.subject) || !sameSubject(receipt.subject,subject) || receipt.market !== subject.market || receipt.symbol !== subject.symbol || receipt.source_id !== row.evidence_id || receipt.point_in_time_claim !== "NONE" || receipt.provider_fetch_performed !== false || !sourceDate(receipt.as_of) || receipt.as_of.length !== 10 || !v.archive_cutoff || receipt.as_of !== v.archive_cutoff || !texts(receipt.reason_codes) || (receipt.source_time !== null && !timestamp(receipt.source_time)) || (receipt.capture_time !== null && !timestamp(receipt.capture_time)) || (receipt.source_artifact_hash !== null && (typeof receipt.source_artifact_hash !== "string" || !/^sha256:[a-f0-9]{64}$/.test(receipt.source_artifact_hash)))) throw new Error("研究归档截止日或来源身份回执不一致");
      const qualified = receipt.qualification === "QUALIFIED_CURRENT_ARCHIVED_INPUT";
      if (!["QUALIFIED_CURRENT_ARCHIVED_INPUT","MISSING_OR_INVALID_ARCHIVE"].includes(receipt.qualification) || receipt.status !== (qualified ? "partial" : "unavailable") || (row.status === "AVAILABLE") !== qualified) throw new Error("研究归档资格回执不一致");
      const block = receipt.block;
      if (block !== null && (!block || typeof block !== "object" || Array.isArray(block) || typeof block.fixture !== "boolean" || block.source_id !== row.evidence_id || block.subject !== `${subject.market}:${subject.symbol}@${receipt.as_of}` || block.requested_as_of !== receipt.as_of || block.captured_at !== receipt.capture_time || block.point_in_time_claim !== "NONE" || !Array.isArray(block.rows) || block.evidence?.raw_payload_hash !== receipt.source_artifact_hash)) throw new Error("研究归档原始回执无效");
      if (qualified && (!block || !block.rows.length || !["partial","ok"].includes(block.status) || receipt.capture_time === null || receipt.source_artifact_hash === null)) throw new Error("研究归档可用状态不一致");
    }
    ids.add(row.evidence_id);
  }
  return v;
}
export function parseResearchStage(v: ResearchStage, stage: string, bundle: ResearchBundle, previous: ResearchStage[]): ResearchStage {
  const validIds = new Set(bundle.sources.filter(r => r.status === "AVAILABLE" && (stage === "report" || r.stages.includes(stage))).map(r => r.evidence_id));
  if (!keys(v,stageKeys) || v.stage !== stage || typeof v.summary !== "string" || !v.summary.trim() || v.summary.length > 6000 || !texts(v.evidence_ids, 20) || new Set(v.evidence_ids).size !== v.evidence_ids.length || v.evidence_ids.some(x => !validIds.has(x)) || (validIds.size > 0 && !v.evidence_ids.length) || !texts(v.gaps) || (!validIds.size && !v.gaps.length) || !hash(v.output_sha256) || v.input_bundle_sha256 !== bundle.bundle_sha256 || JSON.stringify(v.previous_stage_hashes) !== JSON.stringify(previous.map(p => p.output_sha256)) || v.classification !== "NON_AUTHORITATIVE_AI_DRAFT" || v.numeric_claim_verification !== "NOT_EVALUATED") throw new Error("研究阶段回执无效或引用不匹配");
  const sourceGaps = bundle.sources.filter(r => r.status !== "AVAILABLE" && (stage === "report" || r.stages.includes(stage))).map(r => ({ evidence_id: r.evidence_id, status: r.status }));
  if (JSON.stringify(v.source_gaps) !== JSON.stringify(sourceGaps)) throw new Error("研究来源缺口回执不一致");
  return v;
}
export async function captureCompanyResearch(subject: Subject, signal: AbortSignal, asOf?: string) {
  if (asOf !== undefined && (!/^\d{4}-\d{2}-\d{2}$/.test(asOf) || !sourceDate(asOf) || asOf > new Date().toISOString().slice(0,10))) throw new Error("请选择有效且不晚于今天的归档截止日");
  return parseResearchBundle(await request<ResearchBundle>("/company-research/capture", "POST", { ...subject, confirm_public_fetch: true, ...(asOf ? { as_of: asOf } : {}) }, { signal }), subject, asOf);
}
export async function generateCompanyResearch(bundle: ResearchBundle, llm: LlmConfig, onStage: (stage: string, output?: ResearchStage) => void, signal: AbortSignal): Promise<ResearchRecord> {
  let runId = "", active = "", completed: ResearchStage[] = [], terminal: ResearchRecord | null = null;
  await streamNdjson("/api/company-research/generate", { ...bundle.subject, bundle_id: bundle.bundle_id, expected_bundle_sha256: bundle.bundle_sha256, confirm_model_calls: true, llm }, event => {
    if (terminal) throw new Error("研究结束后收到多余事件");
    if (event.type === "run_started") {
      if (runId || !id(event.run_id) || event.bundle_sha256 !== bundle.bundle_sha256 || !sameSubject(event.subject, bundle.subject) || event.max_model_calls !== 6) throw new Error("研究身份不匹配");
      runId = event.run_id;
    } else if (event.type === "stage_started") {
      if (!runId || event.run_id !== runId || active || event.stage !== RESEARCH_STAGES[completed.length]) throw new Error("研究阶段顺序无效");
      active = event.stage; onStage(active);
    } else if (event.type === "stage_done") {
      if (!active || event.run_id !== runId || event.stage !== active) throw new Error("研究阶段未开始");
      const output = parseResearchStage(event.output, active, bundle, completed);
      completed = [...completed, output]; onStage(active, output); active = "";
    } else if (event.type === "done") {
      const r = parseResearchRecord(event.record as ResearchRecord);
      if (!r || active || completed.length !== 6 || r.schema_version !== "company_research.v1" || r.status !== "COMPLETED" || r.run_id !== runId || r.bundle_id !== bundle.bundle_id || r.bundle_sha256 !== bundle.bundle_sha256 || !sameSubject(r.subject, bundle.subject) || r.completed_stage_count !== 6 || !hash(r.result_sha256) || JSON.stringify(r.stages) !== JSON.stringify(completed)) throw new Error("研究最终回执不完整");
      terminal = r;
    } else if (event.type === "error") throw new Error("研究未完成；仅显示已核对结构的阶段草稿，不能保存完整报告");
    else throw new Error("未知研究事件");
  }, signal, { strict: true, maxBytes: 512 * 1024 });
  if (!terminal) throw new Error("研究响应中断，未收到完整报告");
  return terminal;
}
export function parseResearchRecord(row: ResearchRecord): ResearchRecord {
  const requiredKeys = ["schema_version","run_id","bundle_id","bundle_sha256","subject","status","started_at","model","classification","stages","completed_stage_count","numeric_claim_verification",...(row?.status !== "RUNNING" ? ["finished_at"] : []),...(row?.status === "COMPLETED" ? ["result_sha256"] : [])];
  if (!keys(row,requiredKeys) || row.schema_version !== "company_research.v1" || !id(row.run_id) || !id(row.bundle_id) || !hash(row.bundle_sha256)
    || !validSubject(row.subject)
    || !timestamp(row.started_at) || !keys(row.model,["provider","name"]) || !text(row.model.provider) || !text(row.model.name) || (row.status !== "RUNNING" && (!timestamp(row.finished_at) || canonicalTimestamp(row.finished_at) < canonicalTimestamp(row.started_at))) || (row.status === "RUNNING" && row.completed_stage_count !== 0)
    || row.classification !== "NON_AUTHORITATIVE_AI_DRAFT" || row.numeric_claim_verification !== "NOT_EVALUATED"
    || !Number.isInteger(row.completed_stage_count) || row.completed_stage_count < 0 || row.completed_stage_count > 6
    || !["COMPLETED", "FAILED", "CANCELLED", "RUNNING"].includes(row.status) || !Array.isArray(row.stages)
    || (row.status === "COMPLETED" ? row.stages.length !== 6 || row.completed_stage_count !== 6 || !hash(row.result_sha256) || typeof row.finished_at !== "string" : row.stages.length !== 0)) throw new Error("研究记录损坏或版本不支持");
  row.stages.forEach((stage, i) => {
    if (!keys(stage,stageKeys) || stage.stage !== RESEARCH_STAGES[i] || typeof stage.summary !== "string" || !stage.summary.trim() || stage.summary.length > 6000
      || !texts(stage.evidence_ids, 20) || !texts(stage.gaps) || !hash(stage.output_sha256) || stage.input_bundle_sha256 !== row.bundle_sha256
      || JSON.stringify(stage.previous_stage_hashes) !== JSON.stringify(row.stages.slice(0, i).map(s => s.output_sha256))
      || stage.classification !== "NON_AUTHORITATIVE_AI_DRAFT" || stage.numeric_claim_verification !== "NOT_EVALUATED"
      || !Array.isArray(stage.source_gaps) || stage.source_gaps.length > 20 || stage.source_gaps.some(g => !keys(g,["evidence_id","status"]) || !text(g.evidence_id,100) || !["MISSING", "ERROR", "UNSUPPORTED"].includes(g.status))) throw new Error("研究阶段记录损坏");
  });
  return row;
}
export async function readCompanyResearchRuns(signal?: AbortSignal): Promise<ResearchRecord[]> {
  const rows = await get<ResearchRecord[]>("/company-research/runs", { signal });
  if (!Array.isArray(rows) || rows.length > 50) throw new Error("研究记录响应无效");
  rows.forEach(parseResearchRecord);
  return rows;
}
// Read the immutable bundle referenced by this saved run. Never capture or generate here.
export async function readCompanyResearchEvidence(record: ResearchRecord, signal: AbortSignal): Promise<ResearchBundle> {
  parseResearchRecord(record);
  if (signal.aborted) throw new Error("已取消来源读取");
  const bundle = parseResearchBundle(await get<ResearchBundle>(`/company-research/bundles/${record.bundle_id}`, { signal }), record.subject);
  if (signal.aborted) throw new Error("已取消来源读取");
  if (bundle.bundle_id !== record.bundle_id || bundle.bundle_sha256 !== record.bundle_sha256) throw new Error("冻结资料与研究记录不一致");
  record.stages.forEach((stage, index) => parseResearchStage(stage, RESEARCH_STAGES[index], bundle, record.stages.slice(0, index)));
  return bundle;
}
export function researchNote(record: ResearchRecord): string {
  if (record.status !== "COMPLETED" || record.stages.length !== 6) throw new Error("研究未完成，不能保存完整报告");
  return [`# ${record.subject.market}:${record.subject.symbol} 六阶段公司研究`, `NON_AUTHORITATIVE_AI_DRAFT · 数字与事实未自动核验`, `运行 ${record.run_id} · 来源包 ${record.bundle_id} · SHA256 ${record.bundle_sha256}`, `生成 ${record.finished_at} · ${record.model.provider}/${record.model.name}`, ...record.stages.map(s => `## ${STAGE_LABELS[s.stage]}\n${s.summary}\n引用：${s.evidence_ids.join(", ") || "无可用来源"}\n缺口：${[...s.source_gaps.map(g => `${g.evidence_id}:${g.status}`), ...s.gaps].join("；") || "模型未列出额外缺口，不代表完整"}`)].join("\n\n");
}

export type ResearchHistoryPage = { records: ResearchRecord[]; diagnostics: { run_id: string | null; status: "CORRUPTED_OR_UNSUPPORTED" }[]; unassigned_corrupt_count: number; next_cursor: string | null };
export async function readCompanyResearchPage(subject: Subject, signal: AbortSignal, cursor?: string): Promise<ResearchHistoryPage> {
  const query = new URLSearchParams({ market: subject.market, symbol: subject.symbol, ...(cursor ? { cursor } : {}) });
  const page = await get<ResearchHistoryPage>(`/company-research/history?${query}`, { signal });
  if (!keys(page,["records","diagnostics","unassigned_corrupt_count","next_cursor"]) || !Array.isArray(page.records) || !Array.isArray(page.diagnostics) || page.records.length + page.diagnostics.length > 50 || !Number.isSafeInteger(page.unassigned_corrupt_count) || page.unassigned_corrupt_count < 0 || !(page.next_cursor === null || text(page.next_cursor,400))) throw new Error("研究历史分页回执无效");
  const seen = new Set<string>();
  for (const row of page.records) {
    parseResearchRecord(row);
    if (!sameSubject(row.subject,subject) || seen.has(row.run_id)) throw new Error("研究历史主体或运行身份冲突");
    seen.add(row.run_id);
  }
  for (const row of page.diagnostics) {
    if (!keys(row,["run_id","status"]) || row.status !== "CORRUPTED_OR_UNSUPPORTED" || !(row.run_id === null || id(row.run_id)) || (row.run_id !== null && seen.has(row.run_id))) throw new Error("研究历史诊断回执无效");
    if (row.run_id) seen.add(row.run_id);
  }
  return page;
}
