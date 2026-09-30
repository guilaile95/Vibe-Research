import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, AlertCircle, ExternalLink, FileText, Flame, Loader2, Newspaper, RefreshCw, Star, TrendingUp } from "lucide-react";
import MarketIntelPanel from "@/components/market/MarketIntelPanel";
import { HotlistPanel } from "@/components/native-intel/HotlistPanel";
import { IntelReportPanel, IntelAnalyticsPanel } from "@/components/native-intel/IntelReports";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, ApiError, type Announcement, type NewsItem } from "@/lib/api";
import { loadWatchAuthoritative } from "@/lib/watchlist";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "reports", label: "报告", icon: FileText, desc: "当前、今日与增量报告" },
  { key: "analytics", label: "趋势分析", icon: TrendingUp, desc: "可解释的非 AI 统计分析" },
  { key: "hotlist", label: "实时热榜", icon: Flame, desc: "财联社热门、华尔街见闻等权威热榜与位次轨迹" },
  { key: "market-intel", label: "市场情报", icon: Activity, desc: "关注趋势、赛道要点与去重后的最新公开资讯" },
  { key: "events", label: "事件概率", icon: TrendingUp, desc: "全球宏观预期概率（公开数据、免登录只读），后续接入" },
  { key: "filings", label: "A股公告", icon: FileText, desc: "汇总关注列表里各个股的近期公告（东财公开披露）" },
  { key: "news", label: "公开新闻", icon: Newspaper, desc: "汇总关注列表里各个股的近期新闻（公开源）" },
];

interface FeedRow { code: string; name: string; when: string; title: string; meta?: string; url?: string }
const MAX_ROWS = 60;

type FeedKind = "filings" | "news";
interface FeedState {
  kind: FeedKind;
  status: "loading" | "ready" | "partial" | "error" | "watchlist-empty";
  codes: string[];
  rows: FeedRow[];
  error: string | null;
}

const loadingFeed = (kind: FeedKind): FeedState => ({ kind, status: "loading", codes: [], rows: [], error: null });

function validFeedItems(items: unknown, kind: FeedKind): items is Announcement[] | NewsItem[] {
  if (!Array.isArray(items)) return false;
  const titleKey = kind === "filings" ? "title" : "新闻标题";
  const textKeys = kind === "filings" ? ["date", "type", "url"] : ["发布时间", "文章来源", "新闻链接"];
  return items.every((item) => item && typeof item === "object"
    && typeof item[titleKey] === "string" && item[titleKey].trim()
    && textKeys.every((key) => (kind === "news" && !(key in item)) || typeof item[key] === "string"));
}

