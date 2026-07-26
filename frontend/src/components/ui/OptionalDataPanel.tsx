import {
  BarChart3,
  Boxes,
  ChevronDown,
  ChevronRight,
  LineChart,
  Loader2,
  Megaphone,
  RefreshCw,
} from "lucide-react";
import type { DisclosureItem, KlineBar } from "@/lib/api";
import { GlassCard } from "./GlassCard";
import { KlineChart } from "./KlineChart";

// ---------------------------------------------------------------------------
// 面板状态机类型
// ---------------------------------------------------------------------------
export type PanelStatus = "idle" | "loading" | "success" | "empty" | "error";

type PanelId = "kline" | "finance" | "info" | "disclosure";

interface PanelState {
  expanded: boolean;
  status: PanelStatus;
  error: string | null;
}

interface Props {
  onToggle: (key: PanelId) => void;
  onRetry: (key: PanelId) => void;
  panelStates: Record<PanelId, PanelState>;
  kline: KlineBar[];
  klineErr: string | null;
  finance: Record<string, string | number | null>;
  financeErr: string | null;
  info: Record<string, string | number>;
  infoErr: string | null;
  disc: DisclosureItem[];
  discErr: string | null;
}

// ---------------------------------------------------------------------------
// 子折叠项
// ---------------------------------------------------------------------------

interface SubToggleProps {
  icon: React.ReactNode;
  title: string;
  hint: string;
  status: PanelStatus;
  expandKey: PanelId;
  expanded: boolean;
  onToggle: (key: PanelId) => void;
  onRetry: (key: PanelId) => void;
  children: React.ReactNode;
}

function SubToggle({ icon, title, hint, status, expandKey, expanded, onToggle, onRetry, children }: SubToggleProps) {
  const statusLabel = () => {
    switch (status) {
      case "loading": return "加载中…";
      case "success": return "已加载";
      case "empty":   return "暂无数据";
      case "error":   return "加载失败";
      default:        return hint;
    }
  };

  return (
    <div className="border-b border-border/40 last:border-0">
      <button
        onClick={() => onToggle(expandKey)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-muted/20"
      >
        {expanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
        {icon}
        <span className="font-medium">{title}</span>
        <span className="ml-auto text-xs text-muted-foreground/60">{statusLabel()}</span>
        {status === "error" && (
          <button
            onClick={(e) => { e.stopPropagation(); onRetry(expandKey); }}
            className="rounded p-1 text-warning hover:bg-warning/10"
            title="重试"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        )}
      </button>
      {expanded && ["success", "empty", "error"].includes(status) && (
        <div className="px-4 pb-3">{children}</div>
      )}
    </div>
  );
}

/**
 * 个股数据「扩展数据」折叠面板：包含 K 线 / 季报财务 / 基本面 / 巨潮公告 四个子项，
 * 均为可选依赖（mootdx / akshare）。每个子项有独立状态机：
 *
 *   idle → loading → success / empty / error
 *
 * - 默认收起，首次展开才发起请求。
 * - 已加载的面板再次展开不会重复请求。
 * - 错误状态可显式重试。
 * - 切换股票时状态由父组件清空。
 */
export function OptionalDataPanel({
  onToggle,
  onRetry,
  panelStates,
  kline,
  klineErr,
  finance,
  financeErr,
  info,
  infoErr,
  disc,
  discErr,
}: Props) {
  const state = (k: PanelId) => panelStates[k]?.status ?? "idle";

  return (
    <GlassCard className="mb-4 divide-y divide-border/40 overflow-hidden !p-0">
      <div className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">
        扩展数据（可选依赖 · 按需加载）
      </div>

      <SubToggle
        icon={<LineChart className="h-4 w-4 text-primary" />}
        title="历史 K 线"
        hint="mootdx"
        status={state("kline")}
        expandKey="kline"
        expanded={!!panelStates.kline?.expanded}
        onToggle={onToggle}
        onRetry={onRetry}
      >
        <PanelContent
          status={state("kline")}
          loadingHint="安装 mootdx 后可用"
          errorMsg={klineErr}
          isEmpty={kline.length === 0}
        >
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground/60">最近 {kline.length} 个交易日 OHLC。</p>
            <KlineChart bars={kline} />
          </div>
        </PanelContent>
      </SubToggle>

      <SubToggle
        icon={<BarChart3 className="h-4 w-4 text-primary" />}
        title="季报财务快照"
        hint="mootdx"
        status={state("finance")}
        expandKey="finance"
        expanded={!!panelStates.finance?.expanded}
        onToggle={onToggle}
        onRetry={onRetry}
      >
        <PanelContent
          status={state("finance")}
          loadingHint="安装 mootdx 后可用"
          errorMsg={financeErr}
          isEmpty={Object.keys(finance).length === 0}
        >
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {Object.entries(finance).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{k}</p>
                <p className="mt-0.5 font-mono text-sm font-bold">{v == null ? "—" : String(v)}</p>
              </div>
            ))}
          </div>
        </PanelContent>
      </SubToggle>

      <SubToggle
        icon={<Boxes className="h-4 w-4 text-primary" />}
        title="个股基本面"
        hint="akshare"
        status={state("info")}
        expandKey="info"
        expanded={!!panelStates.info?.expanded}
        onToggle={onToggle}
        onRetry={onRetry}
      >
        <PanelContent
          status={state("info")}
          loadingHint="安装 akshare 后可用"
          errorMsg={infoErr}
          isEmpty={Object.keys(info).length === 0}
        >
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {Object.entries(info).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{k}</p>
                <p className="mt-0.5 font-mono text-sm font-bold">{String(v)}</p>
              </div>
            ))}
          </div>
        </PanelContent>
      </SubToggle>

      <SubToggle
        icon={<Megaphone className="h-4 w-4 text-primary" />}
        title="巨潮公告"
        hint="akshare"
        status={state("disclosure")}
        expandKey="disclosure"
        expanded={!!panelStates.disclosure?.expanded}
        onToggle={onToggle}
        onRetry={onRetry}
      >
        <PanelContent
          status={state("disclosure")}
          loadingHint="安装 akshare 后可用"
          errorMsg={discErr}
          isEmpty={disc.length === 0}
        >
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground/60">环境不稳时可能为空。</p>
            {disc.slice(0, 10).map((d, i) => (
              <div key={i} className="flex items-start gap-3 border-b border-border/40 pb-2 text-sm last:border-0">
                <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">{String(d.date ?? "").slice(0, 10)}</span>
                {d.url ? (
                  <a href={String(d.url)} target="_blank" rel="noreferrer" className="flex-1 truncate hover:text-primary">{String(d.title ?? "")}</a>
                ) : (
                  <span className="flex-1 truncate">{String(d.title ?? "")}</span>
                )}
              </div>
            ))}
          </div>
        </PanelContent>
      </SubToggle>
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// 面板内容渲染：处理 loading / error / empty / success
// ---------------------------------------------------------------------------

function PanelContent({
  status,
  loadingHint,
  errorMsg,
  isEmpty,
  children,
}: {
  status: PanelStatus;
  loadingHint: string;
  errorMsg: string | null;
  isEmpty: boolean;
  children: React.ReactNode;
}) {
  if (status === "loading") {
    return <Loading />;
  }
  if (status === "error") {
    return <p className="text-xs text-warning">{errorMsg ?? "加载失败"}（{loadingHint}）</p>;
  }
  if (status === "empty" || isEmpty) {
    return <p className="text-xs text-muted-foreground/60">暂无数据。</p>;
  }
  return <>{children}</>;
}

function Loading() {
  return (
    <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
    </div>
  );
}
