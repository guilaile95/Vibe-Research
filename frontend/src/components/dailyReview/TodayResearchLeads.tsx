import { BarChart3, Flame, Layers } from "lucide-react";
import { Link } from "react-router-dom";
import type { DailyReviewData } from "@/lib/api";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import { LeadAnalysisButton } from "./LeadAnalysisButton";
import type { LeadKind } from "@/lib/leadAnalysisContext";

const pct = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? "—" : `${value > 0 ? "+" : ""}${value}%`;
const count = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? "—" : String(value);
const sourceState = (status: string | undefined, loading: boolean) => loading ? "读取中" : ({ normal: "", partial: "数据不完整", stale: "历史数据，需核对日期", unavailable: "数据暂不可用", error: "读取失败" })[status ?? ""] ?? "来源状态未知";

/** A small set of descriptive facts from the existing review, never a new score or ranking. */
export function TodayResearchLeads({ review, loading, previousResult = false, onOpenDetail }: {
  review: DailyReviewData | null;
  loading: boolean;
  previousResult?: boolean;
  onOpenDetail: (id: string) => void;
}) {
  const industry = review?.sector_rotation?.highlights?.strongest_industry;
  const weakest = review?.sector_rotation?.highlights?.weakest_industry;
  const active = review?.capital_activity?.amount_top?.[0];
  const emotion = review?.short_term_emotion?.data;
  const industrySource = review?.sector_rotation?.industry;
  const breadthSource = review?.market_environment?.breadth;
  const candidateCode = active && /^\d{6}$/.test(active.code) ? active.code : null;
  const leads = [
    {
      label: "行业表现", icon: Layers,
      kind: "industry" as LeadKind, subject: industry?.code ?? null, canAnalyze: !!industry?.code,
      fact: industry ? `${industry.name} · ${pct(industry.change_pct)} · 行业涨幅排名居前` : loading ? "正在读取行业排名…" : "行业排名暂不可用",
      hint: weakest ? `排名靠后：${weakest.name} ${pct(weakest.change_pct)}；继续查看板块内部分化。` : "进入板块研究，核对行业内个股表现与研究依据。",
      question: "上涨是否集中在少数个股？板块内有哪些共同催化？",
      source: `行业排名 · 行情时间 ${industrySource?.data_time || industrySource?.trade_date || "未提供"}`,
      stale: industrySource?.is_stale,
      status: industrySource?.status, href: "/sectors", action: "板块研究",
    },
    {
      label: "成交活跃", icon: BarChart3,
      kind: "activity" as LeadKind, subject: candidateCode, canAnalyze: !!candidateCode,
      fact: active ? `${active.name} · 成交额 ${active.amount == null || !Number.isFinite(active.amount) ? "—" : `${(active.amount / 1e8).toFixed(2)} 亿元`} · 成交榜首位` : loading ? "正在读取成交额榜…" : "成交额榜暂不可用",
      hint: active ? `涨跌幅 ${pct(active.change_pct)}；结合公告与基本面核对成交活跃的原因。` : "数据恢复后显示榜单事实；可先查看已有研究候选。",
      question: "近期是否有公告或业绩变化？成交活跃是否持续？",
      source: `全 A 快照 · 行情时间 ${breadthSource?.data_time || breadthSource?.trade_date || "未提供"}`,
      stale: breadthSource?.is_stale,
      status: breadthSource?.status ?? review?.data_health?.components?.breadth,
      href: candidateCode ? `${candidateWorkspaceHref(candidateCode)}?${new URLSearchParams({ return_to: "/daily-review#research-leads-title" })}` : "/screener", action: candidateCode ? "候选研究" : "市场发现",
    },
    {
      label: "短线情绪", icon: Flame,
      kind: "emotion" as LeadKind, subject: null, canAnalyze: !!emotion,
      fact: emotion ? `涨停 ${count(emotion.zt_count)} 家 · 跌停 ${count(emotion.dt_count)} 家 · 最高 ${count(emotion.max_boards)} 板` : loading ? "正在读取短线情绪…" : "短线情绪暂不可用",
      hint: emotion?.date ? `数据日期 ${emotion.date}；查看连板分布与封板情况。` : "查看连板分布与封板情况；缺失指标不代表零。",
      question: "涨停是否集中在同一方向？封板和连板数据是否完整？",
      source: `短线情绪 · 数据日期 ${emotion?.date || "未提供"}`,
      stale: false,
      status: review?.short_term_emotion?.status, href: null, action: "查看情绪详情",
    },
  ];
  return (
    <section aria-labelledby="research-leads-title" className="mb-6" data-testid="today-research-leads">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 id="research-leads-title" className="text-lg font-semibold">值得继续研究</h2>
        <Link to="/screener" className="text-xs text-primary hover:underline">打开市场发现 →</Link>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">从已有榜单和市场情绪出发，先核对数据时点，再研究成因与持续性。</p>
      <div className="divide-y divide-border/60 rounded-xl border border-border/60 bg-card/40">
        {leads.map((lead) => (
          <div key={lead.label} data-testid={`today-lead-${lead.label}`} className="grid gap-2 p-4 sm:grid-cols-[7rem_minmax(0,1fr)_auto] sm:items-center">
            <span className="flex items-center gap-2 text-sm font-medium"><lead.icon className="h-4 w-4 text-muted-foreground" />{lead.label}</span>
            <div className="min-w-0">
              <p className="text-sm font-medium">{lead.fact}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{lead.hint}</p>
              <p className="mt-1 text-xs leading-5">下一步核对：{lead.question}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">{lead.source}</p>
              {(previousResult || lead.stale) && <p className="mt-1 text-xs text-warning">上次结果 · 时效待核验</p>}
              {sourceState(lead.status, loading) && <p className="mt-1 text-xs text-warning">{sourceState(lead.status, loading)}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 sm:flex-col sm:items-end">
              {lead.href ? <Link to={lead.href} className="text-xs text-primary hover:underline">{lead.action} →</Link> : <button type="button" onClick={() => onOpenDetail("emotion")} className="text-left text-xs text-primary hover:underline">{lead.action} ↓</button>}
              {lead.canAnalyze && <LeadAnalysisButton key={`${lead.kind}:${lead.subject}`} kind={lead.kind} subject={lead.subject} label={lead.label} />}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
