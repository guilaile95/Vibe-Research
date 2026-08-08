// 财报速览：把最新财报 + 前向一致预期 + 估值分位，用「结论先行」的结构收拢成一张速览卡。
// 纯前端计算（数据都已在个股页 state 里）。

import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import type { Valuation, Financials, ValPercentile } from "@/lib/api";

// 从含单位/符号的字符串里取数（"+15.2%" → 15.2；取不到 → null）。
const num = (s: string | number | null | undefined): number | null => {
  if (s == null) return null;
  const n = parseFloat(String(s).replace(/[^0-9.\-]/g, ""));
  return Number.isNaN(n) ? null : n;
};

// A股红涨绿跌：正=红 负=绿。
const yoyColor = (s: string | null | undefined) => {
  const n = num(s);
  return n == null ? "text-muted-foreground" : n > 0 ? "text-danger" : n < 0 ? "text-success" : "text-muted-foreground";
};

interface Props {
  val: Valuation;
  fin: Financials | null;
  pctl: ValPercentile | null;
}

export function EarningsSnapshot({ val, fin, pctl }: Props) {
  if (!fin || (!fin.revenue && !fin.net_profit)) return null;

  const revYoy = num(fin.revenue_yoy);
  const npYoy = num(fin.net_profit_yoy);
  const roe = num(fin.roe);
  const pePctile = pctl?.metrics.pe_ttm?.percentile ?? null;

  const observations: string[] = [];
  if (revYoy != null) observations.push(`营收${revYoy >= 30 ? "高增长" : revYoy >= 0 ? "正增长" : "下滑"}`);
  if (revYoy != null && npYoy != null) observations.push(npYoy >= revYoy ? "利润增速快于营收" : "利润增速慢于营收");
  if (roe != null) observations.push(`${roe >= 15 ? "高" : roe >= 8 ? "中" : "偏低"} ROE ${roe}%`);
  if (pePctile != null) observations.push(`PE ${pePctile < 30 ? "低" : pePctile <= 70 ? "中" : "高"}分位 ${Math.round(pePctile)}%`);
  if (val.peg != null) observations.push(`PEG ${val.peg}`);

  const forward: string[] = [];
  if (val.eps_26e != null) forward.push(`26E EPS ${val.eps_26e}`);
  if (val.pe_26e != null) forward.push(`前向 PE ${val.pe_26e}`);
  if (val.digest_years != null && val.digest_years > 0) forward.push(`估值消化 ${val.digest_years} 年`);
  if (val.analyst_count > 0) forward.push(`${val.analyst_count} 家机构覆盖`);

  return (
    <GlassCard className="mb-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border/35 pb-2.5">
        <h3 className="text-sm font-semibold">财报速览</h3>
        {fin.period ? <span className="text-xs text-muted-foreground/65">{fin.period}</span> : null}
      </div>

      <div className="grid grid-cols-2 divide-x divide-border/35 py-3">
        <div className="pr-4">
          <p className="text-xs text-muted-foreground">营业总收入</p>
          <p className="mt-1 font-mono text-lg font-semibold">{fin.revenue ?? "—"}</p>
          {fin.revenue_yoy ? <p className={cn("mt-0.5 text-xs", yoyColor(fin.revenue_yoy))}>同比 {fin.revenue_yoy}</p> : null}
        </div>
        <div className="pl-4">
          <p className="text-xs text-muted-foreground">归母净利润</p>
          <p className="mt-1 font-mono text-lg font-semibold">{fin.net_profit ?? "—"}</p>
          {fin.net_profit_yoy ? <p className={cn("mt-0.5 text-xs", yoyColor(fin.net_profit_yoy))}>同比 {fin.net_profit_yoy}</p> : null}
        </div>
      </div>

      {observations.length > 0 ? (
        <p className="border-t border-border/30 pt-2.5 text-xs leading-5 text-muted-foreground">
          <span className="text-foreground/80">关键观察：</span>{observations.join(" · ")}
        </p>
      ) : null}

      {forward.length > 0 ? (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          <span className="text-foreground/80">前向预期：</span>{forward.join(" · ")}
        </p>
      ) : null}
    </GlassCard>
  );
}
