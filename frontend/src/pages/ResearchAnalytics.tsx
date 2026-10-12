import { useEffect, useRef, useState } from "react";
import { addNote } from "@/lib/notes";
import { researchAnalyticsNote } from "@/lib/researchAnalyticsNote";
import { request } from "@/lib/api";
import { analyticsModes, formatResearchNumber as fmt, metricNames, percentageMetrics, parseAnalyticsInput, parseAnalyticsReport, parseAnalyticsExample, type AnalyticsMode, type AnalyticsReport } from "@/lib/researchAnalytics";

type Row = Record<string, unknown>;
type Report = AnalyticsReport;

function TableValue({ value, column }: { value: unknown; column: string }) {
  if (value === null || value === undefined) return <span>未定义</span>;
  if (typeof value === "number") return <span className="whitespace-nowrap">{fmt(value, percentageMetrics.has(column) || column === "return_difference_from_base")}</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  if (Array.isArray(value)) return <ul>{value.map((item, index) => <li key={index}><TableValue value={item} column={column} /></li>)}</ul>;
  const fields = value as Record<string, unknown>;
  if ("value" in fields && typeof fields.status === "string") {
    const status = fields.status === "SUPPORTED" ? "已计算" : fields.status === "UNDEFINED" ? "未定义" : fields.status;
    return <div data-testid="research-table-metric"><div className="whitespace-nowrap">{fmt(fields.value, percentageMetrics.has(column))}</div><p className="text-muted-foreground">{status}</p>{typeof fields.reason === "string" && fields.reason && <p className="text-muted-foreground">原因：{fields.reason}</p>}</div>;
  }
  return <dl>{Object.entries(fields).map(([key, item]) => <div key={key}><dt className="text-muted-foreground">{metricNames[key] ?? key}</dt><dd><TableValue value={item} column={key} /></dd></div>)}</dl>;
}

function RecordTable({ title, rows }: { title: string; rows?: Row[] }) {
  if (!rows) return null;
  const keys = Array.from(new Set(rows.flatMap(row => Object.keys(row))));
  return <section className="card-surface min-w-0 p-4"><h3 className="mb-2 font-medium">{title} · {rows.length}</h3>
    {!rows.length ? <p className="text-sm text-muted-foreground">无记录；不等于未定义比率为零</p> : <>
      <p className="mb-2 text-xs text-muted-foreground">可横向滚动查看全部列；完整原始结果保留在下方详情中</p>
      <div role="region" aria-label={`${title}数据表`} tabIndex={0} className="max-h-80 overflow-auto"><table className="w-max min-w-full text-left text-xs"><thead><tr>{keys.map(k => <th className="whitespace-nowrap p-2" key={k}>{metricNames[k] ?? k}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr className="border-t" key={index}>{keys.map(k => <td className="min-w-28 max-w-64 break-words p-2 align-top [overflow-wrap:anywhere]" key={k}><TableValue value={row[k]} column={k} /></td>)}</tr>)}</tbody></table></div></>}
  </section>;
}

function Curve({ rows }: { rows?: Row[] }) {
  if (!rows?.length) return null;
  const values = rows.map(row => row.nav ?? row.nav_index ?? row.twr_index).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (values.length !== rows.length || values.length < 2) return <p className="text-sm">覆盖不完整，未绘制完整组合净值线</p>;
  const low = Math.min(...values), high = Math.max(...values), range = high - low || 1;
  const points = values.map((v, i) => `${10 + i / (values.length - 1) * 580},${140 - (v - low) / range * 120}`).join(" ");
  return <figure className="card-surface p-4"><figcaption className="mb-2 text-sm">研究净值路径 · {String(rows[0].date)} 至 {String(rows[rows.length - 1]?.date)}</figcaption>
    <svg role="img" aria-label="只读研究净值路径" viewBox="0 0 600 160" className="w-full max-h-60"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" /></svg>
    <p className="text-xs text-muted-foreground">区间最低 {fmt(low)} · 最高 {fmt(high)}；仅输入条件下的计算结果</p></figure>;
}

