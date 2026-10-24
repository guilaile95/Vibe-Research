import { useEffect, useState } from "react";
import { get } from "@/lib/api";

interface Coverage { status: string; supported_end: string; days_until_coverage_end: number }
export function CalendarCoverageCard({ refresh }: { refresh: number }) {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setCoverage(null); setUnavailable(false);
    const timer = setTimeout(() => controller.abort(), 5000);
    void get<Record<string, unknown>>("/calendar-status", { signal: controller.signal }).then((value) => {
      if (!current || controller.signal.aborted) return;
      if (!value || !["SUPPORTED", "EXPIRING", "EXPIRED", "OUT_OF_RANGE", "INVALID_ARTIFACT"].includes(String(value.status))
          || typeof value.supported_end !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.supported_end)
          || typeof value.days_until_coverage_end !== "number" || !Number.isSafeInteger(value.days_until_coverage_end)
          || value.future_dates_inferred !== false) throw new Error("Invalid calendar status");
      setCoverage({ status: String(value.status), supported_end: value.supported_end, days_until_coverage_end: value.days_until_coverage_end });
    }).catch(() => { if (current) setUnavailable(true); }).finally(() => clearTimeout(timer));
    return () => { current = false; clearTimeout(timer); controller.abort(); };
  }, [refresh]);
  return <div className="mt-3 border-t border-border/50 pt-3 text-xs" data-testid="calendar-coverage-status">
    <p className="font-medium">交易日历覆盖</p>
    <p className="mt-1" role="status">{coverage
      ? `${coverage.status === "SUPPORTED" ? "已确认范围" : coverage.status === "EXPIRING" ? "覆盖即将到期" : coverage.status === "EXPIRED" ? "覆盖已到期" : "当前范围不可验证"}：截至 ${coverage.supported_end}`
      : unavailable ? "日历状态未取得，不能据此确认未来交易日" : "正在核对日历覆盖…"}</p>
    <p className="mt-1 text-muted-foreground">范围外日期保持未知；下一年度需核对沪深交易所官方公告，不按工作日推算。</p>
  </div>;
}
