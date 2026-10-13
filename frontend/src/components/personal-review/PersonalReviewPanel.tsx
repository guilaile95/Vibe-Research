import { useEffect, useId, useRef, useState } from "react";
import { PriceBasisImport } from "./PriceBasisImport";
import { Link } from "react-router-dom";
import { parsePersonalReview, parseSavedAssessment, parseSavedPattern, parseExcursion, ReviewResponseError } from "@/lib/personalReviewValidation";
import { request } from "@/lib/api";
import { emptyAssessment, emptyPattern, eligiblePatterns, reviewNumber, type AssessmentContent, type AssessmentRevision, type Excursion, type PatternContent, type PersonalReview } from "@/lib/personalReview";

const input = "w-full rounded border border-input bg-background p-2 text-sm";
const button = "rounded border border-input px-3 py-2 text-sm disabled:opacity-50";
const reasonLabels: Record<string, string> = {
  OPENING_INVENTORY_UNKNOWN: "期初持仓边界未知，不能推定完整轮次",
  ACCOUNT_CORRECTION_REQUIRES_RECONCILIATION: "账户修正须先对账",
  CORRECTED_TRADE_REQUIRES_RECONCILIATION: "流水已修正，成本需先对账",
  SAME_INSTANT_ORDER_UNKNOWN: "同一时刻买卖先后无法证明",
  OVERSELL_OR_MISSING_HISTORY: "超卖或历史不完整",
  LEGACY_OPENING_EPISODE_UNSCORED: "期初存量退出，不计为完整轮次",
  FUTURE_EXECUTION_UNVERIFIED: "未来成交时间未核验，不纳入当前复查",
  INVALID_EXECUTION: "成交记录无法核验",
};

