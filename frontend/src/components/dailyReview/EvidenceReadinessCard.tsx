import { useEffect, useRef, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api } from "@/lib/api";
import { isEvidenceReadinessForDate, type EvidenceReadiness, type EvidenceStatus } from "@/lib/evidenceReadiness";

const labels = { seal_quality: "封板质量", cohort_identity: "两日名单", next_day_verification: "明日验证事前事实" };
const statuses: Record<EvidenceStatus, string> = { not_configured: "未连接归档", missing: "缺少所需归档", ineligible: "证据不足或未通过检查", busy: "归档写入中，暂不可读", ready: "现有证据可读取" };
const windows = { CALENDAR_UNKNOWN: "日历未确认", OPEN: "当前可以写下条件", SEALED: "已封存，不能补写条件", NOT_YET_OPEN: "尚未到收盘后的填写窗口" };

export function EvidenceReadinessCard({ tradeDate }: { tradeDate: string | null }) {
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const [state, setState] = useState<{ date: string; result: EvidenceReadiness | null; error: boolean } | null>(null);
  useEffect(() => {
    const request = ++generation.current;
    if (!tradeDate) return;
    const controller = new AbortController();
    setState(null);
    api.evidenceReadiness(tradeDate, controller.signal).then(result => {
      if (controller.signal.aborted || generation.current !== request) return;
      const valid = isEvidenceReadinessForDate(result, tradeDate);
      setState({ date: tradeDate, result: valid ? result : null, error: !valid });
    }).catch(() => {
      if (!controller.signal.aborted && generation.current === request) setState({ date: tradeDate, result: null, error: true });
    });
    return () => controller.abort();
  }, [tradeDate, revision]);
  const current = state?.date === tradeDate ? state : null;
  const result = current?.result;
  return <GlassCard className="mb-6">
    <section data-testid="evidence-readiness-card" aria-label="归档证据检查">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">归档证据检查</h3>
        <button type="button" className="text-xs text-primary disabled:opacity-50" disabled={!tradeDate}
          onClick={() => setRevision(x => x + 1)}>重新检查已有归档</button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">所选交易日：{tradeDate ?? "未确定"} · 只读检查现有归档，不请求行情或导入数据</p>
      {!tradeDate ? <p className="mt-3 text-sm">等待页面交易日，未用今天代替</p>
        : !current ? <p className="mt-3 text-sm" role="status">正在检查归档证据…</p>
        : current.error ? <p className="mt-3 text-sm" role="alert">归档检查未通过，未显示旧日期结果；可重新检查</p>
        : result ? <>
          <ul className="mt-3 space-y-3">{result.features.map(row => <li key={row.feature} data-testid={`readiness-${row.feature}`} className="text-xs">
            <p className="font-medium">{labels[row.feature]}：{statuses[row.status]}</p>
            <p className="mt-1 text-muted-foreground">所需日期：{row.required_dates.join("、")}</p>
            <p className="mt-1">{row.requirements}</p><p className="mt-1">{row.next_step}</p>
            {row.reason_codes.length > 0 && <p className="mt-1 break-words text-muted-foreground">检查代码：{row.reason_codes.join("、")}</p>}
          </li>)}</ul>
          <div className="mt-3 text-xs" data-testid="readiness-journal-window">
            <p>明日验证填写窗口：{windows[result.journal.state]}</p>
            <p className="mt-1">事前涨停家数：{result.journal.prior_metric_available.limit_up_count ? "可读取" : "未知"} · 事前炸板率：{result.journal.prior_metric_available.failed_board_rate ? "可读取" : "未知"}</p>
            {result.journal.next_trade_date && <p className="mt-1">目标交易日 {result.journal.next_trade_date} · 封存时间 {result.journal.seals_at}</p>}
          </div>
          <details className="mt-3 text-xs"><summary className="cursor-pointer">检查边界与后续使用</summary>
            {result.limitations.map(line => <p className="mt-2" key={line}>{line}</p>)}
            <p className="mt-2">检查时间 {result.generated_at}；详细来源请查看相应功能卡</p>
          </details>
        </> : null}
    </section>
  </GlassCard>;
}
