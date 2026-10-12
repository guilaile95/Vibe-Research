import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { request } from "@/lib/api";
import {
  boundaryLabels, conditionDraft, directionLabels, formatMetric, percent, resultLabel, verificationDate, ownsVerificationDate,
  type Direction, type Metric, type VerificationCondition, type VerificationView,
} from "@/lib/nextDayVerification";

export function NextDayVerificationCard({ initialDate }: { initialDate?: string | null }) {
  const [day, setDay] = useState(() => verificationDate(initialDate));
  const [view, setView] = useState<VerificationView | null>(null);
  const [draft, setDraft] = useState<VerificationCondition[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const sequence = useRef(0);
  const savingLock = useRef(false);
  const userTouched = useRef(false);

  useEffect(() => {
    if (initialDate && !userTouched.current && !savingLock.current) setDay(verificationDate(initialDate));
  }, [initialDate]);

  useEffect(() => {
    const id = ++sequence.current;
    const controller = new AbortController();
    setView(null); setDraft([]); setMessage("");
    setLoading(true);
    request<VerificationView>(`/next-day-verification/${encodeURIComponent(day)}`, "GET", undefined, { signal: controller.signal })
      .then((data) => { if (id === sequence.current) { setView(data); setDraft(conditionDraft(data)); } })
      .catch((error) => { if (id === sequence.current && !controller.signal.aborted) setMessage(error instanceof Error ? error.message : "读取失败"); })
      .finally(() => { if (id === sequence.current) setLoading(false); });
    return () => { ++sequence.current; controller.abort(); };
  }, [day, reload]);

  const editable = ownsVerificationDate(view, day) && view.state === "OPEN" && !loading && !saving;
  function change(metric: Metric, direction: Direction | "", reason?: string) {
    userTouched.current = true;
    setDraft((items) => {
      const old = items.find((item) => item.metric === metric);
      return [...items.filter((item) => item.metric !== metric), ...(direction ? [{ metric, direction, reason: reason ?? old?.reason ?? "" }] : [])];
    });
  }
  async function save() {
    if (!view || !editable || savingLock.current) return;
    savingLock.current = true; setSaving(true); setMessage("");
    const id = ++sequence.current;
    try {
      const data = await request<VerificationView>(`/next-day-verification/${encodeURIComponent(day)}`, "PUT", { revision: view.revision, items: draft });
      if (id === sequence.current) { setView(data); setDraft(conditionDraft(data)); setMessage("已保存；仅记录研究条件，不产生交易或正式决策"); }
    } catch (error) {
      if (id === sequence.current) setMessage(`${error instanceof Error ? error.message : "保存失败"}。输入已保留；可重新读取确认最新记录`);
    } finally {
      savingLock.current = false;
      if (id === sequence.current) setSaving(false);
    }
  }

  return <GlassCard className="mb-6" data-testid="next-day-verification">
    <h3 className="text-base font-semibold">明日验证 · 事前条件</h3>
    <p className="mt-1 text-xs text-muted-foreground">记录可用；自动核验等待本地合格收盘事实。不会启动数据采集，不构成投资建议</p>
    <div className="my-3 flex flex-wrap items-center gap-3">
      <label className="text-sm">复盘交易日 <input aria-label="验证复盘交易日" type="date" value={day} disabled={saving} onChange={(event) => { userTouched.current = true; setDay(event.target.value); }} className="rounded border border-border bg-background px-2 py-1" /></label>
      <button type="button" disabled={loading || saving} onClick={() => setReload((n) => n + 1)} className="text-sm text-primary disabled:opacity-50">重新读取（放弃未保存输入）</button>
    </div>
    {loading && <p role="status" className="text-sm">正在读取验证记录…</p>}
    {message && <p role="status" className="my-2 text-sm">{message}</p>}
    {ownsVerificationDate(view, day) && <>
      <p className="text-sm font-medium">{boundaryLabels[view.state]}</p>
      <p className="mb-3 text-xs text-muted-foreground">下一交易日：{view.next_trade_date ?? "未知"} · 条件版本：{view.revision}</p>
      <fieldset disabled={!editable} className="space-y-3 disabled:opacity-70">
        <legend className="sr-only">编辑市场条件</legend>
        {view.metrics.map((metric) => {
          const item = draft.find((entry) => entry.metric === metric.key);
          return <div key={metric.key} className="rounded border border-border p-3">
            <label className="flex flex-wrap items-center gap-2 text-sm">{metric.label}
              <select aria-label={`${metric.label}方向`} value={item?.direction ?? ""} onChange={(event) => change(metric.key, event.target.value as Direction | "")} className="rounded border border-border bg-background px-2 py-1">
                <option value="">不设条件</option>{Object.entries(directionLabels).map(([key, text]) => <option value={key} key={key}>{text}</option>)}
              </select>
              <span className="text-xs text-muted-foreground">持平阈值：变化不超过 {metric.key === "failed_board_rate" ? "5 个百分点" : "5 家"}</span>
            </label>
            {item && <input aria-label={`${metric.label}理由`} maxLength={200} value={item.reason} onChange={(event) => change(metric.key, item.direction, event.target.value)} placeholder="事前理由（可选，最多 200 字）" className="mt-2 w-full rounded border border-border bg-background px-2 py-1 text-sm" />}
          </div>;
        })}
        <button type="button" disabled={!editable} onClick={() => void save()} className="rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50">{saving ? "保存中…" : draft.length ? "保存整晚条件" : "保存为空（清除本晚条件）"}</button>
      </fieldset>
      <h4 className="mb-2 mt-4 text-sm font-semibold">已保存条件与对账</h4>
      {!view.items.length && <p className="text-sm text-muted-foreground">此交易日尚无条件；不会自动补写</p>}
      {view.items.map((item) => <div key={item.metric} className="mb-2 rounded bg-muted/25 p-3 text-sm">
        <p>{view.metrics.find((m) => m.key === item.metric)?.label} · 预期{directionLabels[item.direction]} · {resultLabel(item)}</p>
        <p className="mt-1 text-xs text-muted-foreground">事前冻结值 {formatMetric(item.metric, item.prior_value)} → 当前收盘观察 {formatMetric(item.metric, item.current_value)}</p>
        <p className="text-xs text-muted-foreground">历史同方向发生频率 {percent(item.baseline.rate)} · 可比 {item.baseline.samples}/{item.baseline.possible_pairs} 对（至少 12 对才显示频率）</p>
        <p className="break-words text-xs text-muted-foreground">写入时间 {item.written_at}{item.reason ? ` · ${item.reason}` : ""}</p>
      </div>)}
      <p className="mt-3 text-sm">近 60 个交易日条件：已判定 {view.history.summary.decided}/{view.history.summary.total}，成立 {view.history.summary.hit}，待核验 {view.history.summary.unknown}；成立率 {percent(view.history.summary.rate)}，覆盖率 {percent(view.history.summary.coverage)}</p>
      <p className="mt-1 text-xs text-muted-foreground">有基准覆盖 {view.history.summary.baseline_covered} 条；对应历史频率 {percent(view.history.summary.expected_rate)}，同一覆盖子集差额 {percent(view.history.summary.edge)}。不是投资收益或策略胜率</p>
      <ul className="mt-3 space-y-1 text-xs text-muted-foreground">{view.limitations.map((line) => <li key={line}>{line}</li>)}</ul>
    </>}
  </GlassCard>;
}
