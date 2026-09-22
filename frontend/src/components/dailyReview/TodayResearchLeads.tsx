import { BarChart3, Flame, Layers } from "lucide-react";
import { Link } from "react-router-dom";
import type { DailyReviewData } from "@/lib/api";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";

const pct = (value: number | null | undefined) => value == null ? "—" : `${value > 0 ? "+" : ""}${value}%`;
const count = (value: number | null | undefined) => value == null ? "—" : String(value);
const sourceState = (status: string | undefined, loading: boolean) => loading ? "读取中" : ({ normal: "", partial: "数据不完整", stale: "历史数据，需核对日期", unavailable: "数据暂不可用", error: "读取失败" })[status ?? ""] ?? "来源状态未知";

/** A small set of descriptive facts from the existing review, never a new score or ranking. */
export function TodayResearchLeads({ review, loading, onOpenDetail }: {
  review: DailyReviewData | null;
  loading: boolean;
  onOpenDetail: (id: string) => void;
}) {
  const industry = review?.sector_rotation?.highlights?.strongest_industry;
  const weakest = review?.sector_rotation?.highlights?.weakest_industry;
  const active = review?.capital_activity?.amount_top?.[0];
  const emotion = review?.short_term_emotion?.data;
  const candidateCode = active && /^\d{6}$/.test(active.code) ? active.code : null;
  const leads = [
    {
      label: "行业表现", icon: Layers,
      fact: industry ? `${industry.name} · ${pct(industry.change_pct)} · 行业涨幅排名居前` : loading ? "正在读取行业排名…" : "行业排名暂不可用",
      hint: weakest ? `排名靠后：${weakest.name} ${pct(weakest.change_pct)}；继续查看板块内部分化。` : "进入板块研究，核对行业内个股表现与研究依据。",
      status: review?.sector_rotation?.industry?.status, href: "/sectors", action: "板块研究",
    },
    {
      label: "成交活跃", icon: BarChart3,
      fact: active ? `${active.name} · 成交额 ${active.amount == null ? "—" : `${(active.amount / 1e8).toFixed(2)} 亿`} · 成交榜首位` : loading ? "正在读取成交额榜…" : "成交额榜暂不可用",
      hint: active ? `涨跌幅 ${pct(active.change_pct)}；结合公告与基本面核对成交活跃的原因。` : "数据恢复后显示榜单事实；可先查看已有研究候选。",
      status: review?.data_health?.components?.turnover,
      href: candidateCode ? candidateWorkspaceHref(candidateCode) : "/screener", action: candidateCode ? "候选研究" : "市场发现",
    },
    {
      label: "短线情绪", icon: Flame,
      fact: emotion ? `涨停 ${count(emotion.zt_count)} 家 · 跌停 ${count(emotion.dt_count)} 家 · 最高 ${count(emotion.max_boards)} 板` : loading ? "正在读取短线情绪…" : "短线情绪暂不可用",
      hint: emotion?.date ? `数据日期 ${emotion.date}；查看连板分布与封板情况。` : "查看连板分布与封板情况；缺失指标不代表零。",
      status: review?.short_term_emotion?.status, href: null, action: "查看情绪详情",
    },
  ];
  return (
    <section aria-labelledby="research-leads-title" className="mb-6" data-testid="today-research-leads">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 id="research-leads-title" className="text-lg font-semibold">值得继续研究</h2>
        <Link to="/screener" className="text-xs text-primary hover:underline">打开市场发现 →</Link>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">从当日榜单和市场情绪出发，继续核对成因与持续性。</p>
      <div className="divide-y divide-border/60 rounded-xl border border-border/60 bg-card/40">
        {leads.map((lead) => (
          <div key={lead.label} className="grid gap-2 p-4 sm:grid-cols-[7rem_minmax(0,1fr)_auto] sm:items-center">
            <span className="flex items-center gap-2 text-sm font-medium"><lead.icon className="h-4 w-4 text-muted-foreground" />{lead.label}</span>
            <div className="min-w-0">
              <p className="text-sm font-medium">{lead.fact}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{lead.hint}</p>
              {sourceState(lead.status, loading) && <p className="mt-1 text-xs text-warning">{sourceState(lead.status, loading)}</p>}
            </div>
            {lead.href ? <Link to={lead.href} className="text-xs text-primary hover:underline">{lead.action} →</Link> : <button type="button" onClick={() => onOpenDetail("emotion")} className="text-left text-xs text-primary hover:underline">{lead.action} ↓</button>}
          </div>
        ))}
      </div>
    </section>
  );
}
