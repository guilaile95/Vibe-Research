import { useMemo, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
          if (d.node_type === "industry") {
            return `<div style="font-weight:600;margin-bottom:4px">${d.name}</div>` +
              `<div>股票数：${d.stock_count ?? "—"}</div>` +
              `<div>平均涨跌：${formatChangePct(d.change_pct)}</div>` +
              `<div>流通市值：${formatMarketCap(d.value)}</div>` +
              `<div>上涨：${d.up_count ?? "—"} / 下跌：${d.down_count ?? "—"}</div>`;
          }
          return `<div style="font-weight:600;margin-bottom:4px">${d.name} (${d.code ?? "—"})</div>` +
            `<div>涨跌幅：${formatChangePct(d.change_pct)}</div>` +
            `<div>最新价：${formatPrice(d.price)}</div>` +
            `<div>流通市值：${formatMarketCap(d.value)}</div>` +
            `<div>成交额：${formatAmount(d.amount)}</div>` +
            `<div>所属行业：${d.industry ?? "—"}</div>`;
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
      const p = params as { data?: TreemapNode };
      const d = p.data;
      if (!d || d.node_type !== "stock" || !d.code) return;
      navigate(`/stock-data?code=${d.code}`);
    },
    [navigate],
  );

  // ── 状态渲染 ──────────────────────────────────────────────────────

  const status = data?.status;
  const warnings = data?.warnings ?? [];

  return (
    <div data-market-cloud style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#e4e4e7" }}>市场热力</h3>
          {status === "partial" && (
            <span style={{ fontSize: 11, color: "#fbbf24", background: "rgba(251,191,36,0.1)", padding: "2px 8px", borderRadius: 4 }}>
              部分数据缺失
            </span>
          )}
          {status === "stale" && (
            <span style={{ fontSize: 11, color: "#fb923c", background: "rgba(251,146,60,0.1)", padding: "2px 8px", borderRadius: 4 }}>
              数据过期
            </span>
          )}
          {data?.fetched_at && (
            <span style={{ fontSize: 11, color: "#71717a" }}>更新于 {data.fetched_at.slice(11, 16)}</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 4 }}>
            {SCOPE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setScope(opt.value)}
                style={{
                  padding: "4px 12px",
                  fontSize: 12,
                  borderRadius: 4,
                  border: "1px solid #3f3f46",
                  background: scope === opt.value ? "#3f3f46" : "transparent",
                  color: scope === opt.value ? "#fafafa" : "#a1a1aa",
                  cursor: "pointer",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                style={{
                  padding: "4px 12px",
                  fontSize: 12,
                  borderRadius: 4,
                  border: "1px solid #3f3f46",
                  background: "#3f3f46",
                  color: "#fafafa",
                  cursor: "default",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && (
        <div style={{ height: 500, display: "flex", alignItems: "center", justifyContent: "center", color: "#71717a", fontSize: 13, background: "#18181b", borderRadius: 8 }}>
          加载市场热力（全 A 股快照，首次约 30-60 秒）…
        </div>
      )}

      {!loading && error && (
        <div style={{ height: 500, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, background: "#18181b", borderRadius: 8 }}>
          <div style={{ color: "#f87171", fontSize: 14 }}>数据暂不可用</div>
          <div style={{ color: "#71717a", fontSize: 12 }}>{error}</div>
          <button onClick={reload} style={{ padding: "6px 16px", fontSize: 12, borderRadius: 4, border: "1px solid #3f3f46", background: "transparent", color: "#a1a1aa", cursor: "pointer" }}>
            重试
          </button>
        </div>
      )}

      {!loading && !error && status === "unavailable" && (
        <div style={{ height: 500, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, background: "#18181b", borderRadius: 8 }}>
          <div style={{ color: "#f87171", fontSize: 14 }}>数据暂不可用</div>
          {warnings.length > 0 && <div style={{ color: "#71717a", fontSize: 12 }}>{warnings[0]}</div>}
          <button onClick={reload} style={{ padding: "6px 16px", fontSize: 12, borderRadius: 4, border: "1px solid #3f3f46", background: "transparent", color: "#a1a1aa", cursor: "pointer" }}>
            重试
          </button>
        </div>
      )}

      {!loading && !error && data?.data && (status === "normal" || status === "partial" || status === "stale") && (
        <>
          <EChart option={option} height={520} onClick={handleClick} />
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: "#71717a", flexWrap: "wrap", gap: 8 }}>
            <span>矩形面积 = 流通市值 · 颜色 = 当日涨跌幅（红涨绿跌） · 点击行业聚焦 · 点击个股进入研究 · 滚轮缩放 / 拖拽平移</span>
            <span>{data.data.valid_count}/{data.data.stock_count} 只有效数据 · {data.data.industry_count} 个行业</span>
          </div>
          {warnings.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#fbbf24" }}>
              {warnings.join("；")}
            </div>
          )}
        </>
      )}
    </div>
  );
}
