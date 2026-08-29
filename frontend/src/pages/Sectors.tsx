import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ChevronRight, Flame, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectorHeatmap } from "@/components/sectors/SectorHeatmap";
import sectorsData from "@/data/sectors.json";
import { api, type BoardRankingData, type SectorMarketContextData, type TimedComponentEnvelope } from "@/lib/api";
import { formatActivity, formatSectorPercent, mappedSectorRows } from "@/lib/sectorMarketView";
import { cn } from "@/lib/utils";
import {
  getDefaultResearchPath,
  hasSectorResearchWorkspace,
} from "@/data/sectorResearch";
import { getSectorTagCount } from "@/data/sectorResearch/sectorTagPlans";

type SectorRow = (typeof sectorsData.sectors)[number] & {
  researchWorkspace?: boolean;
};

export function Sectors() {
  const sectors = sectorsData.sectors as SectorRow[];
  const hotCount = sectors.filter((s) => s.hot).length;
  const [marketContext, setMarketContext] = useState<SectorMarketContextData | null>(null);
  const [industryBoards, setIndustryBoards] = useState<TimedComponentEnvelope<BoardRankingData> | null>(null);
  const [loading, setLoading] = useState(true);
  const [contextError, setContextError] = useState(false);
  const [boardsError, setBoardsError] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.allSettled([api.getSectorMarketContext(), api.marketBoards("industry", 8)])
      .then(([contextResult, boardsResult]) => {
        if (!alive) return;
        if (contextResult.status === "fulfilled") setMarketContext(contextResult.value);
        else setContextError(true);
        if (boardsResult.status === "fulfilled") setIndustryBoards(boardsResult.value);
        else setBoardsError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  const mappedRows = mappedSectorRows(marketContext?.items ?? []);
  const mappingByKey = new Map((marketContext?.items ?? []).map((item) => [item.sector_key, item]));

  const valueClass = (value: number | null | undefined) => cn(
    value == null && "text-muted-foreground",
    value != null && value > 0 && "text-rose-600 dark:text-rose-400",
    value != null && value < 0 && "text-emerald-600 dark:text-emerald-400",
  );

  return (
    <div>
      <PageHeader
        title="板块中心"
        subtitle={`${sectors.length} 个研究赛道 · 市场观察与产业研究在同一路径`}
      />

      <SectorHeatmap />

      <GlassCard className="mb-5 p-4 sm:p-5" data-sector-strength-matrix>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-1.5 text-sm font-semibold"><Activity className="h-4 w-4" /> 板块强度</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">当日全行业横截面 + 显式映射赛道的 5/20/60 日指数趋势</p>
          </div>
          {marketContext && (
            <span className="text-[11px] text-muted-foreground">映射 {marketContext.mapped_count}/{marketContext.total_count}</span>
          )}
        </div>

        {loading && (
          <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载市场观察…</div>
        )}

        {!loading && (
          <div className="mt-4 space-y-5">
            <section>
              <h3 className="mb-2 text-xs font-medium text-muted-foreground">今日行业横截面</h3>
              {industryBoards?.data?.top?.length ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  {industryBoards.data.top.slice(0, 8).map((board, index) => (
                    <div key={board.code} className="rounded-lg border border-border/50 bg-muted/15 px-2.5 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">{index + 1}. {board.name}</span>
                        <span className={cn("font-semibold", valueClass(board.change_pct))}>{formatSectorPercent(board.change_pct)}</span>
                      </div>
                      <p className="mt-1 truncate text-[10px] text-muted-foreground">
                        宽度 {board.up_count ?? "—"}↑ / {board.down_count ?? "—"}↓ · 换手 {board.turnover_pct == null ? "—" : `${board.turnover_pct.toFixed(2)}%`} · 领涨 {board.leader ?? "—"}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{boardsError ? "今日行业横截面暂不可用。" : "当前无可用行业排名。"}</p>
              )}
            </section>

            <section>
              <h3 className="mb-2 text-xs font-medium text-muted-foreground">Vibe 赛道多周期观察</h3>
              {mappedRows.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border border-border/50">
                  <table className="w-full min-w-[820px] text-left text-xs">
                    <thead className="bg-muted/25 text-[10px] text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2">20日排名</th><th className="px-3 py-2">赛道 / 指数</th>
                        <th className="px-3 py-2">5日</th><th className="px-3 py-2">20日</th><th className="px-3 py-2">60日</th>
                        <th className="px-3 py-2">5日动能变化</th><th className="px-3 py-2">成交活跃度</th><th className="px-3 py-2">排名变化</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {mappedRows.map((row) => {
                        const href = getDefaultResearchPath(row.sector_key) ?? `/sectors/${row.sector_key}`;
                        const metrics = row.metrics;
                        return (
                          <tr key={row.sector_key} className="hover:bg-muted/15">
                            <td className="px-3 py-2 font-medium">{row.rank_20d_within_mapped ?? "—"} / {row.rank_universe_count ?? "—"}</td>
                            <td className="px-3 py-2"><Link className="font-medium text-primary hover:underline" to={href}>{row.sector_label}</Link><p className="text-[10px] text-muted-foreground">{row.index?.name} · {row.index?.thscode}</p></td>
                            {[metrics?.return_5d_pct, metrics?.return_20d_pct, metrics?.return_60d_pct, metrics?.return_5d_delta_vs_previous_5d_pct].map((value, index) => (
                              <td key={index} className={cn("px-3 py-2 font-medium", valueClass(value))}>{formatSectorPercent(value)}</td>
                            ))}
                            <td className="px-3 py-2">{formatActivity(metrics?.turnover_vs_prior_20d)}</td>
                            <td className="px-3 py-2">{row.rank_change_vs_5_sessions_ago == null ? "—" : row.rank_change_vs_5_sessions_ago > 0 ? `↑${row.rank_change_vs_5_sessions_ago}` : row.rank_change_vs_5_sessions_ago < 0 ? `↓${Math.abs(row.rank_change_vs_5_sessions_ago)}` : "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{contextError ? "多周期指数观察暂不可用，研究入口仍可使用。" : "当前无可用显式映射。"}</p>
              )}
            </section>

            <p className="text-[10px] leading-relaxed text-muted-foreground">
              20日排名仅覆盖本页显式映射的 Vibe 赛道；排名变化比较当前与5个交易日前的20日排名。未映射主题不按名称猜测。成交活跃度未做盘中时段归一；进入赛道后再读取当前成分与上涨宽度。
            </p>
          </div>
        )}
      </GlassCard>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sectors.map((s) => {
          const workspace = hasSectorResearchWorkspace(s.key) || s.researchWorkspace;
          const tagCount = getSectorTagCount(s.key);
          const market = mappingByKey.get(s.key);

          // 链接：完整研究工作台 → 默认 Tag；仅有 Tag 规划 → 通用详情；否则通用详情
          const href = workspace
            ? getDefaultResearchPath(s.key) ?? `/sectors/${s.key}`
            : `/sectors/${s.key}`;

          // 区分：仅有 Tag 规划（未落地）≠ 已有真实内容。避免"已规划 6 个栏目"误导用户以为有内容。
          let footer: string;
          if (workspace) {
            footer = `${tagCount} 个研究栏目`;
          } else if (tagCount > 0) {
            footer = `已规划 ${tagCount} 个栏目`;
          } else if (s.verified) {
            footer = `${s.nodes.length} 个环节`;
          } else {
            footer = "环节梳理中";
          }

          return (
            <Link key={s.key} to={href}>
              <GlassCard glow={s.hot} className="flex h-full flex-col justify-between">
                <div>
                  <div className="mb-1 flex items-center gap-2">
                    <h3 className="text-base font-bold">{s.label}</h3>
                    {s.hot && (
                      <span className="inline-flex items-center gap-0.5 rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                        <Flame className="h-3 w-3" /> 研究重点
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground">{s.tagline}</p>
                </div>
                <div className="mt-3 flex items-center justify-between border-t border-border/50 pt-3 text-xs">
                  <span className="text-muted-foreground">{footer} · {market?.mapping_status === "mapped" ? "市场映射已核验" : "市场映射待确认"}</span>
                  <ChevronRight className="h-4 w-4 text-primary" />
                </div>
              </GlassCard>
            </Link>
          );
        })}
      </div>

      <p className="mt-4 text-center text-xs text-muted-foreground/60">
        共 {sectors.length} 个板块，其中 {hotCount} 个研究重点 · 实时强弱不使用静态火焰标签
      </p>
    </div>
  );
}
