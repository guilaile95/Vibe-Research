import { useEffect, useRef, useState } from "react";
import { request } from "@/lib/api";
import { parseExtendedResearch, validResearchDate, type ExtendedBlock, type ExtendedKind, type ExtendedPublicResearch } from "@/lib/extendedPublicResearch";

const show = (v: unknown) => v === null || v === undefined ? "未知" : typeof v === "number" ? v.toLocaleString("zh-CN", { maximumFractionDigits: 6 }) : typeof v === "boolean" ? v ? "是" : "否" : typeof v === "string" ? v : "无效字段";
function Grid({ rows, columns }: { rows: Record<string, any>[]; columns: [string, string][] }) {
  return <div className="max-w-full overflow-x-auto"><table className="min-w-full text-left text-xs"><thead><tr>{columns.map(([k, label]) => <th key={k} className="whitespace-nowrap p-2">{label}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={r.id || r.date || i}>{columns.map(([k]) => <td key={k} className="p-2 align-top">{show(r[k])}</td>)}</tr>)}</tbody></table></div>;
}
function Rows({ block }: { block: ExtendedBlock }) {
  if (!block.rows.length) return <p>暂无合格记录；缺失不作为零值</p>;
  if (block.source_id === "em_market_trend") return <>{block.rows.map(r => <div key={r.id} className="space-y-2">
    <p>{r.name} · {r.index_code} · {r.exchange} · {r.date} · 收盘 {show(r.close)} 点{r.provisional ? " · 盘中未完成" : ""}</p>
    <Grid rows={[r.metrics]} columns={[["return_5d_pct", "5日%"], ["return_20d_pct", "20日%"], ["return_60d_pct", "60日%"], ["return_250d_pct", "250日%"], ["ytd_pct", "年初至今%"], ["ytd_basis_date", "上年末基准日"], ["ma20", "20日均线"], ["ma60", "60日均线"], ["ma250", "250日均线"], ["high250", "250日最高收盘"], ["low250", "250日最低收盘"], ["off_high250_pct", "距最高收盘%"]]} />
    <details><summary>固定交易日窗口与缺日</summary>{Object.entries(r.windows as Record<string, any>).map(([n, w]) => <p key={n} className="break-words text-xs">{n}日：应有 {w.expected_dates.length} 个参考收盘，实有 {w.observed_dates.length}；缺失 {w.missing_dates.join("、") || "无"}<br />预期日期：{w.expected_dates.join("、")}</p>)}</details>
  </div>)}</>;
  if (block.source_id === "index_valuation") return <><p className="text-xs">非正市盈率表示亏损/无定义，不解释为便宜；两种股本口径不可混用</p><Grid rows={block.rows} columns={[["date", "源日期"], ["index_code", "指数"], ["pe_total", "PE总股本（倍）"], ["pe_calculation", "PE计算股本（倍）"], ["dividend_yield_total_pct", "股息率总股本%"], ["dividend_yield_calculation_pct", "股息率计算股本%"]]} /></>;
  if (block.source_id === "chinabond_yield_curve") return <Grid rows={block.rows} columns={[["date", "源日期"], ["curve", "曲线"], ["tenor", "期限"], ["yield_pct", "收益率%（非价格/持有期回报）"]]} />;
  if (["global_quote_ref", "cn_quote_ref"].includes(block.source_id)) return <>{block.rows.map(r => <div key={r.id} className="space-y-2">
    <Grid rows={[r.quote, r.benchmark]} columns={[["key", "来源标识"], ["name", "名称"], ["price", "报价"], ["currency", "币种（指数不适用）"], ["unit", "单位"], ["source_time", "独立源时间UTC"], ["session_date", "交易所当地报价日"], ["timezone", "时区"]]} />
    <p className="break-words text-xs">基准参考日 {r.reference_session_date} · 时钟时段 {r.clock_phase} · 来源陈旧线索 {show(r.source_stale)} · 报价距采集 {show(r.quote_age_seconds_at_capture)} 秒 · 基准距采集 {show(r.benchmark_age_seconds_at_capture)} 秒</p>
    <p className="text-xs">归档快照不认证实时新鲜度；{r.after_requested_date ? "报价晚于所选截止日，仅供诊断，不进入该日期研究依据" : "参考日不是官方交易日历"}</p>
  </div>)}</>;
  if (["global_financials_pit", "cn_financials_ytd"].includes(block.source_id)) return <>
    <p className="text-xs">公告日筛选的当前版本，不是历史版本PIT；累计、全年累计、单季分别保留，不混算TTM。金额为来源原始数值，缩放单位未核实，不换算币种金额或估值</p>
    <Grid rows={block.rows} columns={[["returned_secucode", "源证券标识"], ["start", "期初"], ["end", "期末"], ["notice_date", "公告日"], ["period_kind", "期间类型"], ["period_months", "月数"], ["currency", "报告币种"], ["revenue", "营收（原始缩放未知）"], ["net_profit_parent", "归母净利（缩放未知）"], ["net_profit_deducted", "扣非"], ["eps_basic", "基本EPS（报告币种/股）"], ["consolidation_scope", "源合并口径"]]} />
    <p className="break-words text-xs">行覆盖：{Object.entries(block.counters || {}).map(([k, v]) => `${k}=${v}`).join(" · ")}</p>
  </>;
  return <><p className="text-xs">年度一致预期，非公司承诺；报告币种可能不同于报价币种。未提供升级/降级评级。</p><Grid rows={block.rows} columns={[["fiscal_label", "财年"], ["fiscal_end", "实际财年截止"], ["horizon", "源预期期间"], ["currency", "报告币种"], ["quote_currency", "报价币种"], ["eps_avg", "EPS均值"], ["eps_low", "EPS最低"], ["eps_high", "EPS最高"], ["analyst_count", "机构数"], ["revenue_estimate", "营收预期（报告币种）"]]} /></>;
}

