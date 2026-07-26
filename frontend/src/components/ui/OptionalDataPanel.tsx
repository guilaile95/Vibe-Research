import {
  BarChart3,
  Boxes,
  ChevronDown,
  ChevronRight,
  LineChart,
  Loader2,
  Megaphone,
} from "lucide-react";
import type { DisclosureItem, KlineBar } from "@/lib/api";
import { GlassCard } from "./GlassCard";
import { KlineChart } from "./KlineChart";

type OptKey = "kline" | "finance" | "info" | "disclosure";

interface Props {
  onLoad: (key: OptKey) => void;
  expanded: Record<string, boolean>;
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
  loaded: boolean;      // 已有数据或报错即视为已加载
  expandKey: OptKey;
  expanded: boolean;
  onToggle: (key: OptKey) => void;
  children: React.ReactNode;
}

function SubToggle({ icon, title, hint, loaded, expandKey, expanded, onToggle, children }: SubToggleProps) {
  return (
    <div className="border-b border-border/40 last:border-0">
      <button
        onClick={() => onToggle(expandKey)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-muted/20"
      >
        {expanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
        {icon}
        <span className="font-medium">{title}</span>
        <span className="ml-auto text-xs text-muted-foreground/60">{loaded ? "已加载" : hint}</span>
      </button>
      {loaded && expanded && <div className="px-4 pb-3">{children}</div>}
    </div>
  );
}

/**
 * 个股数据「扩展数据」折叠面板：包含 K 线 / 季报财务 / 基本面 / 巨潮公告 四个子项，
 * 均为可选依赖（mootdx / akshare）。默认收起，首次展开才发起请求，
 * 避免每次查询都触发 501。
 */
export function OptionalDataPanel({
  onLoad,
  expanded,
  kline,
  klineErr,
  finance,
  financeErr,
  info,
  infoErr,
  disc,
  discErr,
}: Props) {
  // 面板是否已加载过（有数据或有错误即视为已加载）
  const loaded = {
    kline: kline.length > 0 || !!klineErr,
    finance: Object.keys(finance).length > 0 || !!financeErr,
    info: Object.keys(info).length > 0 || !!infoErr,
    disc: disc.length > 0 || !!discErr,
  };
  // 简易加载态：展开但尚未加载完成
  const loading = {
    kline: !!expanded.kline && !loaded.kline,
    finance: !!expanded.finance && !loaded.finance,
    info: !!expanded.info && !loaded.info,
    disc: !!expanded.disc && !loaded.disc,
  };

  return (
    <GlassCard className="mb-4 divide-y divide-border/40 overflow-hidden !p-0">
      <div className="px-4 py-2.5 text-xs font-semibold text-muted-foreground">
        扩展数据（可选依赖 · 按需加载）
      </div>

      <SubToggle
        icon={<LineChart className="h-4 w-4 text-primary" />}
        title="历史 K 线"
        hint="mootdx"
        loaded={loaded.kline}
        expandKey="kline"
        expanded={!!expanded.kline}
        onToggle={onLoad}
      >
        {loading.kline ? <Loading /> : klineErr ? (
          <p className="text-xs text-warning">{klineErr}（安装 mootdx 后可用）</p>
        ) : (
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground/60">最近 {kline.length} 个交易日 OHLC。</p>
            <KlineChart bars={kline} />
          </div>
        )}
      </SubToggle>

      <SubToggle
        icon={<BarChart3 className="h-4 w-4 text-primary" />}
        title="季报财务快照"
        hint="mootdx"
        loaded={loaded.finance}
        expandKey="finance"
        expanded={!!expanded.finance}
        onToggle={onLoad}
      >
        {loading.finance ? <Loading /> : financeErr ? (
          <p className="text-xs text-warning">{financeErr}（安装 mootdx 后可用）</p>
        ) : (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {Object.entries(finance).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{k}</p>
                <p className="mt-0.5 font-mono text-sm font-bold">{v == null ? "—" : String(v)}</p>
              </div>
            ))}
          </div>
        )}
      </SubToggle>

      <SubToggle
        icon={<Boxes className="h-4 w-4 text-primary" />}
        title="个股基本面"
        hint="akshare"
        loaded={loaded.info}
        expandKey="info"
        expanded={!!expanded.info}
        onToggle={onLoad}
      >
        {loading.info ? <Loading /> : infoErr ? (
          <p className="text-xs text-warning">{infoErr}（安装 akshare 后可用）</p>
        ) : (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {Object.entries(info).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{k}</p>
                <p className="mt-0.5 font-mono text-sm font-bold">{String(v)}</p>
              </div>
            ))}
          </div>
        )}
      </SubToggle>

      <SubToggle
        icon={<Megaphone className="h-4 w-4 text-primary" />}
        title="巨潮公告"
        hint="akshare"
        loaded={loaded.disc}
        expandKey="disclosure"
        expanded={!!expanded.disc}
        onToggle={onLoad}
      >
        {loading.disc ? <Loading /> : discErr ? (
          <p className="text-xs text-warning">{discErr}（安装 akshare 后可用）</p>
        ) : disc.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">暂无公告记录。</p>
        ) : (
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
        )}
      </SubToggle>
    </GlassCard>
  );
}

function Loading() {
  return (
    <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
    </div>
  );
}

