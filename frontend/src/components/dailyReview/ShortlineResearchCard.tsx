import { useEffect, useRef, useState } from "react";
import { RegimeAnnotationForm } from "@/components/dailyReview/RegimeAnnotationForm";
import { GlassCard } from "@/components/ui/GlassCard";
import { request } from "@/lib/api";
import { isShortlineResearchForDate, type ShortlineResearch, type Stats } from "@/lib/shortlineResearch";

const fmt = (value: number | null | undefined, percent = false) => value == null ? "未知" : `${(percent ? value * 100 : value).toFixed(2)}${percent ? "%" : ""}`;
const labels: Record<string, string> = { all_yesterday: "昨日完整并集", yesterday_limit_up: "昨日涨停", yesterday_broken: "昨日炸板",
  yesterday_first_board: "昨日首板", yesterday_multi_board: "昨日连板", limit_up_count: "涨停数", highest_board: "最高连续板",
  broken_rate: "炸板率", money_effect_pct: "昨日涨停中位收益(%)", deep_loss_count: "跌幅≥5%数量", promotion_1_to_2: "1进2",
  positive: "上涨", negative: "下跌", flat: "平盘", deep_loss: "跌幅≥5%", limit_up: "涨停", limit_down: "跌停", unknown: "未知",
  previous_boards: "入场日连续板数", last_seal_time: "入场日末封时间", entry_environment_highest_board: "入场日全市场最高连续板",
  by_0935: "09:35前", after_1430: "14:30后", middle_session: "其余盘中" };
