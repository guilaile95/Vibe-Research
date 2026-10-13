import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api } from "@/lib/api";
import { isCohortIdentityForDate, type CohortIdentity } from "@/lib/cohortIdentity";

/** Date-owned read of stored lists; absence is not a price/performance outcome. */
export function CohortIdentityCard({ tradeDate }: { tradeDate: string | null }) {
  const [state, setState] = useState<{ date: string; result: CohortIdentity | null; error: boolean } | null>(null);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const request = ++generation.current;
    if (!tradeDate) return;
    const controller = new AbortController();
    setState(null);
    api.cohortIdentity(tradeDate, controller.signal).then(result => {
      if (controller.signal.aborted || generation.current !== request) return;
      setState({ date: tradeDate, result: isCohortIdentityForDate(result, tradeDate) ? result : null,
        error: !isCohortIdentityForDate(result, tradeDate) });
    }).catch(() => {
      if (controller.signal.aborted || generation.current !== request) return;
      setState({ date: tradeDate, result: null, error: true });
    });
    return () => controller.abort();
  }, [tradeDate, revision]);
  const current = state?.date === tradeDate ? state : null;
  const result = current?.result;
  return <GlassCard className="mb-6">
    <section data-testid="cohort-identity-card" aria-label="相邻交易日涨停名单对照">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">相邻交易日涨停名单对照</h3>
        <button type="button" className="text-xs text-primary disabled:opacity-50" disabled={!tradeDate}
          onClick={() => setRevision(x => x + 1)}>重新读取归档</button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">所选交易日：{tradeDate ?? "未确定"} · 当前存档版本的事后查阅，非历史时点可知数据</p>
      <p className="mt-2 text-xs text-muted-foreground">仅查阅名单身份；未在今日池中不等于下跌、亏损或跌停。不计算晋级率、收益或交易信号</p>
      {!tradeDate ? <p className="mt-3 text-sm">等待页面交易日，未使用今天的日期代替</p>
        : !current ? <p className="mt-3 text-sm" role="status">正在读取两日名单…</p>
        : current.error ? <p className="mt-3 text-sm" role="alert">名单读取未通过，未显示旧日期结果</p>
        : result ? <>
          <p className="mt-3 text-sm" role="status">{result.message}</p>
          {result.projection && result.evidence ? <>
            <p className="mt-2 text-xs">前一交易日 {result.previous_trade_date} → 所选交易日 {result.trade_date}</p>
            <div className="mt-3 overflow-x-auto"><table data-testid="cohort-members-table" className="w-full text-left text-xs">
              <thead><tr><th className="p-2">代码</th><th className="p-2">前日来源连续板数</th><th className="p-2">今日来源连续板数</th><th className="p-2">今日名单身份</th></tr></thead>
              <tbody>{result.projection.rows.map(row => <tr key={row.stock_code}>
                <td className="p-2 font-mono">{row.stock_code}</td><td className="p-2">{row.previous_boards}</td>
                <td className="p-2">{row.current_boards ?? "未知"}</td>
                <td className="p-2">{row.present_today ? "今日所选名单出现" : "今日所选名单未出现"}</td>
              </tr>)}</tbody>
            </table></div>
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer">查看两日来源证据</summary>
              <p className="mt-2">来源板数语义未经独立市场核验；N/M 窗口板数没有替代连续板数。范围为存档覆盖的沪深 A 股涨停名单</p>
              {([result.evidence.previous, result.evidence.current]).map(e => <div key={e.trade_date} className="mt-3 break-all">
                <p>{e.trade_date} · 来源 {e.source_ids.join("、")} · 输入完整性行数 {e.row_count}</p>
                <p>抓取 {e.fetched_at} · 快照 {e.snapshot_at} · 落库 {e.stored_at}</p>
                <p>规范化 envelope 内容 SHA256：{e.envelope_sha256}</p>
              </div>)}
              <p className="mt-2">内容哈希用于绑定本次已存记录，不是原始响应回执，也不证明历史当时已知或新增事实权威</p>
            </details>
          </> : <p className="mt-2 text-xs text-muted-foreground">未知不会当作空名单；仅使用已有归档，不启动行情采集</p>}
        </> : null}
    </section>
  </GlassCard>;
}
