// A 股板块热力图 V1。
//
// - 矩形面积 = 板块真实成交额（amount）；
// - 颜色 = 板块当日涨跌幅（红涨绿跌，接近 0 中性灰）；
// - 行业 / 概念切换，复用 api.marketBoards；
// - fail-closed：loading / normal / partial / stale / unavailable 显式表达；
// - 点击板块进入 Vibe 已有 Sector / Sector Research（携带真实 identifier）；
// - 概念板块过多时按成交额聚合"其他 N 个"（纯 UI 聚合，非真实板块）。

import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { EChart } from "@/components/ui/EChart";
import { GlassCard } from "@/components/ui/GlassCard";
import { useSectorHeatmap, type HeatmapBoardType } from "@/hooks/useSectorHeatmap";
import { formatHeatmapTooltip, type HeatmapItem } from "@/lib/sectorHeatmap";
import { formatSectorPercent } from "@/lib/sectorMarketView";
import sectorsData from "@/data/sectors.json";
import { getDefaultResearchPath, hasSectorResearchWorkspace } from "@/data/sectorResearch";
import { cn } from "@/lib/utils";

// 从 Vibe sectors.json 构建名称 → key 的映射（用于点击跳转时的最佳匹配）
const vibeSectorMap = new Map<string, string>();
for (const s of sectorsData.sectors) {
  vibeSectorMap.set(s.label, s.key);
}

function resolveVibeSectorKey(boardName: string): string | null {
  // 精确匹配
  if (vibeSectorMap.has(boardName)) return vibeSectorMap.get(boardName)!;
  // 包含匹配（东财名称可能比 Vibe 标签短，如"半导体" vs "半导体国产替代"）
  for (const [label, key] of vibeSectorMap) {
    if (label.includes(boardName) || boardName.includes(label)) return key;
  }
  return null;
}

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  stale: { label: "数据过期", className: "text-amber-500 border-amber-500/30 bg-amber-500/10" },
  partial: { label: "部分数据缺失", className: "text-yellow-500 border-yellow-500/30 bg-yellow-500/10" },
  unavailable: { label: "数据不可用", className: "text-red-500 border-red-500/30 bg-red-500/10" },
};

export function SectorHeatmap() {
  const navigate = useNavigate();
  const { state, boardType, setBoardType, refresh } = useSectorHeatmap("industry");

  const treemapOption = useMemo(() => {
    if (state.status === "loading" || state.status === "unavailable" || state.items.length === 0) {
      return {};
    }
    return {
      tooltip: {
        trigger: "item",
        formatter: (params: { data?: HeatmapItem }) => {
          if (!params.data) return "";
          return formatHeatmapTooltip(params.data);
        },
        backgroundColor: "rgba(24, 24, 27, 0.95)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e4e4e7", fontSize: 12 },
        extraCssText: "border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.4);",
      },
      series: [
        {
          type: "treemap",
          data: state.items,
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          animationDurationUpdate: 300,
          label: {
            show: true,
            position: "inside",
            formatter: (params: { data?: HeatmapItem; name?: string }) => {
              const d = params.data;
              if (!d) return params.name ?? "";
              const pct = formatSectorPercent(d.data.change_pct);
              return `{name|${d.name}}\n{pct|${pct}}`;
            },
            rich: {
              name: { fontSize: 12, fontWeight: 600, color: "#fff", lineHeight: 16 },
              pct: { fontSize: 11, color: "rgba(255,255,255,0.85)", lineHeight: 14 },
            },
            overflow: "truncate",
          },
          upperLabel: { show: false },
          itemStyle: {
            borderColor: "rgba(0,0,0,0.3)",
            borderWidth: 1,
            gapWidth: 1,
          },
          levels: [
            {
              itemStyle: { borderColor: "rgba(0,0,0,0.3)", borderWidth: 1, gapWidth: 1 },
            },
          ],
        },
      ],
    };
  }, [state.items, state.status]);

  const handleChartClick = (params: unknown) => {
    const p = params as { data?: HeatmapItem };
    const item = p?.data;
    if (!item || item.data.isAggregate) return;
    const boardCode = item.data.code;
    const boardName = item.data.name;
    const vibeKey = resolveVibeSectorKey(boardName);
    if (vibeKey && hasSectorResearchWorkspace(vibeKey)) {
      const path = getDefaultResearchPath(vibeKey);
      if (path) {
        navigate(path);
        return;
      }
    }
    if (vibeKey) {
      navigate(`/sectors/${vibeKey}`);
      return;
    }
    // 未匹配到 Vibe 赛道：携带东财真实板块 code 进入通用详情
    navigate(`/sectors/${boardCode}`);
  };

  const toggleType = (t: HeatmapBoardType) => {
    if (t !== boardType) setBoardType(t);
  };

  return (
    <GlassCard className="mb-5 p-4 sm:p-5" data-sector-heatmap>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">板块热力</h2>
          {state.status !== "loading" && state.status !== "normal" && STATUS_BADGE[state.status] && (
            <span className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
              STATUS_BADGE[state.status].className,
            )}>
              <AlertTriangle className="h-3 w-3" />
              {STATUS_BADGE[state.status].label}
            </span>
          )}
          {state.status !== "loading" && state.updatedAt && (
            <span className="text-[10px] text-muted-foreground">
              更新于 {new Date(state.updatedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-border/50 bg-muted/20 p-0.5">
            <button
              type="button"
              onClick={() => toggleType("industry")}
              className={cn(
                "rounded px-3 py-1 text-xs font-medium transition-colors",
                boardType === "industry"
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              行业
            </button>
            <button
              type="button"
              onClick={() => toggleType("concept")}
              className={cn(
                "rounded px-3 py-1 text-xs font-medium transition-colors",
                boardType === "concept"
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              概念
            </button>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted/30 hover:text-foreground"
            title="刷新"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", state.status === "loading" && "animate-spin")} />
          </button>
        </div>
      </div>

      {state.status === "loading" && (
        <div className="flex h-[400px] items-center justify-center text-xs text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载板块热力…
        </div>
      )}

      {state.status === "unavailable" && (
        <div className="flex h-[400px] flex-col items-center justify-center gap-2 text-center">
          <AlertTriangle className="h-6 w-6 text-red-500/60" />
          <p className="text-xs text-muted-foreground">
            {state.warnings[0] ?? "板块热力数据暂不可用"}
          </p>
          <button
            type="button"
            onClick={refresh}
            className="mt-1 rounded-md border border-border/50 px-3 py-1 text-xs text-muted-foreground hover:bg-muted/20 hover:text-foreground"
          >
            重试
          </button>
        </div>
      )}

      {state.status !== "loading" && state.status !== "unavailable" && state.items.length > 0 && (
        <EChart
          option={treemapOption}
          height={400}
          onClick={handleChartClick}
        />
      )}

      <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground/70">
        <span>
          矩形面积 = 板块成交额 · 颜色 = 当日涨跌幅（红涨绿跌）
          {state.aggregateCount > 0 && ` · 其余 ${state.aggregateCount} 个板块已聚合`}
        </span>
        <span>
          {state.validAmountCount}/{state.totalCount} 个板块有成交额数据
        </span>
      </div>
    </GlassCard>
  );
}
