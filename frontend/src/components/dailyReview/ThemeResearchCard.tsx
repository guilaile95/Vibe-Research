import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { get } from "@/lib/api";
import { isThemeResearchForDate, themeNumber, type ThemeResearchArchive, type ThemeMember } from "@/lib/themeResearch";

const stock = (m: ThemeMember) => `${m.name || m.stock_code}（${m.stock_code}，${themeNumber(m.boards)}板）`;
const seal = (v: string | null | undefined) => v && /^\d{6}$/.test(v) ? `${v.slice(0, 2)}:${v.slice(2, 4)}:${v.slice(4)}` : v || "未知";

export function ThemeResearchCard({ tradeDate }: { tradeDate: string | null }) {
  const [state, setState] = useState<{ date: string; result: ThemeResearchArchive | null; error: boolean; loading: boolean } | null>(null);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const token = ++generation.current;
    if (!tradeDate) return;
    const controller = new AbortController();
    setState({ date: tradeDate, result: null, error: false, loading: true });
    get<unknown>(`/market/theme-research?trade_date=${encodeURIComponent(tradeDate)}`, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted || token !== generation.current) return;
      const valid = isThemeResearchForDate(result, tradeDate);
      setState({ date: tradeDate, result: valid ? result : null, error: !valid, loading: false });
    }).catch(() => {
      if (!controller.signal.aborted && token === generation.current) setState({ date: tradeDate, result: null, error: true, loading: false });
    });
    return () => controller.abort();
  }, [tradeDate, revision]);
  const current = state?.date === tradeDate ? state : null;
  const result = current?.result;
  const p = result?.projection;
  return <GlassCard className="mb-6"><section data-testid="theme-research-card" aria-label="题材树与五日轮动归档研究">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">题材树 · 五日热度与轮动 · 龙头谱系</h3>
      <button type="button" className="text-xs text-primary disabled:opacity-50" disabled={!tradeDate || current?.loading}
        onClick={() => setRevision(x => x + 1)}>重新读取题材归档</button>
    </div>
    <p className="mt-2 text-xs text-muted-foreground">交易日：{tradeDate ?? "未确定"} · 只读当前归档版本，不启动采集 · 事后描述，不代表历史当时已知</p>
    {!tradeDate ? <p className="mt-3 text-sm">等待页面交易日，未以今天代替</p>
      : !current || current.loading ? <p role="status" className="mt-3 text-sm">正在读取固定五个交易日的归档…</p>
      : current.error ? <p role="alert" className="mt-3 text-sm text-destructive">日期或数据合同未通过，未显示旧结果</p>
      : result ? <><p className="mt-3 text-sm" role="status">{result.message}</p>
        {result.reason_codes.includes("ARCHIVE_NOT_CONNECTED") && <p className="mt-2 text-xs text-muted-foreground">需要日期有效的逐股题材原始分页、涨停池与同一响应复权价格归档；未连接的数据保持未知</p>}
        {p && <div className="mt-4 space-y-4">
          {p.fixture && <p className="text-xs text-amber-600">合成测试数据；未进行真实市场验收</p>}
          <p className="text-xs text-muted-foreground">{p.sessions[0]} 至 {p.trade_date} · 缺日不补齐、未知不作零 · 供应商标签保持独立，多标签只数不能相加作市场总数</p>
          <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-xs"><caption className="text-left font-medium">五交易日热度</caption>
            <thead><tr><th className="text-left">日期</th><th>涨停</th><th>题材覆盖</th><th>最高连板</th><th>炸板率</th><th>头部题材集中度</th><th>完整性</th></tr></thead>
            <tbody>{p.days.map(d => <tr key={d.date}><td>{d.date}</td><td className="text-center">{themeNumber(d.limit_up)}</td><td className="text-center">{themeNumber(d.covered)}/{themeNumber(d.limit_up)}</td><td className="text-center">{themeNumber(d.highest_board)}</td><td className="text-center">{themeNumber(d.broken_rate === null ? null : d.broken_rate * 100, true)}</td><td className="text-center">{themeNumber(d.concentration === null ? null : d.concentration * 100, true)}</td><td className="text-center">{d.complete ? "覆盖完整" : d.available ? "部分覆盖" : "缺数"}</td></tr>)}</tbody>
          </table></div>
          <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-xs"><caption className="text-left font-medium">五日题材轮动：只数 / 名次（按只数并列名次，保留全部并列）</caption>
            <thead><tr><th className="text-left">源站标签</th>{p.sessions.map(d => <th key={d}>{d.slice(5)}</th>)}<th>已见活跃日</th><th>前三日数</th></tr></thead>
            <tbody>{p.rotation.map(r => <tr key={r.tag}><td>{r.tag}</td>{r.cells.map(c => <td key={c.date} className="text-center">{c.lower_bound ? "≥" : ""}{themeNumber(c.count)} / {c.rank === null ? "—" : c.rank}</td>)}<td className="text-center">{r.observed_active_days}</td><td className="text-center">{r.top3_days}</td></tr>)}</tbody>
          </table>{!p.rotation.length && <p className="mt-2 text-xs">没有可核验的日期有效题材，未以行业分类代替</p>}</div>
          <details open><summary className="cursor-pointer text-sm font-medium">题材事件树与昨日成员反馈</summary>
            <div className="mt-2 space-y-3">{p.tree.map(t => <div key={t.tag} className="rounded bg-muted/20 p-2 text-xs">
              <strong>{t.tag}</strong> · 当日 {t.lower_bound ? "≥" : ""}{themeNumber(t.count)} 只 · 昨日成员 {themeNumber(t.previous_count)} 只，今日仍涨停 {themeNumber(t.continued_count)} 只 · 延续 {themeNumber(t.continuation_rate === null ? null : t.continuation_rate * 100, true)}{t.continuation_sample_only ? "（仅昨日已覆盖样本）" : ""}
              <p className="mt-1">首封 {seal(t.first_seal)} · 首板 {themeNumber(t.first_boards)} · 最高 {themeNumber(t.highest)}板 · 当前/昨日已归因成员今日炸板 {themeNumber(t.cohort_broken)}、跌停 {themeNumber(t.cohort_limit_down)}</p>
              <ul className="mt-1 space-y-1">{t.members.map(m => <li key={m.stock_code}>{stock(m)} · 首封 {seal(m.theme_first_seal ?? m.first_seal)} · 归因日期 {m.theme_source_date ?? "未知"}</li>)}</ul>
              {!t.members.length && <p className="mt-1">{t.count === 0 ? "昨日题材保留：今天未再出现涨停成员" : "今天归因缺失，不能判定退出"}</p>}
              <p className="mt-1 text-muted-foreground">昨日固定成员：{t.previous_members.map(m => m.stock_code).join("、") || "未知或无成员"}</p>
            </div>)}</div>
          </details>
          <details><summary className="cursor-pointer text-sm font-medium">所选日首板清单（按来源连续板数=1）</summary>
            <ul className="mt-2 space-y-1 text-xs">{p.days[4].firstboards.map(m => <li key={m.stock_code}>{stock(m)} · 首封 {seal(m.theme_first_seal ?? m.first_seal)} · {(m.tags || []).join(" + ") || "题材未知"}</li>)}</ul>
            {!p.days[4].firstboards.length && <p className="mt-2 text-xs">无可展示的首板记录；不据此推断全市场零首板</p>}
          </details>
          <details><summary className="cursor-pointer text-sm font-medium">龙头谱系（每日最高连板全部并列，窗口内首次出现起算）</summary>
            <p className="mt-2 text-xs text-muted-foreground">同一供应商响应内前复权收盘价，CNY/股；不是总回报或可成交收益。停牌/缺失不延用收盘价，缺末日不以较早收盘替代</p>
            <div className="mt-2 space-y-2">{p.lineage.map(l => <div key={l.stock_code} className="rounded bg-muted/20 p-2 text-xs">
              <strong>{l.name || l.stock_code}（{l.stock_code}）</strong> · {l.appear_date} {l.boards_then}板 · 至所选日 {themeNumber(l.cum_return_pct, true)} · 区间最高 {themeNumber(l.peak_cum_return_pct, true)} · 距高点 {themeNumber(l.drawdown_from_peak_pct, true)}
              <p className="mt-1">{l.series.map(s => `${s.date}: ${themeNumber(s.cum_return_pct, true)}`).join(" · ")}</p>
              <p className="mt-1 break-all text-muted-foreground">复权依据：{l.adjustment_basis_id || "未知"} · {l.status === "complete" ? "窗口价格齐全" : "价格未知或不齐全"}</p>
            </div>)}</div>
          </details>
          <details><summary className="cursor-pointer text-xs">归档来源与修订凭据</summary><p className="mt-2 text-xs">采集时间仅证明本地获得数据的时间；不证明公开时间。fixture=true 为合成测试，不是实盘验证</p>
            {p.days.map(d => <pre key={d.date} className="mt-2 whitespace-pre-wrap break-all text-[10px]">{d.date}{"\n"}{JSON.stringify(d.source, null, 2)}</pre>)}
          </details>
        </div>}
      </> : null}
  </section></GlassCard>;
}