function StatsLine({ value }: { value: Stats }) {
  return <p className="text-xs leading-6">完整分母 {value.denominator} · 有效收益 {value.observed} · 未知 {value.unknown} · 均值 {fmt(value.mean_pct)}% · 中位 {fmt(value.median_pct)}% · 上涨 {value.positive_count} / 下跌 {value.negative_count} / 平盘 {value.flat_count} · 跌幅≥5% {value.loss_ge_5_count ?? "未知"} · 参考开盘溢价 {fmt(value.open_premium_mean_pct)}%</p>;
}
/** Date-owned archive GET only; no scheduled polling, provider/model or writes. */
export function ShortlineResearchCard({ tradeDate }: { tradeDate: string | null }) {
  const [state, setState] = useState<{ day: string; result: ShortlineResearch | null; error: boolean } | null>(null);
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState("today");
  const [page, setPage] = useState(0);
  const [windowSize, setWindowSize] = useState(20);
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setState(null); setPage(0);
    if (!tradeDate) return;
    const controller = new AbortController();
    request<unknown>(`/market/shortline-research?trade_date=${encodeURIComponent(tradeDate)}`, "GET", undefined, { signal: controller.signal })
      .then(value => {
        if (controller.signal.aborted || current !== generation.current) return;
        setState({ day: tradeDate, result: isShortlineResearchForDate(value, tradeDate) ? value : null, error: !isShortlineResearchForDate(value, tradeDate) });
      }).catch(() => {
        if (!controller.signal.aborted && current === generation.current) setState({ day: tradeDate, result: null, error: true });
      });
    return () => controller.abort();
  }, [tradeDate, revision]);
  const current = state?.day === tradeDate ? state : null;
  const result = current?.result;
  const p = result?.projection;
  const sample = p?.samples.windows.find(w => w.sessions === windowSize);
  const count = p?.cohort.rows.length ?? 0;
  return <GlassCard className="mb-6"><section aria-label="短线完整反馈与历史研究" data-testid="shortline-research-card">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">短线完整反馈与历史研究</h3>
      <button type="button" className="text-xs text-primary disabled:opacity-50" disabled={!tradeDate} onClick={() => setRevision(v => v + 1)}>重新读取研究归档</button></div>
    <p className="mt-2 text-xs text-muted-foreground">{tradeDate ?? "日期未确定"} · 当前归档版本的事后研究 · 非历史时点可知数据 · 无交易授权</p>
    {!tradeDate ? <p className="mt-3 text-sm">等待页面交易日，未使用今天代替</p> : !current ? <p role="status" className="mt-3 text-sm">读取原始回执与固定窗口…</p>
      : current.error ? <p role="alert" className="mt-3 text-sm">读取或合同核验失败，未显示旧日期数据</p> : result ? <>
        <p role="status" className="mt-3 text-sm">{result.message}</p>
        {result.fixture && <p role="alert" className="mt-2 text-sm font-semibold text-amber-600">合成案例，非真实市场采集</p>}
        <p className="mt-2 text-xs">覆盖状态：{result.status} · {result.reason_codes.join(" / ") || "当前输入已核验"}。完整输入不代表来源已正式定稿或可成交</p>
        {p ? <>
          <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="研究视图">
            {[["today", "今日事实"], ["cohort", "完整昨日反馈"], ["history", "历史分位"], ["samples", "涨停样本"], ["structure", "结构与字段"]].map(([key, label]) =>
              <button key={key} type="button" role="tab" aria-selected={tab === key} className={`rounded px-3 py-2 text-xs ${tab === key ? "bg-primary/15 text-primary" : "bg-muted"}`} onClick={() => setTab(key)}>{label}</button>)}
          </div>
          <div role="tabpanel" className="mt-4">
            {tab === "today" && <>
              <p className="text-sm">涨停 {p.daily.limit_up_count ?? "未知"} · 炸板 {p.daily.broken_count ?? "未知"} · 跌停 {p.daily.limit_down_count ?? "未知"} · 最高连续板 {p.daily.highest_board ?? "未知"}</p>
              <p className="mt-2 text-xs">炸板率 {fmt(p.daily.broken_rate, true)} · 去重分母 {p.daily.broken_denominator ?? "未知"} · 来源池交集 {p.daily.pool_overlap_count ?? "未知"}</p>
              <p className="mt-2 text-xs">梯队缺档：{p.daily.ladder_gaps === null ? "未知" : p.daily.ladder_gaps.join("、") || "无"}；连续板数来自来源，不以N天M板替代</p>
              <p className="mt-3 text-xs">封板字段覆盖 {p.daily.seal_quality.broken_times_coverage ?? "未知"}/{p.daily.seal_quality.denominator ?? "未知"} · 未炸 {p.daily.seal_quality.never_broken_count ?? "未知"} · 回封 {p.daily.seal_quality.reopened_count ?? "未知"}</p>
              <p className="mt-2 text-xs">平均开板 {fmt(p.daily.seal_quality.average_broken_times)} 次 · 09:35前首封 {p.daily.seal_quality.early_first_seal_count ?? "未知"} · 14:30后末封 {p.daily.seal_quality.late_last_seal_count ?? "未知"} · 封单合计 {fmt(p.daily.seal_quality.seal_fund_total_yuan)} 元</p>
              {p.daily.price_limit_bands && <p className="mt-2 text-xs">来源价格上下限匹配：10% {fmt(p.daily.price_limit_bands.share_10, true)} · 20% {fmt(p.daily.price_limit_bands.share_20, true)} · 覆盖 {p.daily.price_limit_bands.coverage}/{p.daily.price_limit_bands.denominator ?? "未知"}。只描述价格取分一致，不认证法律制度</p>}
              <p className="mt-2 text-xs text-muted-foreground">涨停股盘中开板比例 {fmt(p.daily.seal_quality.ever_opened_ratio, true)}，分母与炸板率不同。缺字段不补零</p>
            </>}
            {tab === "cohort" && <>
              <p className="text-xs">{result.previous_trade_date} → {result.trade_date}。完整并集 {p.cohort.union_denominator ?? "未知"}，涨停池 {p.cohort.previous_limit_up_denominator ?? "未知"}，炸板池 {p.cohort.previous_broken_denominator ?? "未知"}，重叠 {p.cohort.overlap_count ?? "未知"}</p>
              {p.cohort.status === "unavailable" ? <p className="mt-3 text-sm">缺少完整昨日涨停与炸板原始名单，不能确定分母</p> : <>
                {Object.entries(p.cohort.groups).map(([name, group]) => <div key={name} className="mt-3"><p className="text-xs font-semibold">{labels[name] ?? name}</p><StatsLine value={group} /></div>)}
                <p className="mt-3 text-xs">结果分类有效 {p.cohort.outcome_coverage?.classified ?? "未知"}，未知 {p.cohort.outcome_coverage?.unknown ?? "未知"}。价格收益与结果分类分别核验</p>
                <div className="mt-3 flex flex-wrap gap-3">{p.cohort.promotion.map(t => <p key={t.previous_boards} className="text-xs">来源连续 {t.previous_boards}→{t.previous_boards + 1}：{t.promoted}/{t.denominator}，未知 {t.unknown}，比例 {fmt(t.rate, true)}</p>)}</div>
                <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-xs" data-testid="shortline-cohort-table"><thead><tr>{["代码", "昨日身份", "今日收益(%)", "开盘溢价(%)", "今日结果", "行情状态"].map(x => <th key={x} className="p-2">{x}</th>)}</tr></thead>
                  <tbody>{p.cohort.rows.slice(page * 20, (page + 1) * 20).map(r => <tr key={r.stock_code}><td className="p-2 font-mono">{r.stock_code}</td><td className="p-2">{r.previous_limit_up ? `${r.previous_boards ?? "未知"}板` : ""}{r.previous_broken ? " 炸板" : ""}</td><td className="p-2">{fmt(r.return_pct)}</td><td className="p-2">{fmt(r.open_premium_pct)}</td><td className="p-2">{labels[r.result] ?? r.result}</td><td className="p-2">{r.price_status}</td></tr>)}</tbody></table></div>
                <div className="mt-2 flex items-center gap-4 text-xs"><button disabled={page === 0} onClick={() => setPage(v => v - 1)}>上一页</button><span>{page + 1}/{Math.max(1, Math.ceil(count / 20))} · 完整名单 {count} 只；分页不改变分母</span><button disabled={(page + 1) * 20 >= count} onClick={() => setPage(v => v + 1)}>下一页</button></div>
              </>}
            </>}
            {tab === "history" && <><p className="text-xs">只比较所选日期之前的固定交易日窗口，缺失不向前补齐；完整窗口才给相对分位。相同值按中位秩，不是预测概率</p>
              {p.history.windows.map(w => <details key={w.sessions} className="mt-3" open={w.sessions === 10}><summary className="text-xs cursor-pointer">前 {w.sessions} 个交易日 · {w.dates[0] ?? "未知"} 至 {w.dates[w.dates.length - 1] ?? "未知"}</summary>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(w.metrics).map(([key, m]) => <p key={key} className="text-xs">{labels[key] ?? key}：当前 {fmt(m.current)} · 分位 {fmt(m.percentile, true)} · 样本 {m.sample_count}/{m.expected_sessions} · 缺失 {m.missing_dates.length} 日</p>)}</div></details>)}</>}
            {tab === "samples" && <><p className="text-xs">完整入场日涨停名单的事后次日表现；入场日环境分组，未计排队、成交、手续费及滑点</p>
              <label className="mt-3 block text-xs">入场日窗口 <select aria-label="样本窗口" value={windowSize} onChange={e => setWindowSize(Number(e.target.value))} className="ml-2 rounded bg-muted p-2">{[20,30,60,90].map(n => <option key={n} value={n}>{n}个交易日</option>)}</select></label>
              {sample && <><p className="mt-2 text-xs">缺少完整入场名单 {sample.missing_entry_dates.length} 日 · 状态 {sample.status}</p><StatsLine value={sample.summary} />
                {Object.entries(sample.groups).map(([key, groups]) => <details key={key} className="mt-3"><summary className="cursor-pointer text-xs">按{labels[key] ?? key}分组</summary>{groups.map(g => <div key={g.label} className="mt-2"><p className="text-xs font-semibold">{labels[g.label] ?? g.label}</p><StatsLine value={g} /></div>)}</details>)}</>}
            </>}
            {tab === "structure" && <><p className="text-xs">市场数量变化：最近10个交易日与此前20个交易日，互不重叠</p>
              {Object.entries(p.structure.market_structure).map(([name,w]) => <p key={name} className="mt-2 text-xs">{name === "recent_10" ? "最近10日" : "此前20日"}：平均涨停数 {fmt(w.mean_limit_up_count)} · 中位 {fmt(w.median_limit_up_count)} · 来源10%价格带占比中位 {fmt(w.source_10pct_band_share_median, true)} · 20%价格带 {fmt(w.source_20pct_band_share_median, true)}，有效日期 {w.samples}/{w.expected}</p>)}
              <p className="mt-3 text-xs">{p.structure.interpretation}</p>{p.structure.field_drift.map(d => <p key={d.kind} className="mt-2 break-words text-xs">{d.kind} · {d.status} · {d.observed_dates.join(" → ")} · 新出现：{d.added.join("、") || "无证据"} · 未再观察到：{d.not_observed.join("、") || "无证据"}</p>)}
              {p.structure.field_drift.filter(d => d.versions?.length).map(d => <details key={`history-${d.kind}`} className="mt-2 text-xs"><summary className="cursor-pointer">{d.kind} 原始字段版本历史</summary>{d.versions?.map(v => <p key={`${v.since}:${v.signature}`} className="mt-2 break-words">{v.since} 至 {v.until} · {v.samples} 个已观察日期 · {v.fields.join("、")}</p>)}</details>)}
              <p className="mt-3 text-xs">制度事件为用户人工记录，未经核验；不从代码前缀或数量变化反推制度</p>
              {(p.structure.regime_events.events ?? []).map(e => <div key={e.id} className="mt-3 text-xs"><p>{e.effective_date} · {e.title} · {e.upcoming ? "尚未施行的计划记录" : "所选日已到记录日期"}</p><p className="whitespace-pre-wrap">{e.note}</p>{e.source_url && <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="break-all text-primary">用户提供的来源链接</a>}<p>人工记录，非官方核验 · 记录时间 {e.created_at}</p></div>)}
            </>}
          </div>
        </> : null}
        <details className="mt-4"><summary className="cursor-pointer text-xs">输入要求、来源回执与限制</summary><ul className="mt-2 list-disc pl-5 text-xs space-y-1">{result.input_requirements.map(x => <li key={x}>{x}</li>)}{result.limitations.map(x => <li key={x}>{x}</li>)}</ul>
          {result.evidence.filter(e => e.trade_date === tradeDate || e.trade_date === result.previous_trade_date).map(e => <div key={`${e.trade_date}:${e.kind}`} className="mt-3 text-xs break-all"><p>{e.trade_date} · {e.kind} · {e.status} · 来源定稿状态 {e.source_finality} · 行数 {e.row_count}/{e.source_total ?? "源总数未知"}</p>{e.receipts.map(r => <div key={r.observation_id}><p>{r.source_ids.join("、")} · 抓取 {r.captured_at} · 本地接收 {r.locally_received_at}</p><p>回执 {r.observation_id} · {r.raw_payload_hash}</p></div>)}</div>)}
          <p className="mt-2 text-xs">接收时间不是提交时间或历史可知性证明；没有时间点权限升级</p>
        </details>
      </> : null}
    {tradeDate && <RegimeAnnotationForm key={tradeDate} tradeDate={tradeDate} onSaved={() => setRevision(v => v + 1)} />}
  </section></GlassCard>;
}