export function ExtendedResearchCard({ kind, tradeDate, market, symbol }: { kind: ExtendedKind; tradeDate: string | null; market?: string; symbol?: string }) {
  const [open, setOpen] = useState(false), [version, setVersion] = useState(0);
  const [state, setState] = useState<{ key: string; data?: ExtendedPublicResearch; error?: string }>({ key: "" });
  const serial = useRef(0);
  const key = `${kind}|${market || "CN"}|${symbol || ""}|${tradeDate || ""}`;
  const current = state.key === key ? state : { key };
  useEffect(() => {
    const id = ++serial.current;
    if (!open || !validResearchDate(tradeDate)) return;
    setState({ key });
    const query = new URLSearchParams({ as_of: tradeDate });
    if (kind === "company") { query.set("market", market || ""); query.set("symbol", symbol || ""); }
    void request<unknown>(`/public-research/${kind === "market" ? "market-context" : "company-inputs"}?${query}`).then(value => {
      const data = parseExtendedResearch(value, { kind, asOf: tradeDate, market, symbol });
      if (serial.current === id) setState({ key, data });
    }).catch(() => { if (serial.current === id) setState({ key, error: "归档读取或来源合同校验失败，请重试" }); });
    return () => { serial.current += 1; };
  }, [open, version, key, kind, tradeDate, market, symbol]);
  return <section aria-label={kind === "market" ? "指数估值利率研究归档" : "公司原始来源归档"} className="my-4 min-w-0 space-y-3 rounded-lg border p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{kind === "market" ? "指数趋势、估值与国债利率" : `${market} ${symbol} 财务与预期原料`}</h3><button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => setOpen(v => !v)}>{open ? "收起来源归档" : "读取来源归档"}</button></div>
    <p className="text-xs text-muted-foreground">截止日 {tradeDate || "未选择"} · 只读已有归档，不联网采集或调用模型</p>
    {open && (!validResearchDate(tradeDate) ? <p>先选择有效研究日期；不使用系统今天替代缺失业务日</p> : <>
      <button type="button" className="rounded border px-3 py-1 text-sm" onClick={() => setVersion(v => v + 1)}>重读研究原料</button>
      {current.error ? <p role="alert">{current.error}</p> : !current.data ? <p role="status">正在读取研究原料…</p> : <>
        <p role="status">{current.data.status} · {current.data.message}</p>
        {current.data.fixture && <p className="rounded border border-amber-500 p-2">合成案例：非真实市场数据</p>}
        <p className="break-words text-xs">缺失：{current.data.missing_sources.map(s => `${s.source_id} ${s.subject}`).join("、") || "无来源缺失；各行仍可能缺字段"}</p>
        {current.data.blocks.map(block => <article key={block.source_id + block.subject} className="min-w-0 space-y-2 rounded border p-3">
          <h4 className="break-words font-medium">{block.label} · {block.subject} · {block.status}{block.archive_stale ? " · 归档陈旧" : ""}</h4>
          <p className="text-sm">{block.guard}</p>
          <Rows block={block} />
          <p className="break-words text-xs">覆盖 / 限制：{block.reason_codes.join(" · ")}</p>
          <details><summary>原始来源与版本</summary><p className="break-all text-xs">{block.source_url}<br />采集 {block.captured_at}<br />接收 {block.evidence.locally_received_at}<br />{block.evidence.raw_payload_hash}<br />{block.evidence.observation_id}<br />公开可读不等于自由再分发，数据许可未核实；历史当时已知声明 NONE</p></details>
        </article>)}
        {current.data.turnover && <article className="min-w-0 space-y-2 rounded border p-3"><h4>沪深两市成交额近60个交易日</h4><p className="text-xs">上证指数 + 深证综指，单位 CNY；缺一侧当日总额未知 · 20日均额 {show(current.data.turnover.ma20)} · 60日均额 {show(current.data.turnover.ma60)}</p><Grid rows={current.data.turnover.rows} columns={[["date", "交易日"], ["sh", "上海CNY"], ["sz_composite", "深圳综指CNY"], ["total", "两市合计CNY"]]} /></article>}
      </>}
    </>)}
  </section>;
}

export function CompanyArchiveCard({ market, symbol }: { market: string; symbol: string }) {
  const [date, setDate] = useState("");
  return <div><label className="text-sm">原料研究截止日 <input aria-label="原料研究截止日" type="date" value={date} onChange={e => setDate(e.target.value)} className="rounded border bg-background p-2" /></label><ExtendedResearchCard kind="company" tradeDate={date || null} market={market} symbol={symbol} /></div>;
}
