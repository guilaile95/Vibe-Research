import { useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import { experimentEndpoint, experimentReason, ExperimentGeneration, type ExperimentRecord, type ExperimentComparison } from "@/lib/experimentLedger";

export function ExperimentLedger({ kind, input }: { kind: string; input: string }) {
  const [records, setRecords] = useState<ExperimentRecord[]>([]);
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [comparison, setComparison] = useState<ExperimentComparison | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const archive = useRef(new ExperimentGeneration());
  const run = useRef(new ExperimentGeneration());
  const compare = useRef(new ExperimentGeneration());
  useEffect(() => { run.current.next(); setMessage(""); setBusy(false); return () => { run.current.next(); }; }, [kind, input]);
  useEffect(() => {
    let alive = true;
    const token = archive.current.next();
    request<{ records: ExperimentRecord[] }>("/research-experiments").then(data => {
      if (alive && archive.current.current(token)) { setRecords(data.records); setError(""); }
    }).catch(() => { if (alive && archive.current.current(token)) { setRecords([]); setComparison(null); compare.current.next(); setError("实验归档读取失败，未显示旧列表"); } });
    return () => { alive = false; };
  }, [revision]);
  useEffect(() => {
    const token = compare.current.next(); setComparison(null);
    if (!left || !right) return;
    request<ExperimentComparison>(`/research-experiments/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`)
      .then(data => { if (compare.current.current(token)) setComparison(data); })
      .catch(() => { if (compare.current.current(token)) setError("比较读取失败，请重新选择记录"); });
    return () => { compare.current.next(); };
  }, [left, right, revision]);
  async function record() {
    const token = run.current.next(); setBusy(true); setMessage("");
    let id = "";
    try {
      const body = JSON.parse(input);
      const created = await request<ExperimentRecord>("/research-experiments", "POST", { kind, input: body });
      id = created.id;
      // The create response is already authoritative for this pending record.
      // Avoid racing a snapshot GET against the execution status writes.
      archive.current.next();
      setRecords(previous => [created, ...previous.filter(item => item.id !== created.id)]);
      await request<unknown>(`${experimentEndpoint(kind)}?record_id=${encodeURIComponent(id)}`, "POST", body, { unwrapData: false });
      if (run.current.current(token)) setMessage(`实验已归档：${id}；状态与指标见下方记录`);
    } catch {
      if (run.current.current(token)) setMessage(id ? `实验未完成：${id}；失败或待运行状态保留在归档，可刷新核对` : "未创建记录：检查输入合同、归档上限与服务状态");
    } finally {
      setRevision(v => v + 1);
      if (run.current.current(token)) setBusy(false);
    }
  }
  async function cancel(id: string) {
    try { await request(`/research-experiments/${encodeURIComponent(id)}/cancel`, "POST"); setRevision(v => v + 1); }
    catch { setError("取消状态未确认，请刷新核对"); }
  }
  return <section className="card-surface space-y-3 p-4" data-testid="experiment-ledger">
    <h2 className="font-medium">实验比较台账</h2>
    <p className="text-xs text-muted-foreground">显式运行并保存紧凑清单到本地服务归档，最多 500 条；原始输入、完整报告不保存。仅描述历史研究结果，不是策略验证、最佳收益排名或正式决策。普通计算不会自动归档。</p>
    <div className="flex gap-2"><button type="button" className="rounded border px-3 py-2" disabled={busy || !input.trim()} onClick={record}>{busy ? "正在运行并记录…" : "运行当前输入并记录实验"}</button><button type="button" className="rounded border px-3 py-2" onClick={() => { setRecords([]); setComparison(null); setRevision(v => v + 1); }}>刷新归档</button></div>
    {message && <p role="status" className="break-all text-sm">{message}</p>}{error && <p role="alert">{error}</p>}
    <p className="text-xs">PENDING / RUNNING 在进程中断后不会推断成功。取消仅停止接收该次结果，不保证中止底层只读计算。缺少回执、状态未完成或口径变化的指标标为不可比。</p>
    <div className="flex flex-wrap gap-3">{[["左侧实验", left, setLeft], ["右侧实验", right, setRight]].map(([label, value, setter]) => <label key={label as string} className="min-w-0 text-sm">{label as string}<select aria-label={label as string} className="block max-w-full rounded border bg-background p-2" value={value as string} onChange={e => (setter as (v: string) => void)(e.target.value)}><option value="">选择已有实验</option>{records.map(item => <option key={item.id} value={item.id}>{item.created_at.slice(0, 19)} · {item.kind} · {item.status} · {item.id.slice(0, 8)}</option>)}</select></label>)}</div>
    {records.filter(item => ["PENDING", "RUNNING"].includes(item.status)).map(item => <div key={item.id} className="break-all text-xs">{item.id} · {item.status} <button type="button" className="underline" onClick={() => cancel(item.id)}>取消接收结果并留档</button></div>)}
    {!records.length && !error && <p className="text-sm">尚无已记录实验；旧页面结果不冒充已有持久化记录</p>}
    {comparison && <div data-testid="experiment-comparison" className="space-y-3">
      <p>同一输入身份：{comparison.same_input ? "是" : "否或缺失"} · 变化：{comparison.changes.join("、") || "无"}</p>
      {!!comparison.reasons.length && <p>不可比原因：{comparison.reasons.map(experimentReason).join("、")}</p>}
      <div className="grid gap-3 md:grid-cols-2">{[comparison.left, comparison.right].map((item, index) => <dl key={index} className="min-w-0 rounded border p-3 text-xs">{Object.entries(item).filter(([key]) => key !== "metrics").map(([key, value]) => <div key={key} className="break-all"><dt className="text-muted-foreground">{key}</dt><dd>{value == null ? "缺失 / 不适用" : typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>)}</div>
      <div className="overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{["指标", "左（单位）", "右（单位）", "可比状态", "右减左"].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>{comparison.metrics.map(metric => <tr key={metric.name}><td>{metric.dimension ? `${metric.dimension.currency} · ${metric.dimension.method} · ${metric.dimension.name}` : metric.name}</td><td>{metric.left ?? "未定义"} ({metric.left_unit})</td><td>{metric.right ?? "未定义"} ({metric.right_unit})</td><td>{metric.status}</td><td>{metric.delta ?? "不计算"}</td></tr>)}</tbody></table></div>
    </div>}
  </section>;
}
