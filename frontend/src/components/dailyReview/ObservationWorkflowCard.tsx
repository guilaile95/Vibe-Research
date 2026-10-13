import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { request } from "@/lib/api";
import { verificationDate } from "@/lib/nextDayVerification";
import { observationLabels, taskLabels, validObservationView, validObservationTask, type ObservationView } from "@/lib/observationWorkflows";

export function ObservationWorkflowCard({ initialDate, inbox = false }: { initialDate?: string | null; inbox?: boolean }) {
  const [selectedDay, setDay] = useState(() => verificationDate(initialDate));
  const day = inbox ? selectedDay : initialDate && verificationDate(initialDate) === initialDate ? initialDate : "";
  const [demo, setDemo] = useState(false);
  const [view, setView] = useState<ObservationView | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [reload, setReload] = useState(0);
  const sequence = useRef(0);
  const lock = useRef(false);
  useEffect(() => { if (initialDate) { setDay(verificationDate(initialDate)); setDemo(false); } }, [initialDate]);
  useEffect(() => {
    const id = ++sequence.current;
    const abort = new AbortController();
    if (!day) { setView(null); setLoading(false); return () => { ++sequence.current; abort.abort(); }; }
    setView(null); setLoading(true); setError("");
    request<unknown>(`/observation-workflows/${demo ? "preview" : encodeURIComponent(day)}`, "GET", undefined, { signal: abort.signal })
      .then(value => {
        if (sequence.current !== id) return;
        if (!validObservationView(value, demo ? undefined : day) || Boolean(value.synthetic) !== demo) throw new Error("观察资料日期或身份校验失败");
        setView(value); setUncertain(false);
      }).catch(e => { if (sequence.current === id && !abort.signal.aborted) setError(e instanceof Error ? e.message : "读取失败"); })
      .finally(() => { if (sequence.current === id) setLoading(false); });
    return () => { ++sequence.current; abort.abort(); };
  }, [day, demo, reload]);
  async function action(kind: string, operation: string) {
    if (lock.current || demo || uncertain || !view || view.trade_date !== day || loading) return;
    lock.current = true; setBusy(true); setError("");
    const id = sequence.current;
    try {
      const result = await request<unknown>(`/observation-workflows/${encodeURIComponent(day)}/tasks/${encodeURIComponent(kind)}/${operation}`, "POST", {});
      if (sequence.current !== id) return;
      if (!validObservationTask(result, day, kind)) {
        setUncertain(true); throw new Error("任务返回未通过校验，执行结果尚未确认；请重新读取后再操作");
      }
      setReload(n => n + 1);
    } catch (e) { if (sequence.current === id) setError(e instanceof Error ? e.message : "任务失败"); }
    finally { lock.current = false; setBusy(false); }
  }
  return <GlassCard className="mb-6" data-testid="observation-workflows">
    <h3 className="font-semibold">{inbox ? "内部提醒与有限任务" : "盘中观察 · 竞价与六时点"}</h3>
    <p className="mt-1 text-xs text-muted-foreground">真实采集、定时调度及外部通知均未启用。重新读取只看本地；手动任务不请求行情或模型</p>
    <div className="my-3 flex flex-wrap gap-3 text-sm">
      <label>观察交易日 <input aria-label="观察交易日" type="date" value={day} disabled={busy || !inbox} onChange={e => { setDay(e.target.value); setDemo(false); }} className="rounded border bg-background p-1" /></label>
      <button disabled={busy || loading} onClick={() => setReload(n => n + 1)}>重新读取</button>
      <button disabled={busy || !day} onClick={() => setDemo(x => !x)}>{demo ? "返回真实归档" : "查看离线合成演示"}</button>
    </div>
    {!day && <p role="status" className="text-sm">等待复盘交易日；不会回退到今日取数</p>}
    {loading && <p role="status">正在读取观察资料…</p>}
    {error && <p role="alert" className="text-sm">{error}</p>}
    {view && (demo ? view.synthetic === true : view.trade_date === day) && <>
      {demo && <p className="my-3 rounded border border-warning p-2 text-sm" role="status">{view.fixture_label} · 示例日期 {view.trade_date}</p>}
      {!inbox && <>
        <p className="text-xs text-muted-foreground">时点均为上海时间；09:25 使用开盘价，其余使用最新价；供应商时间与服务端观察时间分开展示</p>
        <div className="my-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {view.slots.map(slot => <section key={slot.slot} className="min-w-0 rounded border border-border p-3" data-testid={`observation-slot-${slot.slot}`}>
            <h4 className="text-sm font-medium">{slot.slot} · {observationLabels[slot.state] ?? slot.state}</h4>
            <p className="text-xs">尝试 {slot.attempts.length}/3 · {slot.reason ?? "独立时点记录已保存"}</p>
            {slot.observation && <>
              <p className="text-sm">覆盖 {slot.observation.cohort.samples}/{slot.observation.cohort.expected} · 中位涨幅 {slot.observation.cohort.median_pct?.toFixed(2) ?? "未知"}%</p>
              <p className="break-all text-xs">观察：{slot.observation.observed_at}</p>
              <details className="mt-1 text-xs"><summary>逐股来源与供应商时间</summary>{slot.observation.rows.map(row => <p key={row.symbol} className="break-all">{row.symbol} · {row.provider_at} · {row.source_id} · {row.sources.join(" / ")}</p>)}</details>
            </>}
          </section>)}
        </div>
        <h4 className="text-sm font-medium">跨窗口异动回看</h4>
        <p className="text-xs text-muted-foreground">显示 {view.event_coverage.returned}/{view.event_coverage.total} 条，按供应商时间倒序{view.event_coverage.has_more ? "；仅显示最近 500 条，其余已保存在本地" : ""}</p>
        {!view.events.length && <p className="text-xs text-muted-foreground">暂无已记录异动；未采集不代表没有异动</p>}
        <ul className="my-2 space-y-1 text-xs">{view.events.map(e => <li key={e.id} className="break-words">{e.symbol} · {e.kind} · {e.move_pct === null ? "状态转换" : `${e.move_pct.toFixed(2)}%`} · 源 {e.provider_at} · 观察 {e.observed_at}</li>)}</ul>
      </>}
      <h4 className="mt-4 text-sm font-medium">内部任务状态</h4>
      <div className="mt-2 space-y-2">{Object.entries(view.schedule).map(([kind, time]) => {
        const task = view.tasks.find(t => t.kind === kind);
        return <div key={kind} className="rounded border border-border p-2 text-sm">
          <div className="flex flex-wrap items-center gap-3"><span>{time} {taskLabels[kind]} · {task ? observationLabels[task.status] ?? task.status : "未运行"}</span>
            {!demo && <button disabled={busy || loading || uncertain || task?.status === "COMPLETE" || (task?.attempts ?? 0) >= 3} onClick={() => void action(kind, "run")}>仅运行本地任务{task ? " / 重试" : ""}</button>}
            {!demo && task && !task.acknowledged && <button disabled={busy || uncertain} onClick={() => void action(kind, "acknowledge")}>标记已阅</button>}
            {task?.acknowledged && <span>已阅（不改变核验结论）</span>}
          </div>
          {task && <details className="mt-1 text-xs"><summary>结果与缺失明细（尝试 {task.attempts}/3）</summary><p className="break-words whitespace-pre-wrap">{JSON.stringify(task.output ?? { reason: task.reason }, null, 2)}</p></details>}
        </div>;
      })}</div>
      <h4 className="mt-4 text-sm font-medium">验证到期 · 到期不等于兑现</h4>
      <p className="text-xs text-muted-foreground">已检查 {view.due_coverage.evaluated_plans}/{view.due_coverage.eligible_plans} 晚条件{view.due_coverage.has_more ? "；按最近日期仅检查 20 晚，较早条件请在验证区按原日期查看" : ""}</p>
      {!view.due.length && <p className="text-xs text-muted-foreground">暂无到期条件；日历未知时不会猜测下一交易日</p>}
      <ul className="space-y-2 text-sm">{view.due.map(item => <li key={item.id}>{item.set_date} → {item.target_date ?? "日历未知"} · {observationLabels[item.state] ?? item.state} · 已核验 {item.summary.decided}/{item.summary.total}，未知 {item.summary.unknown}</li>)}</ul>
    </>}
  </GlassCard>;
}