export function WatchlistFeed({ kind }: { kind: FeedKind }) {
  const [state, setState] = useState<FeedState>(() => loadingFeed(kind));
  const requestId = useRef(0);
  // A tab switch must not display the preceding feed while its effect is pending.
  const current = state.kind === kind ? state : loadingFeed(kind);
  const { codes, rows, error } = current;
  const loading = current.status === "loading";
  const label = kind === "filings" ? "公告" : "新闻";

  const refresh = useCallback(async () => {
    const request = ++requestId.current;
    const isCurrent = () => requestId.current === request;
    setState(loadingFeed(kind));
    let nextCodes: string[];
    try {
      const result = await loadWatchAuthoritative();
      if (!isCurrent()) return;
      if (result.status !== "valid" && result.status !== "not_configured") {
        setState({ ...loadingFeed(kind), status: "error", error: "关注列表无法读取，请到「今天」检查后重试。" });
        return;
      }
      if (!Array.isArray(result.codes) || result.codes.some((code) => typeof code !== "string" || !/^\d{6}$/.test(code))) {
        throw new Error("Invalid watchlist response");
      }
      nextCodes = result.codes;
    } catch {
      if (isCurrent()) setState({ ...loadingFeed(kind), status: "error", error: "关注列表加载失败，请重试。" });
      return;
    }
    if (!nextCodes.length) {
      setState({ ...loadingFeed(kind), status: "watchlist-empty" });
      return;
    }
    setState({ ...loadingFeed(kind), codes: nextCodes });

    // Quote names are optional; fetch independently without delaying feed requests.
    const [quotes, results] = await Promise.all([
      api.quote(nextCodes.join(",")).catch(() => null),
      Promise.allSettled(nextCodes.map(async (code) => {
        const items = kind === "filings" ? await api.announcements(code) : await api.news(code);
        if (!validFeedItems(items, kind)) throw new Error("Invalid feed response");
        return { code, items };
      })),
    ]);
    if (!isCurrent()) return;

    const output: FeedRow[] = [];
    let failures = 0;
    let dependencies = 0;
    for (const result of results) {
      if (result.status === "rejected") {
        failures += 1;
        if (result.reason instanceof ApiError && result.reason.status === 501) dependencies += 1;
        continue;
      }
      const { code, items } = result.value;
      const quoteName = quotes?.[code]?.name;
      const name = typeof quoteName === "string" && quoteName ? quoteName : code;
      if (kind === "filings") {
        for (const item of items as Announcement[]) {
          output.push({ code, name, when: item.date, title: item.title.replace(/^[^:：]*[:：]/, ""), meta: item.type, url: item.url });
        }
      } else {
        for (const item of items as NewsItem[]) {
          output.push({ code, name, when: item.发布时间 || "", title: item.新闻标题 || "", url: item.新闻链接 });
        }
      }
    }
    const timestamp = (value: string) => {
      const parsed = Date.parse(value.trim().replace(" ", "T"));
      return Number.isNaN(parsed) ? 0 : parsed;
    };
    output.sort((left, right) => timestamp(right.when) - timestamp(left.when));
    const allFailed = failures === nextCodes.length;
    const feedLabel = kind === "filings" ? "公告" : "新闻";
    let message: string | null = null;
    if (failures) {
      message = allFailed
        ? `${feedLabel}加载失败（${failures}/${nextCodes.length} 只），请重试。`
        : `部分${feedLabel}加载失败（${failures}/${nextCodes.length} 只），当前仅展示已成功获取的结果，请重试。`;
      if (kind === "news" && dependencies) message += " 新闻服务缺少 akshare 依赖，请安装后重试。";
    }
    setState({ kind, codes: nextCodes, rows: output.slice(0, MAX_ROWS), status: allFailed ? "error" : failures ? "partial" : "ready", error: message });
  }, [kind]);

  useEffect(() => {
    void refresh();
    return () => { requestId.current += 1; };
  }, [refresh]);

  if (current.status === "watchlist-empty") {
    return (
      <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
        还没有关注股票。到<Link to="/daily-review" className="text-primary">「今天」</Link>加自选（6 位代码），这里会汇总它们的{label}。
        <button type="button" onClick={() => void refresh()} className="ml-2 text-primary hover:underline">刷新</button>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Star className="h-3.5 w-3.5 text-primary/70" />
          {codes.length ? `关注 ${codes.length} 只 · ${loading ? `正在获取${label}` : `${error ? "已获取" : "共"} ${rows.length} 条${label}（近期）`}` : "关注列表"}
        </span>
        <button type="button" onClick={() => void refresh()} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {loading ? "拉取中…" : error ? "重试" : "刷新"}
        </button>
      </div>

      {error && <div role="alert" className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}

      {loading ? (
        <p role="status" className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在汇总关注股的{label}…</p>
      ) : current.status === "ready" && rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground/60">关注列表里的个股近期暂无{label}。</p>
      ) : current.status === "partial" && rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground/60">已成功获取的个股近期暂无{label}，其余个股尚未获取成功。</p>
      ) : (
        <div className="space-y-2">
          {rows.map((row, index) => (
            <div key={index} className="flex items-baseline gap-3 border-b border-border/30 pb-2 text-sm last:border-0">
              <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground/70">{(row.when || "").slice(kind === "filings" ? 0 : 5, kind === "filings" ? 10 : 16)}</span>
              <span className="w-16 shrink-0 truncate text-xs text-primary/90" title={row.code}>{row.name}</span>
              {kind === "filings" && row.meta && <span className="hidden w-20 shrink-0 truncate text-xs text-muted-foreground sm:block">{row.meta}</span>}
              {row.url ? (
                <a href={row.url} target="_blank" rel="noreferrer noopener" className="group flex min-w-0 flex-1 items-center gap-1 hover:text-primary hover:underline">
                  <span className="truncate">{row.title}</span>
                  <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground/0 group-hover:text-primary/60" />
                </a>
              ) : <span className="min-w-0 flex-1 truncate">{row.title}</span>}
              <Link
                to={candidateWorkspaceHref(row.code)}
                className="shrink-0 text-[11px] text-primary hover:underline"
                data-testid={`intel-candidate-${row.code}`}
              >
                候选研究
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Intel() {
  const [tab, setTab] = useState("market-intel");
  const current = TABS.find((item) => item.key === tab)!;

  return (
    <div>
      <PageHeader title="资讯中心" subtitle="关注趋势、赛道要点、公告与公开资讯" />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} type="button" onClick={() => setTab(key)} className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors", tab === key ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50")}>
            <Icon className="h-4 w-4" />{label}
          </button>
        ))}
      </div>

      {current.key === "reports" ? <IntelReportPanel /> : current.key === "analytics" ? <IntelAnalyticsPanel /> : current.key === "hotlist" ? (
        <HotlistPanel />
      ) : current.key === "market-intel" ? (
        <MarketIntelPanel />
      ) : (
        <GlassCard glow>
          <div className="mb-3 flex items-center gap-2">
            <current.icon className="h-5 w-5 text-primary" />
            <h3 className="font-semibold">{current.label}</h3>
          </div>
          {current.key === "filings" ? (
            <WatchlistFeed kind="filings" />
          ) : current.key === "news" ? (
            <WatchlistFeed kind="news" />
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{current.desc}</p>
              <div className="mt-4 rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">该数据源规划中——可先用「市场情报」看关注趋势、赛道要点与最新资讯，或用「A 股公告 / 公开新闻」看关注股动态。</div>
            </>
          )}
        </GlassCard>
      )}

      <p className="mt-3 text-[11px] text-muted-foreground/60">公告 / 新闻来自你关注列表里个股的公开披露与公开源；市场情报会保留来源健康与本地历史。今日要点由你配置的 AI 提炼。</p>
    </div>
  );
}
