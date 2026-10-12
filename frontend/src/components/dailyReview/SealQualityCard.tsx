import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api } from "@/lib/api";
import { isSealQualityArchiveForDate, sealQualityNumber, sealQualityTime, type SealQualityArchive } from "@/lib/sealQuality";

const METRICS: [string, string, boolean][] = [
  ["never_broken_ratio", "涨停样本未开板比例", true],
  ["ever_opened_ratio", "涨停样本曾开板比例", true],
  ["average_broken_times", "平均开板次数", false],
  ["first_seal_by_0935_count", "09:35及以前首封", false],
  ["late_seal_count", "14:30及以后末封", false],
];
const FIELD_LABELS: Record<string, string> = { first_seal: "首封时间", last_seal: "末封时间", broken_times: "开板次数" };

/** Date-scoped archive view; changing the page date immediately hides old data. */
export function SealQualityCard({ tradeDate }: { tradeDate: string | null }) {
  const [state, setState] = useState<{ date: string; result: SealQualityArchive | null; error: boolean; loading: boolean } | null>(null);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const request = ++generation.current;
    if (!tradeDate) return;
    const controller = new AbortController();
    setState({ date: tradeDate, result: null, error: false, loading: true });
    api.sealQuality(tradeDate, controller.signal).then((result) => {
      if (controller.signal.aborted || request !== generation.current) return;
      if (!isSealQualityArchiveForDate(result, tradeDate)) {
        setState({ date: tradeDate, result: null, error: true, loading: false });
        return;
      }
      setState({ date: tradeDate, result, error: false, loading: false });
    }).catch(() => {
      if (controller.signal.aborted || request !== generation.current) return;
      setState({ date: tradeDate, result: null, error: true, loading: false });
    });
    return () => { controller.abort(); };
  }, [tradeDate, revision]);

  const current = state?.date === tradeDate ? state : null;
  const result = current?.result;
  const projection = result?.projection;
  return (
    <GlassCard className="mb-6">
      <section data-testid="seal-quality-card" aria-label="封板质量归档观测">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">封板质量 · 归档观测</h3>
          <button type="button" className="text-xs text-primary disabled:opacity-50" disabled={!tradeDate || current?.loading}
            onClick={() => setRevision((value) => value + 1)}>重新读取归档</button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">交易日：{tradeDate ?? "未确定"} · 只读已连接的本地证据，不启动采集或请求行情</p>
        {!tradeDate ? <p className="mt-3 text-sm">等待页面交易日，未使用今天的日期代替</p>
          : !current || current.loading ? <p className="mt-3 text-sm" role="status">正在读取这一天的归档…</p>
          : current.error ? <p className="mt-3 text-sm text-destructive" role="alert">归档读取未通过，未显示旧日期的结果</p>
          : result ? <>
            <p className="mt-3 text-sm" role="status">{result.message}</p>
            {result.reason_codes.includes("ARCHIVE_NOT_CONNECTED") ? <p className="mt-2 text-xs text-muted-foreground">需要已有的可信归档证据；当前生产采集不会自动保存这些原始字段</p> : null}
            {projection ? <>
              <p className="mt-2 text-xs">{projection.status === "normal" ? "字段完整" : projection.status === "partial" ? "部分字段缺失" : "质量字段不可评估"}
                {" · "}入选样本 {sealQualityNumber(projection.sample_count)} 只 · 范围外排除 {sealQualityNumber(projection.excluded_universe_count)} 只</p>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {METRICS.map(([key, label, ratio]) => <div key={key} className="rounded-lg bg-muted/25 p-2.5">
                  <p className="text-[11px] text-muted-foreground">{label}</p>
                  <p className="mt-1 font-mono text-lg" data-testid={`seal-${key}`}>{sealQualityNumber(projection.metrics[key], ratio)}</p>
                </div>)}
              </div>
              <p className="mt-3 text-xs text-muted-foreground">曾开板比例不是全市场炸板率。09:35/14:30为描述性阈值，含边界和早盘集合竞价，不代表策略或成交机会</p>
              <ul className="mt-2 text-xs text-muted-foreground">
                {Object.entries(projection.coverage).map(([key, value]) => <li key={key}>{FIELD_LABELS[key] ?? key}：已知 {value.known_count} / 缺失或无效 {sealQualityNumber(value.unknown_count)}；{value.complete ? "样本字段齐全" : "相关总体指标留空"}</li>)}
              </ul>
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer">查看来源身份与样本明细</summary>
                <p className="mt-2">来源日期：{projection.source_trade_date ?? "未验证"} · 捕获时间：{result.archive_identity?.captured_at ?? "—"}</p>
                <p>选择方式：LOCAL_LATEST（本地发布顺序），不是供应商修订先后，也不是历史当时可知数据</p>
                <p>归档观测不等于收盘定稿；未授予新增事实权威</p>
                <p className="break-all">发布：{result.archive_identity?.publication_id} · 观测：{result.archive_identity?.source_observation_id}</p>
                <p className="break-all">原始内容哈希：{result.archive_identity?.raw_payload_hash}</p>
                <div className="mt-2 overflow-x-auto"><table className="w-full text-left">
                  <thead><tr><th>代码</th><th>连板</th><th>首封</th><th>末封</th><th>开板次数</th><th>缺失/无效字段</th></tr></thead>
                  <tbody>{projection.rows.slice(0, 50).map((row) => <tr key={row.stock_code}>
                    <td>{row.stock_code}</td><td>{row.lbc}{row.zt_stat ? `（${row.zt_stat}）` : ""}</td>
                    <td>{sealQualityTime(row.first_seal)}</td><td>{sealQualityTime(row.last_seal)}</td><td>{sealQualityNumber(row.broken_times)}</td>
                    <td>{Object.keys(row.field_issues).map((key) => FIELD_LABELS[key] ?? key).join("、") || "无"}</td>
                  </tr>)}</tbody>
                </table></div>
                {projection.rows.length > 50 ? <p>明细展示前50只；聚合与覆盖使用全部 {projection.rows.length} 只样本</p> : null}
              </details>
            </> : null}
          </> : null}
      </section>
    </GlassCard>
  );
}
