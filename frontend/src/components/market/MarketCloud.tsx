import { useMemo, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EChart } from "@/components/ui/EChart";
import { useMarketCloud, type MarketCloudScope, type MarketCloudPeriod } from "@/hooks/useMarketCloud";
import {
  marketCloudToTreemap,
  formatMarketCap,
  formatAmount,
  formatChangePct,
  formatPrice,
  type TreemapNode,
} from "@/lib/marketCloud";
import { cn } from "@/lib/utils";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";

const SCOPE_OPTIONS: { value: MarketCloudScope; label: string }[] = [
  { value: "all", label: "全A" },
  { value: "cyb", label: "创业板" },
  { value: "star", label: "科创板" },
  { value: "sh", label: "上证" },
  { value: "sz", label: "深证" },
];

const PERIOD_OPTIONS: { value: MarketCloudPeriod; label: string }[] = [
  { value: "today", label: "今日" },
];

export function MarketCloud() {
  const navigate = useNavigate();
  const [scope, setScope] = useState<MarketCloudScope>("all");
  const [period] = useState<MarketCloudPeriod>("today");
  const [candidateCodeDraft, setCandidateCodeDraft] = useState("");
  const { data, loading, error, reload } = useMarketCloud({ scope, period });

  const treemapData = useMemo(() => {
    if (!data?.data) return [];
    return marketCloudToTreemap(data.data);
  }, [data]);

  const option = useMemo(() => {
    return {
      tooltip: {
        confine: true,
        backgroundColor: "rgba(24, 24, 27, 0.95)",
        borderColor: "#3f3f46",
        borderWidth: 1,
        textStyle: { color: "#e4e4e7", fontSize: 12 },
        formatter: (params: { data?: TreemapNode; name?: string; value?: number }) => {
          const d = params.data;
          if (!d) return "";
          const fetched = data?.fetched_at ? `<div style="margin-top:4px;color:#71717a;font-size:11px">数据更新：${data.fetched_at}</div>` : "";
          if (d.node_type === "industry") {
            return `<div style="font-weight:600;margin-bottom:4px">${d.name}</div>` +
              `<div>股票数：${d.stock_count ?? "—"}</div>` +
              `<div>平均涨跌：${formatChangePct(d.change_pct)}</div>` +
              `<div>流通市值：${formatMarketCap(d.value)}</div>` +
              `<div>上涨：${d.up_count ?? "—"} / 下跌：${d.down_count ?? "—"}</div>` +
              fetched;
          }
          return `<div style="font-weight:600;margin-bottom:4px">${d.name} (${d.code ?? "—"})</div>` +
            `<div>涨跌幅：${formatChangePct(d.change_pct)}</div>` +
            `<div>最新价：${formatPrice(d.price)}</div>` +
            `<div>流通市值：${formatMarketCap(d.value)}</div>` +
            `<div>成交额：${formatAmount(d.amount)}</div>` +
            `<div>所属行业：${d.industry ?? "—"}</div>` +
            `<div style="margin-top:4px;color:#a1a1aa;font-size:11px">单击：个股数据 · Shift + 单击：候选研究</div>` +
            fetched;
        },
      },
      series: [
        {
          type: "treemap",
          data: treemapData,
          roam: true,
          nodeClick: "zoomToNode",
          breadcrumb: {
            show: true,
            top: 0,
            itemStyle: {
              color: "rgba(63, 63, 70, 0.6)",
              borderColor: "#52525b",
            },
            textStyle: { color: "#a1a1aa", fontSize: 11 },
          },
          label: {
            show: true,
            formatter: (params: { data?: TreemapNode; name?: string }) => {
              const d = params.data;
              if (!d) return params.name ?? "";
              if (d.node_type === "industry") return d.name;
              const pct = d.change_pct;
              if (pct === null || pct === undefined) return d.name;
              const sign = pct > 0 ? "+" : "";
              return `${d.name}\n${sign}${pct.toFixed(2)}%`;
            },
            color: "#fafafa",
            fontSize: 11,
            overflow: "truncate",
          },
          upperLabel: {
            show: true,
            height: 24,
            color: "#e4e4e7",
            fontSize: 12,
            fontWeight: 600,
          },
          levels: [
            {
              // 行业层级
              itemStyle: {
                borderColor: "#18181b",
                borderWidth: 2,
                gapWidth: 2,
              },
              upperLabel: { show: true },
            },
            {
              // 个股层级
              itemStyle: {
                borderColor: "#18181b",
                borderWidth: 1,
                gapWidth: 1,
              },
              colorSaturation: [0.35, 0.7],
            },
          ],
        },
      ],
    };
  }, [treemapData]);

  const handleClick = useCallback(
    (params: unknown) => {
      const p = params as { data?: TreemapNode; event?: { event?: { shiftKey?: boolean } } };
      const d = p.data;
      if (!d || d.node_type !== "stock" || !d.code) return;
      navigate(p.event?.event?.shiftKey ? candidateWorkspaceHref(d.code) : `/stock-data?code=${d.code}`);
    },
    [navigate],
  );

  // ── 状态渲染 ──────────────────────────────────────────────────────

  const status = data?.status;
  const warnings = data?.warnings ?? [];

  const chartHeight = "clamp(560px, 68vh, 700px)";

  return (
    <section data-market-cloud aria-labelledby="market-cloud-title" className="mb-10">
      <header className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="market-cloud-title" className="text-lg font-semibold text-foreground">A股市场热力</h2>
            {status === "partial" && (
              <span className="rounded-md bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">部分数据缺失</span>
            )}
            {status === "stale" && (
              <span className="rounded-md bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">数据已过期</span>
            )}
            {data?.fetched_at && (
              <span className="text-[11px] text-muted-foreground">更新于 {data.fetched_at.slice(11, 16)}</span>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">一眼查看全市场结构；面积代表流通市值，红涨绿跌。</p>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <div className="flex items-center gap-1 rounded-lg border border-primary/30 bg-card/70 p-1 shadow-sm">
            <input
              aria-label="候选研究代码"
              inputMode="numeric"
              value={candidateCodeDraft}
              onChange={(event) => setCandidateCodeDraft(event.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="6 位代码"
              className="w-24 rounded bg-background/70 px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-primary/50"
            />
            {/^[0-9]{6}$/.test(candidateCodeDraft) ? (
              <Link
                to={candidateWorkspaceHref(candidateCodeDraft)}
                className="rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground"
                data-testid="market-cloud-candidate-entry"
              >
                候选研究
              </Link>
            ) : (
              <span className="rounded-md px-2.5 py-1.5 text-xs text-muted-foreground" aria-disabled="true">候选研究</span>
            )}
          </div>
          <div role="toolbar" aria-label="市场热力范围" className="flex flex-wrap items-center gap-1 rounded-lg border border-border/70 bg-card/70 p-1 shadow-sm">
            {SCOPE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                aria-pressed={scope === opt.value}
                data-testid={`market-cloud-scope-${opt.value}`}
                onClick={() => setScope(opt.value)}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-xs transition-colors",
                  scope === opt.value
                    ? "bg-foreground font-medium text-background"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {opt.label}
              </button>
            ))}
            <span aria-hidden="true" className="mx-1 h-5 w-px bg-border" />
            {PERIOD_OPTIONS.map((opt) => (
              <span key={opt.value} className="rounded-md bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary">
                {opt.label}
              </span>
            ))}
          </div>
        </div>
      </header>

      {loading && (
        <div
          data-testid="market-cloud-loading"
          style={{ height: chartHeight }}
          className="flex items-center justify-center rounded-xl border border-border/60 bg-muted/20 text-sm text-muted-foreground"
        >
          正在加载全 A 股市场快照…
        </div>
      )}

      {!loading && error && (
        <div style={{ height: chartHeight }} className="flex flex-col items-center justify-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5">
          <p className="text-sm font-medium text-destructive">市场快照暂不可用</p>
          <p className="max-w-xl text-center text-xs text-muted-foreground">{error}</p>
          <button type="button" onClick={reload} className="rounded-md border border-border px-3 py-1.5 text-xs text-foreground hover:bg-muted">
            重试
          </button>
        </div>
      )}

      {!loading && !error && status === "unavailable" && (
        <div style={{ height: chartHeight }} className="flex flex-col items-center justify-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5">
          <p className="text-sm font-medium text-destructive">市场快照暂不可用</p>
          {warnings.length > 0 && <p className="max-w-xl text-center text-xs text-muted-foreground">{warnings[0]}</p>}
          <button type="button" onClick={reload} className="rounded-md border border-border px-3 py-1.5 text-xs text-foreground hover:bg-muted">
            重试
          </button>
        </div>
      )}

      {!loading && !error && data?.data && (status === "normal" || status === "partial" || status === "stale") && (
        <>
          <div data-market-cloud-chart className="overflow-hidden rounded-xl border border-zinc-700/80 bg-zinc-950 shadow-sm">
            <EChart option={option} height={chartHeight} onClick={handleClick} />
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span>点击行业聚焦 · 单击个股进入数据 · Shift + 单击个股进入候选研究 · 滚轮缩放 / 拖拽平移</span>
            <span>{data.data.valid_count}/{data.data.stock_count} 只有效数据 · {data.data.industry_count} 个行业</span>
          </div>
          {warnings.length > 0 && (
            <p className="mt-1.5 text-[11px] text-warning">{warnings.join("；")}</p>
          )}
        </>
      )}
    </section>
  );
}
