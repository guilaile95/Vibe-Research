import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { GlassCard } from "@/components/ui/GlassCard";
import type { DiscoveryResearchOrigin } from "@/lib/discoveryResearchOrigin";
import { api, type EvidenceRecord, type MyReport, type MyReportTextHit } from "@/lib/api";
import { blankOperand, compareForecast, evidenceMaterial, reportIdFromMaterial, reportPageMaterials, safeSourceUrl, type CheckOperand, type ComparisonMode } from "@/lib/researchCheck";
import { RESEARCH_DEFAULT_BUDGET_BYTES, materialKey, type LegacyResearchNote, type ResearchMaterial, type ResearchQuestion, type ResearchQuestionStatus, type ResearchRound } from "@/lib/researchWorkflow";
import type { ResearchSelection } from "@/lib/researchResume";
import { researchWorkflowStore as store } from "@/lib/researchWorkflowStore";

const fieldClass = "mt-1 block w-full rounded border border-border bg-background px-2 py-2 text-sm disabled:opacity-50";
const buttonClass = "rounded border border-primary/40 px-3 py-2 text-xs text-primary disabled:opacity-50";
const statusLabels: Record<ResearchQuestionStatus, string> = { watching: "观察中", resolved: "已解决", paused: "已暂停", archived: "已归档" };
const id = () => crypto.randomUUID();
const failure = (cause: unknown) => cause instanceof Error ? cause.message : "操作未完成，请重试；草稿已保留。";
const date = (value: number) => new Date(value).toLocaleString();
const mergeMaterials = (existing: ResearchMaterial[], additions: ResearchMaterial[]) => [...new Map([...existing, ...additions].map(material => [materialKey(material), material])).values()];

