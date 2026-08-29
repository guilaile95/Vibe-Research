import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, AlertCircle, ExternalLink, FileText, Loader2, Newspaper, RefreshCw, Star, TrendingUp } from "lucide-react";
import MarketIntelPanel from "@/components/market/MarketIntelPanel";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, ApiError, type Announcement, type NewsItem } from "@/lib/api";
import { loadWatchAuthoritative } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "market-intel", label: "市场情报", icon: Activity, desc: "关注趋势、赛道要点与去重后的最新公开资讯" },
  { key: "events", label: "事件概率", icon: TrendingUp, desc: "全球宏观预期概率（公开数据、免登录只读），后续接入" },
  { key: "filings", label: "A股公告", icon: FileText, desc: "汇总关注列表里各个股的近期公告（东财公开披露）" },
  { key: "news", label: "公开新闻", icon: Newspaper, desc: "汇总关注列表里各个股的近期新闻（公开源）" },
];

interface FeedRow { code: string; name: string; when: string; title: string; meta?: string; url?: string }
const MAX_ROWS = 60;

function WatchlistFeed({ kind }: { kind: "filings" | "news" }) {
  const [codes, setCodes] = useState<string[]>([]);
  const [rows, setRows] = useState<FeedRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [depNote, setDepNote] = useState<string | null>(null);

  const load = useCallback(async (nextCodes: string[]) => {
    if (!nextCodes.length) { setRows([]); return; }
    setLoading(true);
    setErr(null);
    setDepNote(null);
    try {
      const nameOf: Record<string, string> = {};
      try {
        const quotes = await api.quote(nextCodes.join(","));
        for (const code of nextCodes) if (quotes[code]?.name) nameOf[code] = quotes[code].name;
      } catch {
        // A missing quote name does not block public filings or news.
      }

      const output: FeedRow[] = [];
      if (kind === "filings") {
        const results = await Promise.all(
          nextCodes.map((code) => api.announcements(code).then((announcements) => ({ code, announcements })).catch(() => ({ code, announcements: [] as Announcement[] }))),
        );
        for (const { code, announcements } of results) {
          for (const announcement of announcements) {
            output.push({
              code,
              name: nameOf[code] || code,
              when: announcement.date,
              title: announcement.title.replace(/^[^:：]*[:：]/, ""),
              meta: announcement.type,
              url: announcement.url,
            });
          }
        }
      } else {
        let dependencyError: string | null = null;
        const results = await Promise.all(
          nextCodes.map((code) => api.news(code).then((news) => ({ code, news })).catch((cause) => {
            if (cause instanceof ApiError && cause.status === 501) dependencyError = cause.message;
            return { code, news: [] as NewsItem[] };
          })),
        );
        for (const { code, news } of results) {
          for (const item of news) {
            output.push({ code, name: nameOf[code] || code, when: item.发布时间 || "", title: item.新闻标题 || "", url: item.新闻链接 });
          }
        }
        if (dependencyError && output.length === 0) setDepNote(dependencyError);
      }

      const timestamp = (value: string) => {
        const raw = (value || "").trim();
        let result = Date.parse(raw);
        if (Number.isNaN(result)) result = Date.parse(raw.replace(" ", "T"));
        return Number.isNaN(result) ? 0 : result;
      };
      output.sort((left, right) => timestamp(right.when) - timestamp(left.when));
      setRows(output.slice(0, MAX_ROWS));
    } catch (cause) {
      setErr(cause instanceof ApiError ? cause.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    loadWatchAuthoritative()
      .then((result) => {
        setCodes(result.codes);
        void load(result.codes);
      })
      .catch(() => {
        setCodes([]);
        void load([]);
      });
  }, [load]);

  const refresh = () => {
    loadWatchAuthoritative()
      .then((result) => {
        setCodes(result.codes);
        void load(result.codes);
      })
      .catch(() => void load(codes));
  };

  if (!codes.length) {
    return (
      <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
        还没有关注股票。到<Link to="/daily-review" className="text-primary">「今天」</Link>加自选（6 位代码），这里会汇总它们的{kind === "filings" ? "公告" : "新闻"}。
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Star className="h-3.5 w-3.5 text-primary/70" />关注 {codes.length} 只 · 共 {rows.length} 条{kind === "filings" ? "公告" : "新闻"}（近期）
        </span>
        <button type="button" onClick={refresh} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {loading ? "拉取中…" : "刷新"}
        </button>
      </div>

      {err && <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="h-4 w-4 shrink-0" />{err}</div>}

      {depNote ? (
        <p className="py-6 text-center text-xs text-warning">{depNote}（安装后新闻即可用）</p>
      ) : loading && rows.length === 0 ? (
        <p className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在汇总关注股的{kind === "filings" ? "公告" : "新闻"}…</p>
      ) : rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground/60">关注列表里的个股近期暂无{kind === "filings" ? "公告" : "新闻"}。</p>
      ) : (
        <div className="space-y-2">
          {rows.map((row, index) => (
            <a key={index} href={row.url || undefined} target={row.url ? "_blank" : undefined} rel="noreferrer" className={cn("group flex items-baseline gap-3 border-b border-border/30 pb-2 text-sm last:border-0", row.url && "cursor-pointer")}>
              <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground/70">{(row.when || "").slice(kind === "filings" ? 0 : 5, kind === "filings" ? 10 : 16)}</span>
              <span className="w-16 shrink-0 truncate text-xs text-primary/90" title={row.code}>{row.name}</span>
              {kind === "filings" && row.meta && <span className="hidden w-20 shrink-0 truncate text-xs text-muted-foreground sm:block">{row.meta}</span>}
              <span className="flex-1 group-hover:text-primary">{row.title}</span>
              {row.url && <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/0 group-hover:text-primary/60" />}
            </a>
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

      {current.key === "market-intel" ? (
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
