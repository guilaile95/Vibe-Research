import { useEffect, useId, useRef, useState } from "react";
import { request } from "@/lib/api";
import { parsePredictionJournal, verifyPredictionWrite, PredictionGeneration, predictionPercent, type PredictionJournalData, type PredictionRecord } from "@/lib/predictionJournal";

const input = "w-full rounded border border-input bg-background p-2 text-sm";
const button = "rounded border border-input px-3 py-2 text-sm disabled:opacity-50";
const labels = { UNRESOLVED: "未决", TRUE: "成立（人工）", FALSE: "不成立（人工）", INDETERMINATE: "无法确定" };
const kindLabel = (kind: string) => kind === "SOURCE_REFERENCE" ? "用户填写的来源引用（未自动核验）" : "用户自报";
const score = (v: number | null) => v === null ? "不可用" : v.toFixed(4);
const draft = () => ({ id: crypto.randomUUID(), question: "", subject: "", probability: "", deadline: "", evidence_context: "", evidence_kind: "USER_ASSERTION", benchmark_probability: "", benchmark_context: "", outcome_not_known: false });

export function PredictionJournal() {
  const id = useId();
  const [data, setData] = useState<PredictionJournalData | null>(null);
  const [form, setForm] = useState(draft);
  const [asOf, setAsOf] = useState("");
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const generation = useRef(new PredictionGeneration());
  const writing = useRef(false);
  useEffect(() => {
    const token = generation.current.next(), controller = new AbortController();
    setData(null); setError("");
    let path = "/prediction-journal";
    if (asOf) path += `?as_of=${encodeURIComponent(new Date(asOf).toISOString())}`;
    request<unknown>(path, "GET", undefined, { signal: controller.signal }).then(raw => {
      if (!generation.current.current(token)) return;
      setData(parsePredictionJournal(raw)); setUncertain(false);
    }).catch(e => { if (generation.current.current(token) && !controller.signal.aborted) setError(e instanceof Error ? e.message : "预测记录读取失败"); });
    return () => { generation.current.next(); controller.abort(); };
  }, [asOf, reload]);
  async function mutate(path: string, body: unknown, created = false) {
    if (writing.current || uncertain || asOf || !data) return;
    writing.current = true; setBusy(true); setError(""); setMessage("");
    const token = generation.current.token();
    try {
      await request<unknown>(path, "POST", body);
      // A mutation receipt alone is insufficient. Re-read authoritative history.
      const raw = await request<unknown>("/prediction-journal");
      const verified = parsePredictionJournal(raw);
      verifyPredictionWrite(verified, created ? (body as { id: string }).id : path.split("/")[2], body as Record<string, unknown>, created);
      if (generation.current.current(token)) {
        setData(verified); setMessage(created ? "原预测已锁定；后续只能追加结果修订" : "人工结果修订已追加，原记录保留");
        if (created) setForm(draft());
      }
    } catch (e) {
      if (generation.current.current(token)) { setUncertain(true); setError(e instanceof Error ? e.message : "写入结果待核对"); }
    } finally { writing.current = false; if (generation.current.current(token)) setBusy(false); }
  }
  const disabled = busy || uncertain || !!asOf || !data;
  return <details className="space-y-3 rounded border border-border p-3" data-testid="prediction-journal"><summary className="cursor-pointer font-medium">手动预测登记与描述性校准复查</summary>
    <p className="text-xs text-muted-foreground">由你事前填写二元问题、概率、截止与判定标准。原预测锁定，结果仅人工追加；不调用模型、不自动推断结果，不更改 Thesis、正式决策或交易。来源引用也只是用户填写，未经自动核验。</p>
    <label className="block text-sm" htmlFor={`${id}-asof`}>历史可见时间（本机时区；留空看当前）<input className={input} id={`${id}-asof`} type="datetime-local" disabled={busy} value={asOf} onChange={e => { generation.current.next(); setData(null); setAsOf(e.target.value); setMessage(""); }} /></label>
    <button className={button} disabled={busy} onClick={() => { generation.current.next(); setData(null); setReload(n => n + 1); }}>重新读取核对</button>
    {asOf && <p className="text-xs">历史视图只含当时已登记且已可用的结果，不可写入。晚到结果不会回填到过去。</p>}
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {uncertain && <p role="status">写入或响应待核对，草稿保留；重新读取前停用提交。新建预测使用固定身份，重试不会覆盖原预测。</p>}
    {!data && !error && <p role="status">正在读取持久化预测记录…</p>}
    {data && <>
      <p className="text-sm">截至 {data.as_of} · 总数 {data.summary.total} · 二元已决 {data.summary.resolved_binary} · 未决 {data.summary.unresolved} · 无法确定 {data.summary.indeterminate}</p>
      <p className="text-sm">Brier（0–1，越低表示此样本平方误差越小）：{score(data.summary.brier)}。没有二元已决样本时不可用。</p>
      <p className="text-xs">事前自报基准匹配样本 {data.summary.benchmark_count} · 基准 Brier {score(data.summary.benchmark_brier)} · 同一子集预测 Brier {score(data.summary.matched_forecast_brier)}。只比较这组匹配样本；基率来源、代表性与独立性未验证。</p>
      <p className="text-xs text-muted-foreground">全部结果均为描述性复查，不证明预测能力、模型质量或已校准。混合问题、选择性结算与相关样本会影响解释。每组少于 {data.summary.display_caution_minimum} 条显示样本提醒，这是产品展示规则，不是统计证明；达到该数量也不构成保证。</p>
      {data.summary.sample_caution && <p className="text-xs">当前样本提醒：二元已决样本少于展示阈值</p>}
      <details><summary>固定概率分箱（0–100%，相同概率不会拆箱）</summary>{data.summary.bins.map(b => <p className="text-xs" key={b.lower}>{predictionPercent(b.lower)} ≤ p {b.upper_inclusive ? "≤" : "<"} {predictionPercent(b.upper)}：n={b.count} · 平均预测 {predictionPercent(b.mean_probability)} · 成立频率 {predictionPercent(b.observed_frequency)}{b.sample_caution ? " · 样本提醒" : ""}</p>)}</details>
    </>}
    <form className="space-y-2" onSubmit={e => { e.preventDefault(); if (!form.outcome_not_known || form.probability === "") return; void mutate("/prediction-journal", { ...form, outcome_not_known: true, probability: Number(form.probability) / 100, deadline: new Date(form.deadline).toISOString(), benchmark_probability: form.benchmark_probability === "" ? null : Number(form.benchmark_probability) / 100, benchmark_context: form.benchmark_probability === "" ? null : form.benchmark_context }, true); }}>
      <fieldset disabled={busy} className="space-y-2"><h3 className="text-sm font-medium">登记新预测（保存后不可编辑）</h3>
      {([["subject", "对象 / Thesis 引用（自报文本）", 160], ["question", "明确的二元问题与判定标准", 500], ["evidence_context", "事前证据背景 / 来源引用", 2000]] as const).map(([key, label, max]) => <label className="block text-sm" htmlFor={`${id}-${key}`} key={key}>{label}<textarea id={`${id}-${key}`} className={input} required maxLength={max} value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} /></label>)}
      <label className="block text-sm">证据类型<select className={input} value={form.evidence_kind} onChange={e => setForm({ ...form, evidence_kind: e.target.value })}><option value="USER_ASSERTION">用户自报</option><option value="SOURCE_REFERENCE">来源引用（未自动核验）</option></select></label>
      <label className="block text-sm">成立概率（%，0–100）<input className={input} type="number" min="0" max="100" step="any" required value={form.probability} onChange={e => setForm({ ...form, probability: e.target.value })} /></label>
      <label className="block text-sm">未来截止时间（本机时区）<input className={input} type="datetime-local" required value={form.deadline} onChange={e => setForm({ ...form, deadline: e.target.value })} /></label>
      <details><summary>可选：事前基率基准</summary><label className="block text-sm">基准概率（%，0–100）<input className={input} type="number" min="0" max="100" step="any" value={form.benchmark_probability} onChange={e => setForm({ ...form, benchmark_probability: e.target.value })} /></label><label className="block text-sm">基率适用人群、时间窗与来源（用户断言）<textarea className={input} maxLength={1000} required={form.benchmark_probability !== ""} value={form.benchmark_context} onChange={e => setForm({ ...form, benchmark_context: e.target.value })} /></label></details>
      <label className="block text-sm"><input type="checkbox" required checked={form.outcome_not_known} onChange={e => setForm({ ...form, outcome_not_known: e.target.checked })} /> 我确认尚不知道结果，且问题能按所写标准判定（用户自报，系统不能验证）</label>
      <button className={button} disabled={disabled}>锁定预测到本地归档</button></fieldset>
    </form>
    {data?.records.slice().reverse().map(record => <ResolutionCard key={record.forecast.id} record={record} disabled={disabled} save={mutate} />)}
  </details>;
}
function ResolutionCard({ record, disabled, save }: { record: PredictionRecord; disabled: boolean; save: (path: string, body: unknown) => Promise<void> }) {
  const [outcome, setOutcome] = useState("INDETERMINATE"), [available, setAvailable] = useState(""), [evidence, setEvidence] = useState(""), [kind, setKind] = useState("USER_ASSERTION"), [reason, setReason] = useState("");
  const f = record.forecast;
  return <article className="space-y-2 rounded border border-border p-3 text-sm"><h3>{f.subject} · {f.question}</h3><p>预测 {predictionPercent(f.probability)} · 锁定 {record.locked_at} · 截止 {f.deadline}</p><p>{kindLabel(f.evidence_kind)}：{f.evidence_context}</p><p>{labels[record.outcome]} · 结果修订 {record.revision}</p>
    {f.benchmark_probability !== null && <p>事前自报基准 {predictionPercent(f.benchmark_probability)}：{f.benchmark_context}</p>}
    <details><summary>追加人工结果 / 修正（不重写原预测）</summary><p className="text-xs">保守规则：截止之后才能结算，证据可用时间也须不早于截止。提前观察请等截止后复核；无法判定选“无法确定”。修订原因与原始历史始终保留。</p>
      <form className="space-y-2" onSubmit={e => { e.preventDefault(); void save(`/prediction-journal/${f.id}/resolutions`, { expected_revision: record.revision, outcome, available_at: new Date(available).toISOString(), evidence, evidence_kind: kind, correction_reason: reason }); }}>
        <fieldset disabled={disabled} className="space-y-2"><label className="block">结果<select className={input} value={outcome} onChange={e => setOutcome(e.target.value)}><option value="INDETERMINATE">无法确定</option><option value="TRUE">成立</option><option value="FALSE">不成立</option></select></label>
        <label className="block">结果证据可用时间（本机时区）<input className={input} type="datetime-local" required value={available} onChange={e => setAvailable(e.target.value)} /></label>
        <label className="block">依据<textarea className={input} required maxLength={2000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label>
        <label className="block">依据类型<select className={input} value={kind} onChange={e => setKind(e.target.value)}><option value="USER_ASSERTION">用户自报</option><option value="SOURCE_REFERENCE">来源引用（未自动核验）</option></select></label>
        <label className="block">首次判定说明 / 修正原因<textarea className={input} required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label>
        <button className={button} disabled={disabled}>追加结果修订</button></fieldset>
      </form>
    </details>
    <details><summary>完整人工结果修订历史（{record.history.length}）</summary>{record.history.map(event => <p className="text-xs" key={event.revision}>v{event.revision} · {labels[event.resolution.outcome]} · 可用 {event.resolution.available_at} · 登记 {event.recorded_at} · {kindLabel(event.resolution.evidence_kind)}：{event.resolution.evidence} · 原因：{event.resolution.correction_reason}</p>)}</details>
  </article>;
}