function MaterialCard({ material }: { material: ResearchMaterial }) {
  const reportId = reportIdFromMaterial(material);
  return <article className="min-w-0 rounded border border-border/50 p-3 text-xs" data-testid="check-material-snapshot">
    <p className="break-words font-medium">{material.title}</p>
    <p className="mt-1 text-muted-foreground">{material.sourceKind === "report_pages" ? "指定页正文" : material.sourceKind === "evidence_excerpt" ? "已有证据摘录，非原链接全文" : "用户资料"} · {material.availability === "unavailable" ? "读取受限 / 尚未取得" : material.availability === "link_only" ? "只有链接，未读取" : "局部材料"}{material.readRange.truncated ? " · 正文截断" : ""}{material.readRange.ocr ? " · OCR 未核验" : ""}</p>
    <p className="mt-1 break-all text-muted-foreground">证券：{material.securityCode} · 来源日期：{material.publishedAt || "未知"} · 页码：{material.readRange.pages.join(", ") || "无页码"}</p>
    <div className="mt-2 flex flex-wrap gap-3">
      {reportId && <Link to={`/my-reports?report=${encodeURIComponent(reportId)}`} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">在 MyReports 打开原文件</Link>}
      {safeSourceUrl(material.sourceUrl) && <a href={safeSourceUrl(material.sourceUrl)!} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">打开原始来源链接（新标签）</a>}
    </div>
    <details className="mt-2"><summary className="cursor-pointer">实际保存的原文与读取范围</summary>
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-sans">{material.content || "没有取得正文，不能据此计算或声称读过全文。"}</pre>
      <p className="mt-2 break-all text-muted-foreground">文件 SHA256：{material.sourceHash || "无原文件 hash"} · 快照版本：{material.version}</p>
      <p className="mt-1 break-all text-muted-foreground">{material.readRange.description}</p>
    </details>
  </article>;
}

function OperandFields({ label, value, onChange, materials }: { label: string; value: CheckOperand; onChange: (value: CheckOperand) => void; materials: ResearchMaterial[] }) {
  const update = <K extends keyof CheckOperand>(key: K, next: CheckOperand[K]) => onChange({ ...value, [key]: next, confirmed: key === "confirmed" ? Boolean(next) : false });
  const selects: { key: "metric" | "periodType" | "currency" | "unit" | "basis" | "valueType"; label: string; options: [string, string][] }[] = [
    { key: "metric", label: "指标", options: [["归母净利润", "归母净利润"], ["扣非归母净利润", "扣非归母净利润"]] },
    { key: "periodType", label: "期间类型", options: [["annual", "全年"], ["YTD", "年初至今累计"], ["quarter", "单季度"]] },
    { key: "currency", label: "币种", options: [["CNY", "人民币 CNY（首期仅支持）"]] },
    { key: "unit", label: "原单位", options: [["元", "元"], ["万元", "万元"], ["亿元", "亿元"]] },
    { key: "basis", label: "合并口径", options: [["consolidated", "合并报表"], ["parent", "母公司报表"]] },
    { key: "valueType", label: "数据属性", options: [["forecast", "预测，非实际"], ["actual", "实际业绩"]] },
  ];
  return <fieldset className="min-w-0 space-y-3 rounded border border-border/60 p-3" data-testid={`check-operand-${label === "原预告" ? "forecast" : "comparison"}`}>
    <legend className="px-1 text-sm font-medium">{label} · 手工录入 / 待核</legend>
    <label className="block text-xs">{label}来源<select aria-label={`${label}来源`} value={value.materialKey} onChange={e => update("materialKey", e.target.value)} className={fieldClass}>
      <option value="">选择本轮已取得的原文 / 摘录</option>{materials.filter(m => m.content.trim() && !["link_only", "unavailable"].includes(m.availability)).map(m => <option key={materialKey(m)} value={materialKey(m)}>{m.title}</option>)}
    </select></label>
    <label className="block text-xs">{label}原文引句（逐字保留数值、表头、单位）<textarea aria-label={`${label}原文引句`} value={value.sourceExcerpt} onChange={e => update("sourceExcerpt", e.target.value)} rows={3} className={fieldClass} /></label>
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="block text-xs">{label}证券代码<input aria-label={`${label}证券代码`} value={value.subject} onChange={e => update("subject", e.target.value)} maxLength={6} inputMode="numeric" className={fieldClass} /></label>
      {selects.map(item => <label key={item.key} className="block text-xs">{label}{item.label}<select aria-label={`${label}${item.label}`} value={value[item.key]} onChange={e => update(item.key, e.target.value as never)} className={fieldClass}><option value="">未知 / 待确认</option>{item.options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>)}
      <label className="block text-xs">{label}期间开始<input aria-label={`${label}期间开始`} type="date" value={value.periodStart} onChange={e => update("periodStart", e.target.value)} className={fieldClass} /></label>
      <label className="block text-xs">{label}期间结束<input aria-label={`${label}期间结束`} type="date" value={value.periodEnd} onChange={e => update("periodEnd", e.target.value)} className={fieldClass} /></label>
      <label className="block text-xs">{label}{value.valueType === "actual" ? "实际值" : "端点一"}<input aria-label={`${label}数值一`} inputMode="decimal" value={value.low} onChange={e => update("low", e.target.value)} placeholder="亏损填负号，如 -594.25" className={fieldClass} /></label>
      {value.valueType !== "actual" && <label className="block text-xs">{label}端点二<input aria-label={`${label}数值二`} inputMode="decimal" value={value.high} onChange={e => update("high", e.target.value)} placeholder="如 -891.37；自动按大小排序" className={fieldClass} /></label>}
    </div>
    <label className="flex items-start gap-2 text-xs"><input type="checkbox" aria-label={`${label}已人工核对口径`} checked={value.confirmed} onChange={e => update("confirmed", e.target.checked)} /><span>我已对照实际原文核对主体、期间、指标、币种、单位、预测 / 实际、合并口径及正负号。此确认不等于系统自动核实。</span></label>
  </fieldset>;
}

export function ResearchCheckPanel({ code, records, evidenceStatus, returnTo, originLabel, discoveryOrigin, suggestedQuestion, onDirtyChange, selection, onSelectionChange, onValidatedVisit, onRequestDiscard, navigationPending }: {
  code: string; records: EvidenceRecord[]; evidenceStatus: "loading" | "ready" | "error"; returnTo: string;
  selection: ResearchSelection;
  onSelectionChange: (questionId: string | null, roundId: string | null, replace?: boolean, expectedHref?: string) => void;
  onValidatedVisit: (href: string) => void;
  onRequestDiscard: (action: () => void) => void;
  navigationPending: boolean;
  originLabel?: string; discoveryOrigin?: DiscoveryResearchOrigin | null; suggestedQuestion?: string | null; onDirtyChange?: (dirty: boolean) => void;
}) {
  const defaultWhy = discoveryOrigin
    ? `来自${originLabel || "市场发现"}：${discoveryOrigin.conditionSummary} 原卡片快照已保留，仍需核对。`
    : originLabel ? `来自${originLabel}；原发现卡片快照不可用，不能还原当时入选依据。`
      : `从已知股票 ${code} 开始核对；额外来由未记录。`;
  const [questions, setQuestions] = useState<ResearchQuestion[]>([]);
  const [active, setActive] = useState<ResearchQuestion | null>(null);
  const [rounds, setRounds] = useState<ResearchRound[]>([]);
  const [viewedId, setViewedId] = useState("");
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [title, setTitle] = useState(""), [why, setWhy] = useState(defaultWhy);
  const [materials, setMaterials] = useState<ResearchMaterial[]>([]), [available, setAvailable] = useState<ResearchMaterial[]>([]);
  const [handled, setHandled] = useState<Record<string, "reviewed" | "ignored">>({});
  const [judgement, setJudgement] = useState(""), [limitations, setLimitations] = useState(""), [nextMaterial, setNextMaterial] = useState("");
  const [status, setStatus] = useState<ResearchQuestionStatus>("watching");
  const [forecast, setForecast] = useState(blankOperand), [comparison, setComparison] = useState(blankOperand);
  const [mode, setMode] = useState<ComparisonMode>("actual"), [calculationEnabled, setCalculationEnabled] = useState(false);
  const [allowUnitConversion, setAllowUnitConversion] = useState(false);
  const [reports, setReports] = useState<MyReport[]>([]), [reportError, setReportError] = useState(""), [reportLoading, setReportLoading] = useState(false);
  const [reportId, setReportId] = useState(""), [pageFrom, setPageFrom] = useState("1"), [pageTo, setPageTo] = useState("1");
  const [reportCode, setReportCode] = useState(""), [reportConfirmed, setReportConfirmed] = useState(false);
  const [reading, setReading] = useState(false), [pageNotice, setPageNotice] = useState("");
  const [term, setTerm] = useState("归属于上市公司股东的净利润"), [hits, setHits] = useState<MyReportTextHit[]>([]), [searching, setSearching] = useState(false);
  const [legacyNotes, setLegacyNotes] = useState<LegacyResearchNote[]>([]);
  const [legacyNotice, setLegacyNotice] = useState(""), [legacyPreview, setLegacyPreview] = useState<{ raw: string; count: number } | null>(null);
  const [resumeState, setResumeState] = useState<"loading" | "ready" | "invalid" | "unavailable">("loading");
  const [resumeRetry, setResumeRetry] = useState(0);
  const contextGeneration = useRef(0), listGeneration = useRef(0), reportGeneration = useRef(0), legacyGeneration = useRef(0);
  const activeRef = useRef(active); activeRef.current = active;
  const hrefRef = useRef(returnTo); hrefRef.current = returnTo;
  const requestGeneration = useRef(0), mounted = useRef(true);
  const draftIdentity = JSON.stringify([title, why, materials, handled, judgement, limitations, nextMaterial, status, forecast, comparison, mode, calculationEnabled, allowUnitConversion]);
  const [cleanIdentity, setCleanIdentity] = useState(draftIdentity);
  const dirty = draftIdentity !== cleanIdentity;
  const operation = useRef<{ identity: string; request: Parameters<typeof store.appendRound>[0] | null; create: Parameters<typeof store.createQuestion>[0] | null } | null>(null);
  const chosenReport = reports.find(report => report.id === reportId);
  const calculation = useMemo(() => calculationEnabled ? compareForecast(code, mode, forecast, comparison, materials, allowUnitConversion) : null, [calculationEnabled, code, mode, forecast, comparison, materials, allowUnitConversion]);
  const viewed = rounds.find(round => round.id === viewedId);
  const uncheckedNew = available.filter(material => !active?.reviewedMaterialKeys.includes(materialKey(material))).length;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; requestGeneration.current++; contextGeneration.current++; listGeneration.current++; reportGeneration.current++; legacyGeneration.current++; }; }, []);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  const refreshQuestions = useCallback(async () => {
    const generation = ++listGeneration.current; setLoading(true);
    const current = () => mounted.current && generation === listGeneration.current;
    try { const rows = await store.listQuestions(code); if (current()) setQuestions(rows);
      try {
        const imported = await store.listLegacyNotes();
        const oldSource = await store.checkLegacySource(localStorage.getItem("vr-notes"));
        if (current()) { setLegacyNotes(imported); if (oldSource.changed) setLegacyNotice("旧笔记源已变化。已导入快照仍保留，但没有自动重新导入；可预览后决定是否再复制。"); }
      } catch { if (current()) setLegacyNotice("旧记录状态暂不可检查；未自动迁移或覆盖。研究问题功能不依赖旧记录。"); } }
    catch (cause) { if (current()) setError(failure(cause)); }
    finally { if (current()) setLoading(false); }
  }, [code]);
  useEffect(() => { void refreshQuestions(); }, [refreshQuestions]);
  useEffect(() => {
    let cancelled = false;
    void Promise.all(records.filter(record => record.subject_type === "stock" && record.subject_id === code && !record.deleted).map(record => evidenceMaterial(record, code)))
      .then(rows => { if (!cancelled) setAvailable(rows); }).catch(() => { if (!cancelled) setError("已有摘录快照准备失败；不会把材料当作已读取或推进复核基线。"); });
    return () => { cancelled = true; };
  }, [code, records]);

  function clearDraft(question: ResearchQuestion | null, reference?: ResearchRound) {
    const nextTitle = question?.question || "", nextWhy = question?.origin.label || defaultWhy, nextStatus = question?.status || "watching";
    const nextMaterials = reference?.materials || [];
    setTitle(nextTitle); setWhy(nextWhy); setStatus(nextStatus); setMaterials(nextMaterials); setHandled({}); setJudgement(""); setLimitations(""); setNextMaterial("");
    setForecast(blankOperand()); setComparison(blankOperand()); setCalculationEnabled(false); setMode("actual"); setAllowUnitConversion(false); operation.current = null;
    setCleanIdentity(JSON.stringify([nextTitle, nextWhy, reference ? [] : nextMaterials, {}, "", "", "", nextStatus, blankOperand(), blankOperand(), "actual", false, false]));
  }
  const selectedQuestionId = selection.status === "selected" ? selection.questionId : null;
  const selectedRoundId = selection.status === "selected" ? selection.roundId : null;
  useEffect(() => {
    const generation = ++contextGeneration.current;
    const expectedHref = returnTo;
    const current = () => mounted.current && generation === contextGeneration.current;
    const changingQuestion = (activeRef.current?.id || null) !== selectedQuestionId;
    if (changingQuestion) {
      requestGeneration.current++; reportGeneration.current++; legacyGeneration.current++;
      setReading(false); setSearching(false); setReportLoading(false); setHits([]); setPageNotice(""); setBusy(false);
    }
    setError("");
    if (selection.status === "invalid") { setResumeState("invalid"); setError("问题或轮次定位无效；未打开其他问题，也未创建替代记录。"); return; }
    if (selection.status === "absent") {
      if (activeRef.current) { setActive(null); setRounds([]); setViewedId(""); clearDraft(null); }
      setResumeState("ready"); return;
    }
    setResumeState("loading");
    void store.getQuestionContext(selection.questionId).then(context => {
      if (!current()) return;
      if (!context || context.question.securityCode !== code) {
        setResumeState("invalid"); setError("本浏览器找不到该股票的问题记录，或问题不属于当前股票。未自动创建问题。"); return;
      }
      const { question, rounds: history } = context;
      const roundId = selectedRoundId ?? question.headRoundId;
      if (roundId !== null && !history.some(round => round.id === roundId && round.questionId === question.id && round.securityCode === code)) {
        setResumeState("invalid"); setError("指定轮次不存在或不属于该问题；未改为另一轮。"); return;
      }
      if (question.headRoundId === null && question.status !== "paused") {
        setResumeState("invalid"); setError("问题缺少合法头轮次，未按空问题恢复。"); return;
      }
      // Looking at history must never silently rebase a draft's CAS revision/head.
      if ((activeRef.current?.id || null) !== question.id) { setActive(question); clearDraft(question); }
      setRounds(history); setViewedId(roundId || ""); setResumeState("ready");
      onValidatedVisit(expectedHref);
      if (selectedRoundId === null && roundId !== null) onSelectionChange(question.id, roundId, true, expectedHref);
    }).catch(cause => { if (current()) { setResumeState("unavailable"); setError(`已保存上下文读取失败：${failure(cause)} 未将读取失败视为没有记录。`); } });
    return () => { contextGeneration.current++; };
    // The URL drives only saved selection. Draft edits and unrelated source refreshes cannot restart this read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, selection.status, selectedQuestionId, selectedRoundId, resumeRetry]);
  function chooseQuestion(questionId: string) { onSelectionChange(questionId || null, null); }
  async function loadReports() {
    requestGeneration.current++; const generation = ++reportGeneration.current; const current = () => mounted.current && generation === reportGeneration.current; setReading(false); setSearching(false); setReportLoading(true); setReportError("");
    try { const rows = await api.myReports(); if (current()) setReports(rows); }
    catch { if (current()) setReportError("MyReports 列表读取失败。未取得不代表没有披露，可保留当前草稿并重试。"); }
    finally { if (current()) setReportLoading(false); }
  }
  async function searchPages() {
    if (!chosenReport || !term.trim()) return;
    const expectedReportId = chosenReport.id; const generation = ++requestGeneration.current; setReading(false); setSearching(true); setHits([]); setReportError("");
    try {
      const rows = await api.searchMyReportText(term.trim(), [expectedReportId], 20);
      if (mounted.current && generation === requestGeneration.current) { setHits(rows.filter(hit => hit.report_id === expectedReportId)); setPageNotice(rows.length ? "字面关键词命中只是定位线索；请读指定页保留表头、单位和脚注。" : "未命中字面关键词，不代表公司未披露。可换术语或直接读取页码。"); }
    } catch { if (mounted.current && generation === requestGeneration.current) setReportError("全文关键词检索失败；可直接读取指定页。"); }
    finally { if (mounted.current && generation === requestGeneration.current) setSearching(false); }
  }
  async function readPages() {
    if (!chosenReport) return;
    const start = Number(pageFrom), end = Number(pageTo);
    if (!/^\d+$/.test(pageFrom) || !/^\d+$/.test(pageTo) || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end > 1000000 || end - start >= 200) { setReportError("请输入 1–200 页的连续正整数范围。"); return; }
    if (!/^[a-f0-9]{64}$/.test(chosenReport.file_sha256 || "")) { setReportError("缺少文件版本。请先在 MyReports 建立索引并刷新，不会把链接当作原文。"); return; }
    if (!reportConfirmed || reportCode !== code) { setReportError("请对照原页证券代码确认资料属于当前股票；标题或文件名不足以证明归属。"); return; }
    const report = chosenReport, generation = ++requestGeneration.current; setSearching(false); setReading(true); setReportError(""); setPageNotice("");
    try {
      const response = await api.readReportPages({ report_id: report.id, selected_report_ids: [report.id], expected_file_sha256: report.file_sha256!, page_from: start, page_to: end });
      const snapshots = await reportPageMaterials(report, response, code, start, end);
      if (mounted.current && generation === requestGeneration.current) {
        setMaterials(current => mergeMaterials(current, snapshots));
        setPageNotice(`已保留请求页的读取回执：正文 ${response.coverage.readable.length} 页，省略 ${response.coverage.omitted.length} 页，不可读 / 无效 / 失败 ${response.coverage.unreadable.length + response.coverage.invalid.length + response.coverage.error.length} 页。最多返回 8 页 / 12000 字符；只保存实际返回内容，不代表全文已读。`);
      }
    } catch { if (mounted.current && generation === requestGeneration.current) setReportError("指定页读取或版本校验失败，未加入材料。当前草稿保留；请刷新文件列表并重试。"); }
    finally { if (mounted.current && generation === requestGeneration.current) setReading(false); }
  }
  async function save() {
    if (busy || navigationPending || resumeState !== "ready" || reading || searching) return;
    setError(""); setNotice("");
    if (!title.trim() || (!judgement.trim() && !nextMaterial.trim())) { setError("请写下研究问题，并留下本轮判断或下一项要核对的问题；其余可稍后补充，不必勉强计算。"); return; }
    if (calculationEnabled && !calculation?.comparable) { setError("当前计算被拒绝。补齐口径后再保存计算，或取消计算并把资料不足记入本轮限制。"); return; }
    if (calculation?.comparable && calculation.inputs.some(input => handled[input.materialKey] !== "reviewed")) { setError("计算来源尚未标为本轮已核对。请在每份对应材料下明确选择“已核对这部分实际内容”，不会自动推进基线。"); return; }
    const now = Date.now();
    const questionId = active?.id || id();
    if (!operation.current || operation.current.identity !== draftIdentity) {
      const round: ResearchRound = { id: id(), questionId, securityCode: code, parentRoundId: active?.headRoundId || null, createdAt: now,
        materials, calculation, judgement: judgement.trim(), limitations: limitations.trim() || "未记录 / 待核", nextMaterial: nextMaterial.trim(),
        reviewedMaterialKeys: materials.filter(m => handled[materialKey(m)] === "reviewed").map(materialKey), ignoredMaterialKeys: materials.filter(m => handled[materialKey(m)] === "ignored").map(materialKey), coverage: "partial" };
      operation.current = active ? { identity: draftIdentity, create: null, request: { operationId: id(), questionId, expectedRevision: active.revision, expectedHeadRoundId: active.headRoundId, round, status } }
        : { identity: draftIdentity, request: null, create: { operationId: id(), question: { id: questionId, securityCode: code, question: title.trim(), origin: { kind: originLabel ? "discovery" : "candidate", label: why.trim() || defaultWhy, ...(discoveryOrigin ? { snapshot: discoveryOrigin } : {}), url: returnTo.split("#")[0], capturedAt: now }, createdAt: now, status }, initialRound: round } };
    }
    const pending = operation.current, generation = ++requestGeneration.current, expectedHref = returnTo; setBusy(true);
    try {
      const result = pending.request ? await store.appendRound(pending.request) : null;
      const question = result?.question || await store.createQuestion(pending.create!);
      const committedRound = result?.round || pending.create!.initialRound!;
      if (!mounted.current) return;
      if (generation !== requestGeneration.current || hrefRef.current.split("#")[0] !== expectedHref.split("#")[0]) {
        setQuestions(current => [question, ...current.filter(item => item.id !== question.id)]);
        setNotice("先前提交的研究轮次已保存；当前视图已变化，未覆盖当前草稿。可从问题列表打开已保存记录。");
        // Keep the identical operation receipt available for a retry, rather than creating it again.
        return;
      }
      setActive(question); setQuestions(current => [question, ...current.filter(item => item.id !== question.id)]);
      setRounds(current => [...current.filter(item => item.id !== committedRound.id), committedRound]); setViewedId(committedRound.id);
      clearDraft(question); onSelectionChange(question.id, committedRound.id, true, expectedHref); setNotice("本轮已保存。仅本轮明确核对 / 忽略的材料推进处理基线；未处理资料仍保留。未写入正式证据、投资逻辑或决定。");
    } catch (cause) { if (mounted.current && generation === requestGeneration.current) setError(`${failure(cause)} 本轮草稿未清空，未推进本页显示的复核基线。若为并发冲突，请先查看最新轮次再继续。`); }
    finally { if (mounted.current && generation === requestGeneration.current) setBusy(false); }
  }
  async function reconcile() {
    if (!active || busy || navigationPending || resumeState !== "ready") return;
    const questionId = active.id, generation = ++requestGeneration.current, expectedHref = returnTo;
    setBusy(true); setError("");
    try {
      const context = await store.getQuestionContext(questionId);
      if (!context || context.question.securityCode !== code) throw new Error("问题不再可用。");
      if (mounted.current && generation === requestGeneration.current && hrefRef.current.split("#")[0] === expectedHref.split("#")[0]) {
        setActive(context.question); setRounds(context.rounds); setViewedId(context.question.headRoundId || ""); operation.current = null;
        onSelectionChange(questionId, context.question.headRoundId, false, expectedHref);
        setNotice("已显示最新轮次，当前草稿原样保留。请核对冲突后再保存，届时会追加到最新轮次。");
      }
    } catch (cause) { if (mounted.current && generation === requestGeneration.current) setError(failure(cause)); }
    finally { if (mounted.current && generation === requestGeneration.current) setBusy(false); }
  }
  async function exportBackup() {
    setError("");
    try { const raw = await store.exportBackup(); const url = URL.createObjectURL(new Blob([raw], { type: "application/json" })); const link = document.createElement("a"); link.href = url; link.download = `research-questions-${new Date().toISOString().slice(0, 10)}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    catch (cause) { setError(failure(cause)); }
  }
  async function previewLegacy() {
    const generation = ++legacyGeneration.current;
    try {
      const raw = localStorage.getItem("vr-notes") || "[]", preview = await store.previewLegacy(raw);
      if (mounted.current && generation === legacyGeneration.current) { setLegacyPreview({ raw, count: preview.notes.length }); setLegacyNotice(`找到 ${preview.notes.length} 条旧记录。仅在确认后复制为只读历史资料，不补造当时的原文，也不自动合并为研究轮次。`); }
    } catch (cause) { if (mounted.current && generation === legacyGeneration.current) setLegacyNotice(failure(cause)); }
  }
  async function importBackupFile(file: File) {
    if (busy || navigationPending) return;
    if (file.size > RESEARCH_DEFAULT_BUDGET_BYTES * 4) { setError("备份超过研究库导入预算（64 MiB），未读取。"); return; }
    const generation = ++requestGeneration.current;
    const current = () => mounted.current && generation === requestGeneration.current;
    setBusy(true);
    try {
      const raw = await file.text();
      if (!current()) return;
      const result = await store.importBackup(raw, id());
      if (current()) { setNotice(`已导入 ${result.addedQuestions} 个问题、${result.addedRounds} 轮；当前草稿保留。`); await refreshQuestions(); }
    } catch (cause) { if (current()) setError(failure(cause)); }
    finally { if (current()) setBusy(false); }
  }
  async function confirmLegacyImport() {
    if (!legacyPreview || busy || navigationPending) return;
    const generation = ++legacyGeneration.current;
    const current = () => mounted.current && generation === legacyGeneration.current;
    try {
      const result = await store.importLegacy(legacyPreview.raw, id());
      if (!current()) return;
      setLegacyNotice(`已复制 ${result.added} 条旧记录为只读历史资料；旧笔记未修改，未补造材料或研究轮次。导入源 SHA256：${result.sourceHash}`); setLegacyPreview(null);
      const notes = await store.listLegacyNotes(); if (current()) setLegacyNotes(notes);
    } catch (cause) { if (current()) setLegacyNotice(failure(cause)); }
  }

  return <GlassCard id="candidate-research-check" tabIndex={-1} className="scroll-mt-6 space-y-4" data-testid="research-check-panel">
    <header><h2 className="text-base font-semibold">围绕一个问题核对材料</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">无须 AI 或投资计划。保存来由、实际材料、手工口径计算与不可变核对轮次；新依据出现后仍回到同一问题。仅本浏览器 IndexedDB，不跨设备同步，也不是永久备份。</p></header>
    <div className="flex flex-wrap items-end gap-2"><label className="min-w-0 flex-1 text-xs">这只股票的研究问题<select aria-label="这只股票的研究问题" value={active?.id || ""} disabled={loading || busy} onChange={e => chooseQuestion(e.target.value)} className={fieldClass}><option value="">新建问题</option>{questions.map(question => <option key={question.id} value={question.id}>{question.question} · {statusLabels[question.status]}</option>)}</select></label><button type="button" className={buttonClass} disabled={loading || busy} onClick={() => void refreshQuestions()}>刷新问题列表</button></div>
    {loading && <p role="status" className="text-xs">正在读取本浏览器研究问题…</p>}
    {resumeState === "loading" && <p role="status" className="text-xs">正在恢复已保存的问题与核对轮次…</p>}
    {resumeState === "unavailable" && <button type="button" className={buttonClass} onClick={() => setResumeRetry(value => value + 1)}>重试读取已保存上下文</button>}
    {resumeState === "ready" && active && !active.headRoundId && <p className="text-xs">已暂停的问题尚无已保存核对轮次。</p>}
    {resumeState === "ready" && active && <section className="rounded border border-border/50 p-3 text-xs" data-testid="check-question-context"><p>研究来由：{active.origin.label}</p><p className="mt-1">状态：{statusLabels[active.status]} · 已保存 {rounds.length} 轮 · 基线已处理 {active.reviewedMaterialKeys.length} 份材料</p><p className="mt-1 text-muted-foreground">{active.status === "paused" ? "已暂停常规待办提示；手动打开仍可检查未处理依据。" : active.status === "resolved" ? `已解决，不会自动重开。当前可见摘录中有 ${uncheckedNew} 份未处理依据，是否相关需人工判断。` : `打开 / 刷新时可核对现有摘录中 ${uncheckedNew} 份未处理依据；不代表后台持续在线监控或完整公告覆盖。`}</p><button type="button" className={`${buttonClass} mt-2`} disabled={busy} onClick={() => void reconcile()}>查看最新轮次并保留草稿</button></section>}
    {resumeState === "ready" && rounds.length > 0 && <section className="space-y-3 rounded border border-border/60 p-3" aria-label="研究轮次历史" data-testid="check-round-history">
      <label className="block text-xs">打开原核对轮次<select aria-label="打开原研究轮次" value={viewedId} disabled={busy || navigationPending || resumeState !== "ready"} onChange={e => onSelectionChange(active!.id, e.target.value)} className={fieldClass}>{rounds.map((round, index) => <option value={round.id} key={round.id}>第 {index + 1} 轮 · {date(round.createdAt)}{round.id === active?.headRoundId ? " · 当前头轮" : ""}</option>)}</select></label>
      {viewed && <div className="space-y-2 text-xs" data-testid="check-saved-round"><p className="font-medium">原判断（只读）：{viewed.judgement || "未记录 / 待核"}</p><p>原限制 / 反证：{viewed.limitations || "未记录 / 待核"}</p><p>原下一材料：{viewed.nextMaterial || "未记录；已解决的问题可不填"}</p><p>本轮覆盖：局部材料，不代表全范围复核完成；明确核对 {viewed.reviewedMaterialKeys.length} 份，忽略 {viewed.ignoredMaterialKeys.length} 份。</p>
        {viewed.calculation && <div className="rounded border border-primary/30 p-2"><p>{viewed.calculation.result}</p><p className="mt-1 break-words">{viewed.calculation.formula}</p><p className="mt-1 text-muted-foreground">{viewed.calculation.reason}</p><details className="mt-2"><summary className="cursor-pointer">原计算输入与引句</summary>{viewed.calculation.inputs.map((input, i) => <p key={i} className="mt-2 break-all">{input.label}：{input.value} {input.unit} / {input.currency}；{input.subject} / {input.metric} / {input.period} / {input.basis} / {input.valueType}。第 {input.page ?? "未知"} 页；原文：{input.sourceExcerpt}；材料版本：{input.materialKey}</p>)}</details></div>}
        {viewed.materials.map(material => <MaterialCard key={materialKey(material)} material={material} />)}
        <button type="button" className={buttonClass} disabled={busy || dirty} onClick={() => { clearDraft(active, viewed); setNotice("已复制该历史轮材料供本轮核对；旧轮不改写。保存后追加到当前最新轮，需重新确认本轮处理材料与判断。"); }}>以此轮材料继续核对</button>{dirty && <p className="text-warning">先保存或放弃当前草稿，才能复制历史材料。</p>}
      </div>}
    </section>}
    {(active?.origin.snapshot || (!active && discoveryOrigin)) && (() => {
      const original = active?.origin.snapshot || discoveryOrigin!;
      return <details className="rounded border border-border/50 p-3 text-xs" data-testid="check-discovery-origin"><summary className="cursor-pointer">原发现卡片快照（只读，非已核验事实）</summary>
        <p className="mt-2">{original.securityName} · {original.securityCode} · {original.strategy} · {original.conditionSummary}</p>
        <p className="mt-1">行情归属：{original.asOf || "未知"}；来源抓取：{original.sourceFetchedAt || "未知"}；发现时间：{original.discoveredAt || "未知"}；快照捕获：{date(original.capturedAt)}</p>
        <ul className="mt-2 space-y-1">{original.observations.map((observation, index) => <li key={index} className="break-all">{observation.label}：{observation.rawValue}（原始值） · {observation.code} · {observation.sourceRef}</li>)}</ul>
        <p className="mt-2 break-all">入选理由代码：{original.reasonCodes.join(" · ") || "未提供"}</p><p className="mt-1 break-all">来源名称 / 引用：{original.sourceNames.join(" · ") || "未提供"}</p>
        <ul className="mt-2 space-y-1">{original.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul>
        {original.truncated && <p className="mt-2 text-warning">原卡片内容超出快照上限，已截断；不是完整来源包。</p>}
        <p className="mt-2 text-muted-foreground">这份快照只解释为何进入研究，不是原文材料，不能直接作为计算输入。</p>
      </details>;
    })()}
    <fieldset disabled={busy || loading || navigationPending || resumeState !== "ready"} className="min-w-0 space-y-4">
      <legend className="text-sm font-medium">{active ? "继续同一问题，新增一轮" : "新问题的第一轮"}</legend>
      <label className="block text-xs">研究问题<input aria-label="核对研究问题" value={title} readOnly={Boolean(active)} onChange={e => setTitle(e.target.value)} placeholder="例如：2024 年归母利润预告是否被修订或兑现？" className={fieldClass} /></label>
      {!active && suggestedQuestion && <button type="button" onClick={() => setTitle(suggestedQuestion)} className="text-xs text-primary">采用当前建议问题</button>}
      <label className="block text-xs">为什么开始研究（已带入来源，可选补充）<textarea aria-label="为什么开始研究" value={why} readOnly={Boolean(active)} onChange={e => setWhy(e.target.value)} rows={2} placeholder={defaultWhy} className={fieldClass} /></label>
      <section className="space-y-3 rounded border border-border/60 p-3" aria-label="本轮材料选择">
        <h3 className="text-sm font-medium">1 · 选择实际材料，区分链接和已读内容</h3>
        <p className="text-xs text-muted-foreground">预告核对至少需要原预告；判断兑现还需要同口径实际业绩，修订预告不能代替年报。现金流、经营结构与解释需另外取材，当前计算不覆盖。</p>
        <details><summary className="cursor-pointer text-xs">已有同股证据摘录（{available.length} 条）</summary>
          {evidenceStatus !== "ready" && <p className="mt-2 text-xs text-warning">{evidenceStatus === "loading" ? "摘录仍在读取中。" : "摘录读取失败，不能当成没有资料。"}</p>}
          <div className="mt-2 max-h-72 space-y-2 overflow-y-auto">{available.map(material => <label key={materialKey(material)} className="flex items-start gap-2 text-xs"><input type="checkbox" aria-label={`加入摘录：${material.title}`} checked={materials.some(item => materialKey(item) === materialKey(material))} onChange={e => setMaterials(current => e.target.checked ? mergeMaterials(current, [material]) : current.filter(item => materialKey(item) !== materialKey(material)))} /><span>{material.title}<span className="mt-1 block whitespace-pre-wrap text-muted-foreground">{material.content}</span></span></label>)}</div>
        </details>
        <details><summary className="cursor-pointer text-xs">MyReports 原文件与指定页（不新建文档仓）</summary>
          <p className="mt-2 text-xs text-muted-foreground">先在现有 MyReports 管理原文件。这里只读取已归档文件，不自动下载外部 URL、不建索引、不调用模型。文件标题不证明证券归属。</p>
          <div className="my-2 flex flex-wrap gap-3"><button type="button" className={buttonClass} disabled={reportLoading} onClick={() => void loadReports()}>{reportLoading ? "读取中…" : "读取 / 刷新 MyReports 列表"}</button><Link to="/my-reports" target="_blank" rel="noopener noreferrer" className="self-center text-xs text-primary">在新标签管理原文件</Link></div>
          <label className="block text-xs">本轮原文件<select aria-label="本轮原文件" value={reportId} onChange={e => { requestGeneration.current++; setReportId(e.target.value); setReportConfirmed(false); setReportCode(""); setHits([]); setPageNotice(""); setReading(false); setSearching(false); }} className={fieldClass}><option value="">选择文件，尚未读取正文</option>{reports.map(report => <option value={report.id} key={report.id}>{report.title || report.name} · {report.text_index_status || "索引未知"}</option>)}</select></label>
          {chosenReport && <div className="mt-3 space-y-3 text-xs">
            <p>本地可用原件；正文状态 {chosenReport.text_index_status || "未知"}，共 {chosenReport.page_count ?? "未知"} 页。只有指定页成功返回后才成为本轮实际内容。</p>
            <label className="block">关键词（字面检索，不是语义检索）<input aria-label="原文件检索关键词" value={term} onChange={e => setTerm(e.target.value)} className={fieldClass} /></label>
            <div className="flex flex-wrap gap-2">{["归属于上市公司股东的净利润", "修正", "经营活动产生的现金流量净额"].map(value => <button key={value} type="button" className="text-primary underline" onClick={() => setTerm(value)}>{value}</button>)}<button type="button" className={buttonClass} disabled={searching || reading} onClick={() => void searchPages()}>{searching ? "检索中…" : "在此文件检索关键词"}</button></div>
            {hits.map((hit, index) => <div key={index} className="rounded border border-border/40 p-2"><p>{hit.snippet}</p><button type="button" className="mt-1 text-primary" disabled={!hit.page} onClick={() => { requestGeneration.current++; setReading(false); setSearching(false); setPageFrom(String(Math.max(1, (hit.page || 1) - 1))); setPageTo(String((hit.page || 1) + 1)); }}>读取命中页及相邻页（命中 {hit.page ?? "未知"} 页）</button></div>)}
            <p>先打开原文件核对证券代码；不因标题命中就自动归股。</p><Link target="_blank" rel="noopener noreferrer" to={`/my-reports?report=${encodeURIComponent(chosenReport.id)}`} className="text-primary underline">核对该文件原页</Link>
            <label className="block">原页证券代码<input aria-label="原页证券代码" value={reportCode} maxLength={6} onChange={e => { setReportCode(e.target.value); setReportConfirmed(false); }} className={fieldClass} /></label>
            <label className="flex items-start gap-2"><input aria-label="确认原文件证券归属" type="checkbox" checked={reportConfirmed} onChange={e => setReportConfirmed(e.target.checked)} /><span>我已核对原页证券代码，确认属于当前股票 {code}（人工归属，不是系统验证）。</span></label>
            <div className="flex flex-wrap items-end gap-2"><label>核对起始页<input aria-label="核对起始页" value={pageFrom} onChange={e => { requestGeneration.current++; setReading(false); setSearching(false); setPageFrom(e.target.value); }} inputMode="numeric" className={`${fieldClass} !w-20`} /></label><label>核对结束页<input aria-label="核对结束页" value={pageTo} onChange={e => { requestGeneration.current++; setReading(false); setSearching(false); setPageTo(e.target.value); }} inputMode="numeric" className={`${fieldClass} !w-20`} /></label><button type="button" className={buttonClass} disabled={reading || searching} onClick={() => void readPages()}>{reading ? "读取中…" : "读取指定页并加入本轮"}</button></div>
          </div>}
          {reportError && <p role="alert" className="mt-2 text-xs text-warning">{reportError}</p>}{pageNotice && <p role="status" className="mt-2 text-xs">{pageNotice}</p>}
        </details>
        <p className="text-xs">本轮选择 {materials.length} 份内容 / 读取回执；默认均未处理。只选中或打开不等于完成复核。</p>
        {materials.map(material => <div key={materialKey(material)} className="space-y-2"><MaterialCard material={material} /><div className="flex flex-wrap items-center gap-3 text-xs"><label>本轮处理<select aria-label={`本轮处理：${material.title}`} value={handled[materialKey(material)] || "pending"} onChange={e => setHandled(current => { const next = { ...current }; if (e.target.value === "pending") delete next[materialKey(material)]; else next[materialKey(material)] = e.target.value as "reviewed" | "ignored"; return next; })} className="ml-2 rounded border border-border bg-background p-2"><option value="pending">未处理，继续保留</option><option value="reviewed" disabled={!material.content.trim() || ["link_only", "unavailable"].includes(material.availability)}>已核对这部分实际内容</option><option value="ignored">明确忽略 / 与本问题无关</option></select></label><button type="button" className="text-muted-foreground underline" onClick={() => setMaterials(current => current.filter(item => materialKey(item) !== materialKey(material)))}>移出本轮（不删除原文件）</button></div></div>)}
      </section>
      <section className="space-y-3 rounded border border-border/60 p-3" aria-label="手工口径计算"><h3 className="text-sm font-medium">2 · 一项有限计算：预告区间核对</h3><p className="text-xs text-muted-foreground">手工抄录，不自动提取。每组输入都要独立确认口径。未知或错股 / 错期 / 错指标拒绝计算；元、万元、亿元按精确十进制换算。结果不代表投资结论。</p>
        <label className="flex items-center gap-2 text-xs"><input aria-label="本轮添加区间核对" type="checkbox" checked={calculationEnabled} onChange={e => setCalculationEnabled(e.target.checked)} />本轮添加区间核对（缺实际材料时可以不计算）</label>
        {calculationEnabled && <><label className="block text-xs">核对类型<select aria-label="区间核对类型" value={mode} onChange={e => { setMode(e.target.value as ComparisonMode); setComparison(blankOperand()); setAllowUnitConversion(false); }} className={fieldClass}><option value="actual">原预告 vs 实际业绩：是否落在区间内</option><option value="revision">原预告 vs 修订预告：区间变化，不判断兑现</option></select></label><label className="flex items-start gap-2 text-xs"><input aria-label="允许明确单位换算" type="checkbox" checked={allowUnitConversion} onChange={e => setAllowUnitConversion(e.target.checked)} />我已核对两份原文单位，明确允许元 / 万元 / 亿元换算；未勾选时不同单位拒绝比较。</label><div className="grid gap-3 xl:grid-cols-2"><OperandFields label="原预告" value={forecast} onChange={setForecast} materials={materials} /><OperandFields label={mode === "actual" ? "实际业绩" : "修订预告"} value={comparison} onChange={setComparison} materials={materials} /></div>
          <div role="status" className={`rounded border p-3 text-xs ${calculation?.comparable ? "border-primary/30" : "border-warning/40"}`} data-testid="check-calculation-result"><p className="font-medium">{calculation?.result}</p>{calculation?.formula && <p className="mt-1 break-words">{calculation.formula}</p>}<p className="mt-1">{calculation?.reason}</p></div></>}
      </section>
      <section className="space-y-3"><h3 className="text-sm font-medium">3 · 保存有限判断与下一步</h3><p className="text-xs text-muted-foreground">用户判断与材料原文分别保存；管理层解释不等于因果已证实。只需问题加一句判断或下一项问题即可保存；其余可选，空白限制标为“未记录 / 待核”，不生成“全文核验”标签。</p>
        <label className="block text-xs">本轮能回答什么（用户判断）<textarea aria-label="本轮判断" value={judgement} onChange={e => setJudgement(e.target.value)} rows={3} className={fieldClass} /></label>
        <label className="block text-xs">限制 / 反证 / 尚不能判断<textarea aria-label="本轮限制与反证" value={limitations} onChange={e => setLimitations(e.target.value)} rows={3} className={fieldClass} /></label>
        <label className="block text-xs">下一项需要什么材料<textarea aria-label="下一项材料" value={nextMaterial} onChange={e => setNextMaterial(e.target.value)} rows={2} className={fieldClass} /></label>
        <label className="block text-xs">保存后的问题状态<select aria-label="保存后的问题状态" value={status} onChange={e => setStatus(e.target.value as ResearchQuestionStatus)} className={fieldClass}>{status === "archived" && <option value="archived">已归档（保持原状态）</option>}{(["watching", "resolved", "paused"] as const).map(key => <option key={key} value={key}>{statusLabels[key]}</option>)}</select></label>
        <p className="text-xs text-muted-foreground">观察中：打开 / 刷新时核对；已解决：保留新依据提示但不自动重开；已暂停：不提示常规待办，手动仍能检查。此处不改变任何正式决定。</p>
      </section>
      <div className="flex flex-wrap gap-2"><button type="button" disabled={busy || loading || reading || searching} className={buttonClass} onClick={() => void save()} data-testid="check-save-round">{busy ? "保存 / 读取中…" : active ? "保存新一轮核对" : "保存问题与第一轮核对"}</button><button type="button" className={buttonClass} onClick={() => { if (dirty) onRequestDiscard(() => { requestGeneration.current++; reportGeneration.current++; setReportLoading(false); setBusy(false); setReading(false); setSearching(false); clearDraft(active); }); }} disabled={!dirty}>放弃当前核对草稿</button></div>
    </fieldset>
    {dirty && <p role="status" className="text-xs text-warning">有未保存的核对草稿；失败或并发冲突不会清空草稿。请先保存再离开。</p>}
    {error && <p role="alert" className="whitespace-pre-wrap text-xs text-warning" data-testid="check-error">{error}</p>}{notice && <p role="status" className="text-xs" data-testid="check-notice">{notice}</p>}
    <details className="border-t border-border/50 pt-3 text-xs"><summary className="cursor-pointer">本地备份与旧记录显式导入</summary><p className="mt-2 text-muted-foreground">研究问题使用独立 IndexedDB，不会被旧笔记页面重写；浏览器清理仍可能丢失，请定期备份。导入为完整链校验，不接受断链覆盖。</p><div className="mt-2 flex flex-wrap items-center gap-3"><button type="button" className={buttonClass} onClick={() => void exportBackup()}>导出研究问题备份</button><label className="text-primary">导入研究问题备份<input type="file" accept="application/json,.json" aria-label="导入研究问题备份" className="mt-1 block max-w-full text-xs" disabled={busy} onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void importBackupFile(file); }} /></label><button type="button" className={buttonClass} onClick={() => void previewLegacy()}>预览旧笔记导入</button></div>{legacyNotice && <p className="mt-2">{legacyNotice}</p>}{legacyPreview && <button type="button" className={`${buttonClass} mt-2`} onClick={() => void confirmLegacyImport()}>确认复制 {legacyPreview.count} 条旧记录</button>}{legacyNotes.filter(note => note.securityCode === code || note.securityCode === null).map((note, index) => <details key={`${note.id}-${index}`} className="mt-3 rounded border border-border/50 p-2" data-testid="check-legacy-snapshot"><summary className="cursor-pointer">只读导入快照 #{index + 1} · {note.title} · {date(note.ts)}</summary><p className="mt-2">{note.securityCode ? `原证券归属：${note.securityCode}` : "原记录无证券归属，不自动关联当前股票"}；不补造旧回答的工具正文或来源。</p><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words font-sans">{note.content}</pre><details className="mt-2"><summary className="cursor-pointer">保留的原记录元数据</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(note.payload, null, 2)}</pre></details></details>)}<Link to={`/notes?security_code=${code}`} target="_blank" rel="noopener noreferrer" className="mt-2 block text-primary underline">在新标签查看原旧笔记</Link></details>
  </GlassCard>;
}