/** No AI context registration or model action: local ledger companion only. */
export function PersonalReviewPanel({ trade, refreshKey = "" }: { trade?: { trade_id: string; executed_at: string | null; voided_at?: string | null; execution_status: string }; refreshKey?: string }) {
  const formId = useId();
  const [data, setData] = useState<PersonalReview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertainWrite, setUncertainWrite] = useState(false);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState<AssessmentContent>(emptyAssessment);
  const [revision, setRevision] = useState(0);
  const [pattern, setPattern] = useState<PatternContent>(emptyPattern);
  const [patternId, setPatternId] = useState("");
  const [patternRevision, setPatternRevision] = useState(0);
  const [message, setMessage] = useState("");
  const [excursion, setExcursion] = useState<{ id: string; data: Excursion } | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    const token = ++generation.current;
    const controller = new AbortController();
    setData(null); setError(""); setExcursion(null); setMessage(""); setBusy(false); setUncertainWrite(false);
    request<unknown>("/personal-review", "GET", undefined, { signal: controller.signal }).then(value => {
      if (token !== generation.current) return;
      const parsed = parsePersonalReview(value);
      setData(parsed);
      const revisions = trade ? parsed.assessment_history[trade.trade_id] ?? [] : [];
      const prior = revisions[revisions.length - 1];
      setDraft(prior?.content ?? emptyAssessment()); setRevision(prior?.revision ?? 0);
    }).catch(e => { if (!controller.signal.aborted && token === generation.current) setError(e instanceof Error ? e.message : "个人复查读取失败"); });
    return () => { generation.current++; controller.abort(); };
  }, [trade?.trade_id, reload, refreshKey]);
  async function save(path: string, body: unknown) {
    if (busy || uncertainWrite) return;
    const token = generation.current;
    setBusy(true); setError("");
    try {
      const raw = await request<unknown>(path, "PUT", body);
      const result = path.includes("/patterns/") ? parseSavedPattern(raw, body as PatternContent & { revision: number }) : parseSavedAssessment(raw, body as AssessmentContent & { revision: number });
      if (generation.current === token && path.includes("/patterns/")) setPatternRevision(result.revision);
      if (generation.current === token) { setReload(n => n + 1); setMessage("已保存到本地个人复查"); }
    } catch (e) { if (generation.current === token) { if (e instanceof ReviewResponseError || (e as { status?: number })?.status === 0) setUncertainWrite(true); setError(e instanceof Error ? e.message : "保存失败"); } }
    finally { if (generation.current === token) setBusy(false); }
  }
  async function loadExcursion(id: string) {
    const token = generation.current;
    setExcursion(null); setError(""); setBusy(true);
    try { const value = await request<unknown>(`/personal-review/episodes/${id}/excursion`); if (token === generation.current) setExcursion({ id, data: parseExcursion(value) }); }
    catch (e) { if (token === generation.current) setError(e instanceof Error ? e.message : "价格区间读取失败"); }
    finally { if (token === generation.current) setBusy(false); }
  }
  const latestPatterns = data?.patterns.filter(p => !data.patterns.some(other => other.pattern_id === p.pattern_id && other.revision > p.revision)) ?? [];
  const applicable = trade?.executed_at && data ? eligiblePatterns(data.patterns, trade.executed_at) : [];
  return <section className="min-w-0 break-words space-y-3 rounded-xl border border-border p-4" data-testid="personal-review-panel">
    <h2 className="font-semibold">{trade ? "成交个人复查" : "个人复查 · 风险与模式卡"}</h2>
    <p className="text-xs text-muted-foreground">仅本地保存，默认不发给模型。自评不覆盖正式归属、硬风险或持仓权限。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error} <button className={button} onClick={() => { setBusy(false); setReload(n => n + 1); }}>重新加载</button></p>}
    {uncertainWrite && <p role="status" className="text-amber-500">写入结果待核验；当前草稿保留。请显式重新加载核对记录，核对前已停用重复保存。</p>}
    {message && <p role="status">{message}</p>}
    {!data && !error && <p role="status">正在读取本地复查…</p>}
    {data && trade && <>
      {trade.voided_at || trade.execution_status === "not_executed" ? <p>已作废或未成交记录不能新增个人复查</p> : <form className="space-y-3" onSubmit={e => { e.preventDefault(); void save(`/personal-review/assessments/${trade.trade_id}`, { ...draft, revision }); }}>
        <div className="block text-sm"><label htmlFor={`${formId}-environment`}>环境描述（事后自评）</label><textarea id={`${formId}-environment`} className={input} maxLength={500} value={draft.environment} onChange={e => setDraft({ ...draft, environment: e.target.value })} /></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="text-sm"><label htmlFor={`${formId}-board`}>收盘板位（事后标签）</label><input id={`${formId}-board`} className={input} type="number" min={1} max={100} value={draft.closing_board_rank ?? ""} onChange={e => setDraft({ ...draft, closing_board_rank: e.target.value ? Number(e.target.value) : null })} /></div>
          <div className="text-sm"><label htmlFor={`${formId}-stop`}>止损价情景（非正式计划）</label><input id={`${formId}-stop`} className={input} type="number" step="any" min="0.0001" value={draft.stop_price ?? ""} onChange={e => setDraft({ ...draft, stop_price: e.target.value ? Number(e.target.value) : null })} /></div>
          <div className="text-sm"><label htmlFor={`${formId}-judgment`}>判断自评</label><select id={`${formId}-judgment`} className={input} value={draft.judgment} onChange={e => setDraft({ ...draft, judgment: e.target.value as AssessmentContent["judgment"] })}><option value="unknown">未知 / 未评价</option><option value="correct">判断正确（自评）</option><option value="incorrect">判断错误（自评）</option></select></div>
          <div className="text-sm"><label htmlFor={`${formId}-execution`}>执行自评</label><select id={`${formId}-execution`} className={input} value={draft.execution} onChange={e => setDraft({ ...draft, execution: e.target.value as AssessmentContent["execution"] })}><option value="unknown">未知 / 未评价</option><option value="followed">按计划（自评）</option><option value="deviated">偏离计划（自评）</option></select></div>
        </div>
        <div className="block text-sm"><label htmlFor={`${formId}-pattern`}>打法版本（仅成交当日生效版本）</label><select id={`${formId}-pattern`} className={input} value={draft.pattern_id ? `${draft.pattern_id}:${draft.pattern_revision}` : ""} onChange={e => { const [id, rev] = e.target.value.split(":"); setDraft({ ...draft, pattern_id: id || null, pattern_revision: rev ? Number(rev) : null }); }}><option value="">未归类</option>{applicable.map(p => <option key={`${p.pattern_id}:${p.revision}`} value={`${p.pattern_id}:${p.revision}`}>{p.content.name} · v{p.revision}</option>)}</select></div>
        <div className="block text-sm"><label htmlFor={`${formId}-violations`}>违反条目（自报，一行一条，最多10条）</label><textarea id={`${formId}-violations`} className={input} value={draft.violations.join("\n")} onChange={e => setDraft({ ...draft, violations: e.target.value.split("\n").filter(Boolean) })} /></div>
        <div className="block text-sm"><label htmlFor={`${formId}-note`}>复查笔记</label><textarea id={`${formId}-note`} className={input} maxLength={2000} value={draft.note} onChange={e => setDraft({ ...draft, note: e.target.value })} /></div>
        <button type="submit" className={button} disabled={busy || uncertainWrite}>保存自评修订</button>
      </form>}
      <AssessmentHistory items={data.assessment_history[trade.trade_id] ?? []} />
    </>}
    {data && !trade && <>
      <p className="text-xs text-muted-foreground">流水数据时间：{data.data_time ?? "未知"} · 本次读取：{data.as_of}</p>
      {data.weekly && <p className="text-sm">本周本地复查（上海 {data.weekly.from} 至 {data.weekly.through_exclusive}，右端不含）：闭合 {data.weekly.summary.closed_count} 轮 · 金额覆盖 {data.weekly.summary.money_scored} · 净收益 {reviewNumber(data.weekly.summary.net_pnl)} 元；不进入 AI 周报。</p>}
      <div className="grid gap-3 sm:grid-cols-3">{data.windows.map(w => <div className="rounded border border-border p-3 text-sm" key={w.requested}>
        <h3>最近 {w.requested} 个闭合轮次</h3><p>实际 {w.closed_count} · 金额覆盖 {w.money_scored}{w.insufficient_samples ? " · 样本不足" : ""}</p>
        <p>净收益 {reviewNumber(w.net_pnl)} 元</p><p>胜 / 负 / 平：{w.wins} / {w.losses} / {w.flat}</p><p>胜率（排平）：{w.win_rate_excluding_flat === null ? "未知" : `${(w.win_rate_excluding_flat * 100).toFixed(1)}%`}</p>
        <p>偏离计划 {w.self_reported_deviations} · 违反条目 {w.self_reported_violations}（均自报，覆盖 {w.self_assessed_count}）</p>
      </div>)}</div>
      <details><summary className="cursor-pointer">风险情景与边界</summary><div className="space-y-2 text-sm"><p>账户权益参考 {reviewNumber(data.risk.equity_reference)} 元 · {data.risk.equity_confirmation} · 生效时间 {data.risk.equity_effective_at ?? "未知"}</p><p>在险金额为入场参考价到自报止损的剩余数量情景；不是当前风险或正式权限，权益时点未对齐，不算风险占比。</p>{data.risk.open_episodes.map(r => <p key={r.code}>{r.code} · 余量 {r.remaining_quantity} · 情景金额 {reviewNumber(r.entry_reference_stop_scenario)} 元 · 止损标注 {r.stop_recorded_at ?? "未知"}</p>)}</div></details>
      {data.diagnostics.map((d, i) => <p className="text-xs text-amber-500" key={i}>{d.code ?? "账户"}：{reasonLabels[d.reason] ?? d.reason}</p>)}
      <details><summary className="cursor-pointer">完整轮次与判断 / 执行复查（{data.closed_episodes.length}）</summary><div className="space-y-3 py-2">
        {!data.closed_episodes.length && <p className="text-sm">暂无可证明的完整闭合轮次。成交详情仍可记录个人自评。</p>}
        {data.closed_episodes.map(e => <article className="rounded border border-border p-3 text-sm" key={e.episode_id}>
          <p>{e.name}（{e.code}）· 持有 {e.holding_calendar_days} 自然日 · {e.state === "CLOSED" ? "完整闭合" : "混合归属，不评分"}</p><p>{e.opened_at} → {e.closed_at}</p>
          <p>毛收益 {reviewNumber(e.gross_pnl)} · 账本费用 {reviewNumber(e.fees)} · 净收益 {reviewNumber(e.net_pnl)} 元</p>
          <p>判断：{({ correct: "自评正确", incorrect: "自评错误", unknown: "未知" })[e.assessment?.content.judgment ?? "unknown"]} · 执行：{({ followed: "自评按计划", deviated: "自评偏离", unknown: "未知" })[e.assessment?.content.execution ?? "unknown"]}</p>
          {e.assessment && <p>环境：{e.assessment.content.environment || "未记"} · 收盘板位：{e.assessment.content.closing_board_rank ?? "未知"} · 自评时间 {e.assessment.saved_at}</p>}
          {e.formal_attributions.filter(Boolean).map((a, index) => <p key={index}>正式决策 <Link className="text-primary underline" to={`/decision-feedback?code=${e.code}`}>{a!.decision_id}</Link> · 决策时间 {a!.decision_committed_at} · 成交时间 {a!.trade_executed_at}</p>)}
          <button className={button} disabled={busy} onClick={() => void loadExcursion(e.episode_id)}>读取本地持有期价格证据</button>
          {excursion?.id === e.episode_id && <div className="mt-2 text-xs"><p>精确 MFE / MAE：未知。日线不能证明成交机会，企业行动可比性未证明。</p><p>不含买入和卖出当天的原始价格区间：{reviewNumber(excursion.data.raw_interior_low)} – {reviewNumber(excursion.data.raw_interior_high)} 元/股（不复权）；不计算收益率代理。</p><p>证据状态 {excursion.data.state} · 完整覆盖会话数 {excursion.data.source?.sessions ?? "未知"} · 数据时间 {excursion.data.source?.as_of ?? "未知"}</p>{excursion.data.adjusted_bound && <div className="mt-2"><p>同基准内部日线有利幅度下界 {reviewNumber(excursion.data.adjusted_bound.bounded_mfe_pct)}% / 不利幅度下界 {reviewNumber(excursion.data.adjusted_bound.bounded_mae_pct)}%</p><p>状态 {excursion.data.adjusted_bound.state} · 调整后入场参考 {reviewNumber(excursion.data.adjusted_bound.adjusted_entry_reference)} · 内部会话 {excursion.data.adjusted_bound.interior_sessions ?? "未知"}</p><p>供应商版本 {excursion.data.adjusted_bound.source?.provider_revision ?? "未知"} · 采集 {excursion.data.adjusted_bound.source?.captured_at ?? "未知"}</p><p>{excursion.data.adjusted_bound.limitations}</p></div>}</div>}
        </article>)}
      </div></details>
      <PriceBasisImport onSaved={() => setReload(n => n + 1)} />
      <details><summary className="cursor-pointer">模式卡 · 版本历史与复用</summary><div className="space-y-3 py-3">
        <div className="block text-sm"><label htmlFor={`${formId}-pattern-choice`}>编辑已有模式或新建</label><select id={`${formId}-pattern-choice`} className={input} value={patternId} onChange={e => { const p = latestPatterns.find(v => v.pattern_id === e.target.value); setPatternId(p?.pattern_id ?? ""); setPatternRevision(p?.revision ?? 0); setPattern(p?.content ?? emptyPattern()); }}><option value="">新建模式</option>{latestPatterns.map(p => <option key={p.pattern_id} value={p.pattern_id}>{p.content.name} v{p.revision}</option>)}</select></div>
        <form className="space-y-2" onSubmit={e => { e.preventDefault(); const id = patternId || crypto.randomUUID(); setPatternId(id); void save(`/personal-review/patterns/${id}`, { ...pattern, revision: patternRevision }); }}>
          {([ ["name", "名称"], ["setup", "适用环境"], ["entry_rule", "入场规则"], ["exit_rule", "退出规则"], ["invalidation", "失效条件"] ] as const).map(([field, title]) => <div className="block text-sm" key={field}><label htmlFor={`${formId}-${field}`}>{title}</label><textarea id={`${formId}-${field}`} required className={input} maxLength={field === "name" ? 80 : 1000} value={pattern[field]} onChange={e => setPattern({ ...pattern, [field]: e.target.value })} /></div>)}
          <p className="text-xs text-muted-foreground">保存为新版本，上海下一自然日生效（不是下一交易日）；不可倒填。AI 不会修改规则。</p><button className={button} disabled={busy || uncertainWrite}>发布新版本到本地</button>
        </form>
        {data.patterns.map(p => <article className="rounded border border-border p-3 text-sm" key={`${p.pattern_id}:${p.revision}`}><h3>{p.content.name} v{p.revision}</h3><p>生效 {p.effective_from} 至 {p.effective_until ?? "后续版本发布"}（右端不含）</p><p>环境：{p.content.setup}</p><p>入场：{p.content.entry_rule}</p><p>退出：{p.content.exit_rule}</p><p>失效：{p.content.invalidation}</p><p>关联自评轮次 {p.statistics.closed_count} · 金额覆盖 {p.statistics.money_scored} · 净收益 {reviewNumber(p.statistics.net_pnl)} 元</p><button className={button} onClick={() => { setPatternId(""); setPatternRevision(0); setPattern({ ...p.content, name: `${p.content.name}（副本）`.slice(0, 80) }); }}>复制为新模式草稿</button></article>)}
      </div></details>
      <ul className="space-y-1 text-xs text-muted-foreground">{data.limitations.map(l => <li key={l}>{l}</li>)}</ul>
    </>}
  </section>;
}
function AssessmentHistory({ items }: { items: AssessmentRevision[] }) {
  return <details><summary className="cursor-pointer text-sm">自评修订历史（{items.length}）</summary>{items.slice().reverse().map(item => <div className="mt-2 rounded border border-border p-2 text-xs" key={item.revision}><p>v{item.revision} · 保存 {item.saved_at} · 止损标注 {item.stop_recorded_at ?? "未设"}</p><p>{item.content.environment || "无环境描述"} · {item.content.note || "无笔记"}</p><p>判断 {item.content.judgment} / 执行 {item.content.execution} · 模式 {item.content.pattern_id ?? "未归类"} v{item.content.pattern_revision ?? "—"}</p></div>)}</details>;
}