export function ResearchAnalytics() {
  const [mode, setMode] = useState<AnalyticsMode>("simulation");
  const [input, setInput] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [reportBasis, setReportBasis] = useState<{ mode: AnalyticsMode; synthetic: boolean } | null>(null);
  const [noteStatus, setNoteStatus] = useState("");
  const savedReports = useRef(new Set<string>());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [synthetic, setSynthetic] = useState(false);
  const [rdpCodes, setRdpCodes] = useState("");
  const [from, setFrom] = useState("2025-01-02");
  const [to, setTo] = useState("2025-03-01");
  const [adapter, setAdapter] = useState<Row | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  function invalidate() { generation.current++; setReportBasis(null); setNoteStatus(""); setReport(null); setError(""); setBusy(false); }
  async function loadExample() {
    const id = ++generation.current; setBusy(true); setError(""); setReport(null); setReportBasis(null); setNoteStatus("");
    try {
      const response = await request<unknown>(`/research-analytics/example/${mode}`);
      if (generation.current === id) { setInput(JSON.stringify(parseAnalyticsExample(response, mode), null, 2)); setSynthetic(true); }
    } catch { if (generation.current === id) setError("示例读取失败，可重试"); }
    finally { if (generation.current === id) setBusy(false); }
  }
  async function calculate() {
    const id = ++generation.current; setBusy(true); setError(""); setReport(null); setReportBasis(null); setNoteStatus("");
    try {
      const body = parseAnalyticsInput(input);
      const response = await request<unknown>(`/research-analytics/${mode}`, "POST", body);
      if (generation.current === id) { setReport(parseAnalyticsReport(response, mode)); setReportBasis({ mode, synthetic }); }
    } catch { if (generation.current === id) setError("计算未完成：检查输入合同、日期、币种、费用、完整覆盖及有限数值，再重试"); }
    finally { if (generation.current === id) setBusy(false); }
  }
  function saveResearchResult() {
    if (!report || !reportBasis) return;
    const key = `${reportBasis.mode}:${report.input_fingerprint}`;
    if (savedReports.current.has(key)) return;
    savedReports.current.add(key);
    try {
      const note = researchAnalyticsNote(report, reportBasis.mode, reportBasis.synthetic);
      addNote(note.kind, note.title, note.content);
      setNoteStatus("已保存本次结果到当前浏览器研究记录；未发送模型或上传");
    } catch (e) {
      savedReports.current.delete(key);
      setNoteStatus(e instanceof Error ? e.message : "本地记录保存失败，可重试");
    }
  }
  async function readRdp() {
    const id = ++generation.current; setBusy(true); setError("");
    try {
      const response = await request<Row>("/research-analytics/rdp-inputs", "POST", { codes: rdpCodes.split(/[,，\s]+/).filter(Boolean), date_from: from, date_to: to });
      if (generation.current === id) setAdapter(response);
    } catch { if (generation.current === id) setError("本地 RDP 读取未完成，请检查证券代码和日期范围"); }
    finally { if (generation.current === id) setBusy(false); }
  }
  return <div className="mx-auto max-w-6xl space-y-5" data-testid="research-analytics-page">
    <header><h1 className="text-xl font-semibold">研究计算实验室</h1><p className="mt-2 text-sm text-muted-foreground">假设策略、TWR / MWR、相关性与历史情景。所有计算只读，不触发交易、模型调用或数据采集。</p></header>
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">历史可得性及输入真实性 NOT_PROVEN。日历、公司行为、手续费、成交限制须完整声明；缺失不会自动当成零。不同币种分开计算。</div>
    <div role="tablist" aria-label="研究计算类型" className="flex flex-wrap gap-2">{analyticsModes.map(m => <button key={m.id} role="tab" aria-selected={mode === m.id} className="rounded border px-3 py-2 text-sm" onClick={() => { invalidate(); setMode(m.id); setInput(""); setSynthetic(false); setAdapter(null); }}>{m.label}</button>)}</div>
    <section className="card-surface space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-medium">输入与合同</h2><button className="rounded border px-3 py-2 text-sm" disabled={busy} onClick={loadExample}>载入合成示例</button></div>
      <p className="text-sm text-muted-foreground">策略仅支持 BUY_AND_HOLD / SMA_CROSS。前一收盘信号，下一时段开盘成交；限制按声明日历逐日判断。20 只证券、2000 个时段；不支持代码或脚本。</p>
      <p className="text-sm text-muted-foreground">账本投影使用真实账本只读行，须补齐期初收盘数量、原始价格与公司行为并确认历史费用；仅所选股票篮子，不代表整个账户。估值适配器的期初值是市值，不能填历史成本。</p>
      {synthetic && <p className="font-medium text-amber-600" data-testid="synthetic-warning">合成输入 / 编辑后的示例：价格与估值不是市场证据；账本模式仍会读取用户实际交易行，不代表纯合成账户</p>}
      <label className="block text-sm" htmlFor="analytics-input">有界 JSON 输入（不保存）</label>
      <textarea id="analytics-input" className="min-h-64 w-full rounded border bg-transparent p-3 font-mono text-xs" spellCheck={false} value={input} onChange={e => { invalidate(); setInput(e.target.value); }} />
      <div className="flex flex-wrap gap-2"><button className="rounded bg-primary px-4 py-2 text-primary-foreground" disabled={busy || !input.trim()} onClick={calculate}>{busy ? "计算或读取中…" : "只读计算"}</button><button className="rounded border px-3 py-2" onClick={() => { invalidate(); setInput(""); setSynthetic(false); setAdapter(null); }}>清空输入与结果</button></div>
    </section>
    <details className="card-surface p-4"><summary className="cursor-pointer font-medium">从已有本地 RDP 读取价格输入</summary><p className="my-2 text-sm">只读已存数据，不联网采集。观测日期不冒充正式交易日历；费用、限制和公司行为仍须补齐。</p>
      <div className="flex flex-wrap gap-2"><input aria-label="RDP证券代码" className="min-w-0 rounded border bg-transparent p-2" placeholder="六位代码，逗号分隔" value={rdpCodes} onChange={e => { invalidate(); setAdapter(null); setRdpCodes(e.target.value); }} /><input aria-label="RDP开始日期" type="date" value={from} onChange={e => { invalidate(); setAdapter(null); setFrom(e.target.value); }} /><input aria-label="RDP结束日期" type="date" value={to} onChange={e => { invalidate(); setAdapter(null); setTo(e.target.value); }} /><button className="rounded border p-2" disabled={busy || !rdpCodes.trim()} onClick={readRdp}>读取本地价格</button></div>
      {adapter && <textarea aria-label="RDP适配结果" readOnly className="mt-3 h-64 w-full rounded border bg-transparent p-2 font-mono text-xs" value={JSON.stringify(adapter, null, 2)} />}</details>
    {mode === "cost-comparison" && <div className="card-surface space-y-2 p-4 text-sm"><h2 className="font-medium">同一输入比较两种成本法，不改正式成本权威</h2><p>QUALIFIED_RESEARCH 只算显式研究输入；FROZEN_LEDGER 从用户实际账本只读冻结同一序列，禁止提交 trades 字段，仅接受 CNY／Asia/Shanghai A 股资格；多币种使用研究输入。货币未确认、开仓批次或费用不完整、顺序含糊、修正待核对时保持缺口。</p><p>期初须填写真实批次、取得日期与顺序，批次数量须等于声明期初数量；每股成本可为经确认的负成本。分红单列、送转调整份额。不同币种不相加。</p></div>}
    {error && <p role="alert" className="rounded border border-red-500/40 p-3 text-sm">{error}</p>}
    {report && <div className="space-y-4" data-testid="research-analytics-result"><h2 className="font-semibold">结果：{report.status}</h2><button type="button" className="rounded border px-3 py-2 text-sm" disabled={!reportBasis || savedReports.current.has(`${reportBasis.mode}:${report.input_fingerprint}`)} onClick={saveResearchResult}>保存当前结果到本地研究记录</button>{noteStatus && <p role="status" className="text-xs">{noteStatus}</p>}<p className="break-all text-xs text-muted-foreground">范围 {report.scope ?? "待补输入"} · 输入指纹 {report.input_fingerprint}</p>
      {report.missing?.length ? <div role="status" className="rounded border p-3"><h3>缺失合同 / 不完整覆盖</h3><ul className="list-inside list-disc text-sm">{report.missing.map((gap, n) => <li className="break-words" key={n}>{typeof gap === "string" ? gap : JSON.stringify(gap)}</li>)}</ul></div> : null}
      {report.twr !== undefined && <div className="card-surface p-4"><p>TWR {fmt(report.twr, true)}</p><p>MWR 区间 {fmt(report.mwr?.period_return, true)} · 年化 {fmt(report.mwr?.annual_rate, true)}</p><p className="text-xs">{report.mwr?.reason ?? "短于一年不展示年化率；多重根可能性保持未定义"}</p></div>}
      {report.total_return !== undefined && <div className="card-surface p-4"><p>历史情景区间收益 {fmt(report.total_return, true)} · 最大回撤 {fmt(report.max_drawdown?.value, true)}</p><p>历史 VaR 95% {fmt(report.historical_var_95?.value, true)}（统计量，不是最大损失保证）</p><p className="break-words text-xs">原始权重覆盖 {JSON.stringify(report.coverage)}；未覆盖证券未按现金处理</p></div>}
      {report.groups && <section className="space-y-3"><h3 className="font-medium">分币种成本比较 · 正式成本方法未改变</h3><p className="break-words text-xs text-muted-foreground">输入来源 {report.authority ?? "尚未证明输入"}；无跨币种或整个账户合计</p>{report.groups.map((group, n) => <div className="card-surface p-4" key={n}><h4>{String(group.currency)} · {String(group.status)}</h4><div className="mt-3 grid gap-3 sm:grid-cols-2">{["fifo", "moving_average"].map(method => { const values = group[method] as Row; return <div key={method} className="rounded border p-3"><h5 className="mb-2 font-medium">{method === "fifo" ? "FIFO 先进先出" : "研究移动加权平均"}</h5><dl className="text-sm">{Object.entries(values).map(([key, value]) => <div key={key} className="flex justify-between gap-3"><dt className="break-all text-muted-foreground">{key}</dt><dd>{fmt(value)}</dd></div>)}</dl></div>; })}</div></div>)}</section>}
      <RecordTable title="逐证券批次 / 缺口 / 方法差异" rows={report.securities} />
      <Curve rows={report.curve} />
      {report.risk_metrics && <section className="card-surface p-4"><h3 className="mb-3 font-medium">描述性风险分解</h3><dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(report.risk_metrics).map(([key, m]) => <div key={key} className="min-w-0 rounded border p-3"><dt className="break-words text-xs text-muted-foreground">{key}</dt><dd>{fmt(m.value)}</dd>{m.reason && <dd className="break-words text-xs text-muted-foreground">{m.reason}</dd>}</div>)}</dl></section>}

      {report.metrics && <section className="card-surface p-4"><h3 className="mb-3 font-medium">固定上游实际 20 项核心指标</h3><dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(report.metrics).map(([key, m]) => <div key={key} className="rounded border p-3"><dt className="text-xs text-muted-foreground">{metricNames[key] ?? key}</dt><dd>{fmt(m.value, percentageMetrics.has(key))}</dd>{m.reason && <dd className="break-words text-xs text-muted-foreground">{m.reason}</dd>}</div>)}</dl><p className="mt-3 text-xs">已实现不代表每个样本都有定义。无平仓、常数价格和缺基准不会伪填零；年化风险比率采用 252 时段假设。</p></section>}
      {report.realized_pnl !== undefined && <p className="text-sm">已实现 {fmt(report.realized_pnl)} · 未实现 {fmt(report.unrealized_pnl)} · 分红权益 {fmt(report.dividend_entitlements)} · 明确费用 {fmt(report.total_fees)}</p>}
      <RecordTable title="成交" rows={report.fills} /><RecordTable title="未成交及原因" rows={report.rejections} /><RecordTable title="末日未平仓" rows={report.open_positions} />
      <RecordTable title="同样本成本与参数扰动（不是样本外验证）" rows={report.robustness} /><RecordTable title="描述性相关性（不是因果）" rows={report.correlation} /><RecordTable title="事件窗口（重叠样本非独立）" rows={report.event_study} />
      <details className="card-surface p-4"><summary>完整方法、逐日数值与复现结果</summary><textarea aria-label="完整研究结果" readOnly className="mt-3 h-80 w-full bg-transparent font-mono text-xs" value={JSON.stringify(report, null, 2)} /></details>
      <ul className="list-inside list-disc text-xs text-muted-foreground">{report.limitations.map(text => <li key={text}>{text}</li>)}</ul>
    </div>}
  </div>;
}
