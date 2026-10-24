import { useEffect, useRef, useState } from "react";
import { loadLlm } from "@/lib/llm";
import { addNote } from "@/lib/notes";
import { captureCompanyResearch, generateCompanyResearch, readCompanyResearchPage, readCompanyResearchEvidence, researchNote, STAGE_LABELS, type ResearchBundle, type ResearchRecord, type ResearchStage, type Subject } from "@/lib/companyResearch";
import { ReverseDcfCard } from "./ReverseDcfCard";
function archiveLabel(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const v = payload as { as_of?: string; capture_time?: string; source_artifact_hash?: string; block?: { fixture?: boolean } };
  return `${v.block?.fixture ? "合成案例（非真实市场验收） · " : ""}截止 ${v.as_of ?? "未知"} · 原始采集 ${v.capture_time ?? "未知"} · 原始哈希 ${v.source_artifact_hash ?? "缺失"} · 财务原始金额缩放未核验，不作跨单位计算`;
}
export function CompanyResearchPanel({ subject }: { subject: Subject }) {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0,10));
  const [bundle, setBundle] = useState<ResearchBundle | null>(null);
  const [record, setRecord] = useState<ResearchRecord | null>(null);
  const [stages, setStages] = useState<ResearchStage[]>([]);
  const [activeStage, setActiveStage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyDiagnosticCount, setHistoryDiagnosticCount] = useState(0);
  const [historyUnassignedCount, setHistoryUnassignedCount] = useState(0);
  const [history, setHistory] = useState<ResearchRecord[]>([]);
  const [evidence, setEvidence] = useState<{ runId: string; context: string; bundle: ResearchBundle } | null>(null);
  const [evidencePending, setEvidencePending] = useState("");
  const [evidenceError, setEvidenceError] = useState("");
  const evidenceOwner = useRef<AbortController | null>(null);
  const context = `${subject.market}:${subject.symbol}|${asOf}`;
  const contextRef = useRef(context); contextRef.current = context;
  const closeEvidence = () => { evidenceOwner.current?.abort(); evidenceOwner.current = null; setEvidence(null); setEvidencePending(""); setEvidenceError(""); };
  const owner = useRef<{ id: number; controller: AbortController } | null>(null);
  const historyOwner = useRef<AbortController | null>(null);
  const generation = useRef(0); const savedRuns = useRef(new Set<string>());
  const stop = () => { generation.current++; owner.current?.controller.abort(); owner.current = null; setBusy(false); setActiveStage(""); };
  useEffect(() => () => { generation.current++; owner.current?.controller.abort(); historyOwner.current?.abort(); evidenceOwner.current?.abort(); }, []);
  useEffect(() => { stop(); historyOwner.current?.abort(); closeEvidence(); setHistory([]); setHistoryCursor(null); setHistoryLoaded(false); setHistoryBusy(false); setHistoryDiagnosticCount(0); setHistoryUnassignedCount(0); setBundle(null); setRecord(null); setStages([]); setError(""); setSaved(false); }, [subject.market, subject.symbol]);
  const capture = async () => {
    if (owner.current) return;
    const id = ++generation.current; const controller = new AbortController(); owner.current = { id, controller };
    closeEvidence();
    setBusy(true); setError(""); setBundle(null); setRecord(null); setStages([]); setSaved(false);
    try { const next = await captureCompanyResearch(subject, controller.signal, asOf); if (generation.current === id && contextRef.current === context) setBundle(next); }
    catch (e) { if (generation.current === id && contextRef.current === context) setError(e instanceof Error ? e.message : "公开资料采集失败"); }
    finally { if (generation.current === id && contextRef.current === context) { owner.current = null; setBusy(false); } }
  };
  const generate = async () => {
    if (!bundle || owner.current) return;
    const llm = loadLlm();
    if (!llm || llm.provider.startsWith("cli-")) { setError("六阶段研究需要现有 API 接入；请在设置中选择 API 模型。订阅页内聊天不提供此工具链。"); return; }
    let destination = "";
    try { const u = new URL(llm.baseURL); if (!["https:", "http:"].includes(u.protocol) || u.username || u.password || u.search || u.hash) throw new Error(); destination = u.origin; }
    catch { setError("模型接收端无效，请检查设置"); return; }
    if (!confirm(`将 ${subject.market}:${subject.symbol} 的已冻结公开资料及逐阶段草稿发送到 ${destination}（${llm.model}）。最多 6 次模型调用，每次最多 2500 输出 token，无自动重试，可能收费。不会读取个人持仓、账户或成交。生成内容及引用未经事实/数值核验。继续？`)) return;
    const id = ++generation.current; const controller = new AbortController(); owner.current = { id, controller };
    setBusy(true); setError(""); setRecord(null); setStages([]); setSaved(false);
    try {
      const final = await generateCompanyResearch(bundle, llm, (stage, output) => {
        if (generation.current !== id || contextRef.current !== context) return;
        setActiveStage(output ? "" : stage); if (output) setStages(previous => [...previous, output]);
      }, controller.signal);
      if (generation.current === id && contextRef.current === context) setRecord(final);
    } catch (e) { if (generation.current === id && contextRef.current === context) setError(e instanceof Error ? e.message : "公司研究未完成"); }
    finally { if (generation.current === id && contextRef.current === context) { owner.current = null; setBusy(false); setActiveStage(""); } }
  };
  const readEvidence = async (row: ResearchRecord) => {
    closeEvidence();
    const controller = new AbortController(); evidenceOwner.current = controller;
    setEvidencePending(row.run_id);
    const active = () => evidenceOwner.current === controller && !controller.signal.aborted && contextRef.current === context;
    try {
      const frozen = await readCompanyResearchEvidence(row, controller.signal);
      if (active()) setEvidence({ runId: row.run_id, context, bundle: frozen });
    } catch { if (active()) setEvidenceError("冻结资料读取失败或与研究记录不一致，请重试。不会重新采集或调用模型。"); }
    finally { if (active()) { evidenceOwner.current = null; setEvidencePending(""); } }
  };
  const readHistory = async (older = false) => {
    closeEvidence(); historyOwner.current?.abort();
    const controller = new AbortController(); historyOwner.current = controller;
    const active = () => historyOwner.current === controller && !controller.signal.aborted && contextRef.current === context;
    setHistoryBusy(true); setError("");
    if (!older) { setHistory([]); setHistoryLoaded(false); setHistoryCursor(null); setHistoryDiagnosticCount(0); setHistoryUnassignedCount(0); }
    try {
      const page = await readCompanyResearchPage(subject, controller.signal, older ? historyCursor ?? undefined : undefined);
      if (active()) {
        setHistory(previous => older ? [...previous, ...page.records.filter(row => !previous.some(old => old.run_id === row.run_id))] : page.records);
        setHistoryDiagnosticCount(previous => (older ? previous : 0) + page.diagnostics.length);
        setHistoryUnassignedCount(page.unassigned_corrupt_count); setHistoryCursor(page.next_cursor); setHistoryLoaded(true);
      }
    } catch (e) { if (active()) setError(e instanceof Error ? e.message : "研究历史读取失败"); }
    finally { if (active()) { historyOwner.current = null; setHistoryBusy(false); } }
  };
  const save = async () => {
    if (!record || savedRuns.current.has(record.run_id)) return;
    const saveGeneration = generation.current;
    const current = () => generation.current === saveGeneration && contextRef.current === context;
    savedRuns.current.add(record.run_id);
    try { await addNote("公司研究", `${subject.market}:${subject.symbol} 六阶段研究`, researchNote(record)); if (current()) setSaved(true); }
    catch (e) { savedRuns.current.delete(record.run_id); if (current()) setError(e instanceof Error ? e.message : "研究记录保存失败"); }
  };
  return <details className="mb-4 rounded-xl border border-border p-4" data-testid="company-research">
    <summary className="cursor-pointer font-semibold">六阶段公司研究 · {subject.market}:{subject.symbol}</summary>
    <p className="my-2 text-xs text-muted-foreground">先显式采集公开资料，再确认模型预算。全部阶段使用同一冻结资料包；资料来自现有数据适配器，不代表已核验的公司事实或完整原始 HTTP 响应。港美盈利预期/风险来源不足会明确列出。无自动交易或正式论点写入。</p>
    <ReverseDcfCard key={`${subject.market}:${subject.symbol}`} subject={subject} />
    <label className="block text-xs">归档截止日（当前存储版本，不代表历史当时已知）<input aria-label="研究归档截止日" type="date" value={asOf} disabled={busy} onChange={e => { closeEvidence(); historyOwner.current?.abort(); setHistory([]); setHistoryCursor(null); setHistoryLoaded(false); setHistoryBusy(false); setHistoryDiagnosticCount(0); setHistoryUnassignedCount(0); setError(""); setAsOf(e.target.value); setBundle(null); setRecord(null); setStages([]); }} className="ml-2 rounded border p-2" /></label>
    <div className="flex flex-wrap gap-3"><button type="button" disabled={busy} onClick={() => void capture()} className="min-h-11 text-primary disabled:opacity-50">采集并冻结公开资料（不调用模型）</button><button type="button" disabled={busy || !bundle} onClick={() => void generate()} className="min-h-11 text-primary disabled:opacity-50">确认预算并开始六阶段研究</button>{busy && <button type="button" onClick={() => { stop(); setError("已取消；未完成文字不能作为完整报告，后端仅保留失败/取消元数据。完成前已付模型费用可能无法撤销。"); }} className="min-h-11">取消研究</button>}</div>
    {error && <p role="alert" className="my-2 text-sm text-destructive">{error}</p>}
    {bundle && <div className="my-2 text-xs"><p>采集于 {bundle.captured_at} · 来源时间与采集时间不同</p><p className="break-all">资料包 {bundle.bundle_id} · SHA256 {bundle.bundle_sha256}</p><ul>{bundle.sources.map(source => <li key={source.evidence_id}>{source.evidence_id} · {source.source} · {source.status} · {source.source === "immutable_public_source_archive" ? "当前归档事后证据，非历史 PIT" : "原生适配器输入"} · 来源时点 {source.source_as_of ?? "未知"} · 采集 {source.captured_at}{source.source === "immutable_public_source_archive" && <p className="break-all text-warning">{archiveLabel(source.payload)}</p>}</li>)}</ul></div>}
    {busy && <p role="status">{activeStage ? `正在生成：${STAGE_LABELS[activeStage]}` : "正在处理…"} · 已完成 {stages.length}/6 阶段</p>}
    {stages.map(stage => <section key={stage.stage} className="my-2 rounded border border-border p-3"><h4 className="font-medium">{STAGE_LABELS[stage.stage]} · AI 草稿</h4><p className="whitespace-pre-wrap text-sm">{stage.summary}</p><p className="text-xs">引用：{stage.evidence_ids.join("、") || "无可用来源"}</p><p className="text-xs text-warning">缺口：{[...stage.source_gaps.map(g => `${g.evidence_id}:${g.status}`), ...stage.gaps].join("；") || "模型未额外列出，不代表没有缺口"}</p></section>)}
    {record && <div><p role="status" className="text-xs">六阶段流程完成，事实与数字仍未核验 · {record.run_id}</p><button type="button" disabled={saved} onClick={save} className="min-h-11 text-primary disabled:opacity-50">{saved ? "已保存到研究记录" : "保存完整草稿到研究记录"}</button></div>}
    <button type="button" disabled={busy || historyBusy} onClick={() => void readHistory()} className="min-h-11 text-primary">读取已有研究记录</button>
    {historyBusy && <p role="status">正在读取研究历史…</p>}
    {historyLoaded && !historyBusy && history.length === 0 && historyDiagnosticCount === 0 && historyUnassignedCount === 0 && <p>该股票暂无研究记录。</p>}
    {historyDiagnosticCount > 0 && <p role="alert">本次已读取页面有 {historyDiagnosticCount} 条记录损坏或版本不支持；原件保留，未修写或重新计算。</p>}
    {historyUnassignedCount > 0 && <p role="alert">另有 {historyUnassignedCount} 条历史记录无法识别所属股票；未将其视作正常报告。</p>}
    {historyCursor && <button type="button" disabled={busy || historyBusy} onClick={() => void readHistory(true)} className="min-h-11 text-primary">读取更早一批研究记录</button>}

    {history.length > 0 && <ul className="text-xs">{history.map(row => <li key={row.run_id}>{row.started_at} · {row.status === "RUNNING" ? "未结束记录（不代表当前仍在运行）" : row.status} · {row.completed_stage_count}/6 · {row.run_id}
      {row.status === "COMPLETED" && <details><summary>查看已保存完整草稿</summary><pre className="whitespace-pre-wrap break-words">{researchNote(row)}</pre></details>}
      <button type="button" disabled={busy} onClick={() => void readEvidence(row)} className="min-h-11 text-primary">查看该记录冻结资料包 · {row.run_id}</button>
      {evidencePending === row.run_id && <p role="status">正在读取已保存冻结资料…</p>}
      {evidence?.context === context && evidence.runId === row.run_id && <aside data-testid="company-research-frozen-evidence" className="rounded border border-border p-2">
        <p>原始冻结证据 · {evidence.bundle.subject.market}:{evidence.bundle.subject.symbol} · 采集 {evidence.bundle.captured_at} · 截止日 {evidence.bundle.archive_cutoff ?? "未记录"}</p>
        <p className="break-all">资料包 {evidence.bundle.bundle_id} · SHA256 {evidence.bundle.bundle_sha256}</p>
        <p>已保存的原生适配器输入，事实与数字未核验；当前归档事后证据不代表历史 PIT。仅查看，不重新采集或调用模型。</p>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(evidence.bundle, null, 2)}</pre>
      </aside>}
    </li>)}</ul>}
    {evidenceError && <p role="alert" className="text-destructive">{evidenceError}</p>}
    {(evidence || evidencePending || evidenceError) && <button type="button" onClick={closeEvidence} className="min-h-11 text-primary">关闭冻结资料</button>}
  </details>;
}
