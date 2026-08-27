import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  AlertCircle,
  CircleSlash,
  Clock,
  Flame,
  Loader2,
  RefreshCw,
  Rss,
  Search,
  Server,
} from "lucide-react";
import {
  api,
  ApiError,
  type TrendradarEnvelope,
  type TrNewsRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 市场关注雷达（TrendRadar sidecar 只读控制台，TR1-P1）。
 *
 * 诚实渲染约定：
 * - 每个区块独立拉取、独立展示其 envelope status；
 * - DISABLED / CONFIG_ERROR / UNAVAILABLE / TIMEOUT / CONTRACT_MISMATCH /
 *   UPSTREAM_ERROR 都显式可见，绝不伪装"空列表=无热点"；
 * - 上游 relevance/hotness/sentiment 一律标注「关注度，非投资建议」。
 */

type SectionState = "idle" | "loading" | "ok" | "failed";

interface SectionStateInfo {
  state: SectionState;
  envelope?: TrendradarEnvelope;
}

const _FAILURE_HINTS: Record<string, string> = {
  DISABLED: "sidecar 网关未启用：设置 VIBE_TRENDRADAR_MCP_URL=http://127.0.0.1:<port>/mcp 后重启后端",
  CONFIG_ERROR: "网关配置非法（如非回环地址），已 fail-closed",
  UNAVAILABLE: "sidecar 不可达/未安装客户端",
  TIMEOUT: "sidecar 超时",
  CONTRACT_MISMATCH: "上游契约漂移（fail-closed，需要重新资格认证）",
  UPSTREAM_ERROR: "sidecar 工具返回错误",
};

function failureText(env: TrendradarEnvelope): string {
  const base =
    _FAILURE_HINTS[env.status] ?? `sidecar 返回异常状态 ${env.status}`;
  return env.error ? `${base} — ${env.error}` : base;
}

/** MCP 工具可能返回 structuredContent，也可能按上游声明返回 JSON 文本。 */
function envelopeResult(env: TrendradarEnvelope): unknown {
  if (env.result !== undefined) return env.result;
  if (typeof env.result_text !== "string") return undefined;
  try {
    return JSON.parse(env.result_text) as unknown;
  } catch {
    return env.result_text;
  }
}

function sectionState(env: TrendradarEnvelope): SectionStateInfo {
  return { state: env.status === "OK" ? "ok" : "failed", envelope: env };
}

function StatusBadge({ env }: { env?: TrendradarEnvelope }) {
  if (!env) return null;
  const ok = env.status === "OK";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
        ok
          ? "bg-emerald-500/10 text-emerald-500"
          : "bg-amber-500/10 text-amber-500",
      )}
    >
      {env.status}
    </span>
  );
}

function FailureBanner({ env }: { env: TrendradarEnvelope }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-600">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{failureText(env)}</span>
    </div>
  );
}

export default function TrendRadarPanel() {
  const [statusEnv, setStatusEnv] = useState<TrendradarEnvelope | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  // 各功能区独立状态
  const [latest, setLatest] = useState<SectionStateInfo>({ state: "idle" });
  const [trending, setTrending] = useState<SectionStateInfo>({ state: "idle" });
  const [rss, setRss] = useState<SectionStateInfo>({ state: "idle" });
  const [topicProbe, setTopicProbe] = useState<{
    topic: string;
    loading: boolean;
    trend?: TrendradarEnvelope;
    sentiment?: TrendradarEnvelope;
  }>({ topic: "", loading: false });

  const refreshStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const env = await api.trendradarStatus();
      setStatusEnv(env);
    } catch (e) {
      setStatusEnv({
        status: "UNAVAILABLE",
        error: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setStatusLoading(false);
    }
  }, []);

  const loadLatest = useCallback(async () => {
    setLatest({ state: "loading" });
    try {
      const envelope = await api.trendradarLatest(30);
      setLatest(sectionState(envelope));
    } catch (e) {
      setLatest({
        state: "failed",
        envelope: {
          status: "UNAVAILABLE",
          error: e instanceof ApiError ? e.message : String(e),
        },
      });
    }
  }, []);

  const loadTrending = useCallback(async () => {
    setTrending({ state: "loading" });
    try {
      const envelope = await api.trendradarTrending();
      setTrending(sectionState(envelope));
    } catch (e) {
      setTrending({
        state: "failed",
        envelope: {
          status: "UNAVAILABLE",
          error: e instanceof ApiError ? e.message : String(e),
        },
      });
    }
  }, []);

  const loadRss = useCallback(async () => {
    setRss({ state: "loading" });
    try {
      const envelope = await api.trendradarRssLatest(1, 20);
      setRss(sectionState(envelope));
    } catch (e) {
      setRss({
        state: "failed",
        envelope: {
          status: "UNAVAILABLE",
          error: e instanceof ApiError ? e.message : String(e),
        },
      });
    }
  }, []);

  useEffect(() => {
    refreshStatus().then(() => {
      // 仅当 status 为 OK 才继续装载其余面板；失败态保持各自显式提示
      void Promise.all([loadLatest(), loadTrending(), loadRss()]);
    });
  }, [refreshStatus, loadLatest, loadTrending, loadRss]);

  const probeTopic = async (rawTopic: string) => {
    const topic = rawTopic.trim();
    if (!topic || topicProbe.loading) return;
    setTopicProbe({ topic, loading: true });
    try {
      const [trend, sentiment] = await Promise.all([
        api.trendradarTopicTrend(topic),
        api.trendradarSentiment(topic).catch((e: unknown) => ({
          status: "UNAVAILABLE",
          error: e instanceof ApiError ? e.message : String(e),
        })),
      ]);
      setTopicProbe({ topic, loading: false, trend, sentiment });
    } catch (e) {
      setTopicProbe({
        topic,
        loading: false,
        trend: {
          status: "UNAVAILABLE",
          error: e instanceof ApiError ? e.message : String(e),
        },
      });
    }
  };

  const gwEnabled = statusEnv?.gateway?.enabled === true;
  const upstream = statusEnv?.upstream;

  return (
    <div className="space-y-4">
      {/* 关注度语义声明 —— authority boundary 可视化 */}
      <div className="rounded-lg border border-border/60 bg-muted/10 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
        数据来自本机 TrendRadar sidecar 的公开舆情观察（只读）。热度 / 相关度 /
        情绪分仅表示「值得关注 / 研究」，<b>不是买卖建议</b>，也不进入持仓 /
        论点 / 决策任何权威链。
      </div>

      {/* 服务状态条 */}
      <div className="rounded-xl border border-border/70 bg-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-sm font-semibold">
            <Server className="h-4 w-4 text-primary" /> Sidecar 状态
          </span>
          <button
            onClick={() => refreshStatus()}
            className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-[11px] hover:bg-accent"
          >
            {statusLoading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}{" "}
            刷新
          </button>
        </div>
        {statusLoading && !statusEnv ? (
          <div className="text-xs text-muted-foreground">读取中…</div>
        ) : statusEnv?.status === "OK" ? (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs md:grid-cols-3">
            <div>
              网关：<span className="font-mono">enabled @ {statusEnv.gateway?.mcp_url_host}</span>
            </div>
            <div>
              服务端：
              <span className="font-mono">
                {" "}
                {statusEnv.server?.server_name || "?"} v{statusEnv.server?.server_version || "?"}
              </span>
            </div>
            <div>
              协议：
              <span className="font-mono"> {statusEnv.server?.protocol_version || "?"}</span>
            </div>
            <div className="col-span-2 truncate">
              上游：<span className="font-mono">{upstream?.repo}@{upstream?.source_commit?.slice(0, 8)}</span>{" "}
              core v{upstream?.core_version} · mcp v{upstream?.mcp_version} ·{" "}
              {(upstream?.license) ?? ""}
            </div>
          </div>
        ) : statusEnv ? (
          <FailureBanner env={statusEnv} />
        ) : null}
      </div>

      {!gwEnabled && statusEnv && statusEnv.status !== "OK" ? (
        <div className="rounded-xl border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/80">
          雷达各区块依赖可用的 sidecar。先按上方提示恢复网关，再回来刷新。
        </div>
      ) : (
        <>
          {/* 最新热榜 */}
          <section className="rounded-xl border border-border/70 bg-card p-4">
            <header className="mb-2 flex items-center justify-between">
              <h4 className="flex items-center gap-1.5 text-sm font-semibold">
                <Flame className="h-4 w-4 text-primary" /> 全平台热榜 · 最新抓取
                <StatusBadge env={latest.envelope} />
              </h4>
              <button onClick={() => loadLatest()} className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-[11px] hover:bg-accent">
                {latest.state === "loading" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} 刷新
              </button>
            </header>
            {latest.state !== "ok" ? (
              latest.envelope ? <FailureBanner env={latest.envelope} /> : null
            ) : (
              <HotlistContent env={latest.envelope!} />
            )}
          </section>

          {/* 热点话题 + 话题探针 */}
          <section className="rounded-xl border border-border/70 bg-card p-4">
            <header className="mb-2 flex items-center justify-between">
              <h4 className="flex items-center gap-1.5 text-sm font-semibold">
                <Activity className="h-4 w-4 text-primary" /> 热点话题 / 主题趋势与情绪探针
                <StatusBadge env={trending.envelope} />
              </h4>
              <button onClick={() => loadTrending()} className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-[11px] hover:bg-accent">
                {trending.state === "loading" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} 刷新
              </button>
            </header>
            <TopicProbeStrip onProbe={probeTopic} busy={topicProbe.loading} />
            {topicProbe.topic && (
              <div className="mt-3 rounded-lg border border-border/60 bg-muted/10 p-3 text-xs">
                <div className="mb-1 font-medium">
                  探针目标：{topicProbe.topic}
                  {topicProbe.loading && <Loader2 className="ml-2 inline h-3 w-3 animate-spin" />}
                </div>
                {topicProbe.trend && (
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] text-muted-foreground">
                    {summarizeEnvelope(topicProbe.trend)}
                  </pre>
                )}
                {topicProbe.sentiment && (
                  <>
                    <div className="mt-2 mb-1 text-[11px] text-muted-foreground">情绪面：</div>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] text-muted-foreground">
                      {summarizeEnvelope(topicProbe.sentiment)}
                    </pre>
                  </>
                )}
              </div>
            )}
            {trending.state === "ok" && renderTrendingResult(trending.envelope)}
          </section>

          {/* RSS */}
          <section className="rounded-xl border border-border/70 bg-card p-4">
            <header className="mb-2 flex items-center justify-between">
              <h4 className="flex items-center gap-1.5 text-sm font-semibold">
                <Rss className="h-4 w-4 text-primary" /> RSS 订阅流
                <StatusBadge env={rss.envelope} />
              </h4>
              <button onClick={() => loadRss()} className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-[11px] hover:bg-accent">
                {rss.state === "loading" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} 刷新
              </button>
            </header>
            {rss.state !== "ok" ? (
              rss.envelope ? <FailureBanner env={rss.envelope} /> : null
            ) : (
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] text-muted-foreground">
                {summarizeEnvelope(rss.envelope!)}
              </pre>
            )}
          </section>
        </>
      )}

      <p className="text-[11px] text-muted-foreground/60">
        通知发送 / 手动爬取触发在 Phase 3 单独授权前不提供。文章阅读器等出网工具暂未开放。
      </p>
    </div>
  );
}

function HotlistTable({ rows }: { rows?: TrNewsRow[] }) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground/70">
        <CircleSlash className="mr-1 inline h-3.5 w-3.5" />
        sidecar 未返回热榜条目（该日尚无抓取数据为真实空态）
      </div>
    );
  }
  return (
    <ul className="divide-y divide-border/40 text-sm">
      {rows.slice(0, 30).map((row, i) => (
        <li key={`${row.title}-${i}`} className="flex items-start gap-2 py-1.5">
          <span className="mt-0.5 inline-flex min-w-6 justify-center rounded bg-primary/10 px-1 text-[10px] font-bold text-primary">
            {row.rank ?? "-"}
          </span>
          <span className="min-w-0 flex-1 truncate">
            {row.url ? (
              <a href={row.url} target="_blank" rel="noreferrer noopener" className="hover:text-primary hover:underline">
                {row.title}
              </a>
            ) : (
              row.title
            )}
          </span>
          <span className="shrink-0 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground/80">
            {row.platform_name || row.platform}
          </span>
          {row.timestamp && (
            <span className="hidden shrink-0 items-center gap-0.5 font-mono text-[10px] text-muted-foreground md:inline-flex">
              <Clock className="h-3 w-3" />
              {row.timestamp.slice(11)}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function HotlistContent({ env }: { env: TrendradarEnvelope }) {
  const result = envelopeResult(env);
  if (Array.isArray(result)) {
    return <HotlistTable rows={result as TrNewsRow[]} />;
  }
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/40 bg-muted/10 p-2 font-mono text-[10px] text-muted-foreground">
      {summarizeEnvelope(env)}
    </pre>
  );
}

function TopicProbeStrip({
  onProbe,
  busy,
}: {
  onProbe: (t: string) => void;
  busy: boolean;
}) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onProbe(value);
      }}
      className="flex items-center gap-2"
    >
      <Search className="h-3.5 w-3.5 text-muted-foreground" />
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="输入主题词（如 固态电池 / 算力），查看趋势与情绪观察…"
        className="min-w-0 flex-1 rounded-md border border-border/60 bg-background px-2 py-1 text-xs outline-none focus:border-primary/50"
      />
      <button
        type="submit"
        disabled={busy || !value.trim()}
        className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-[11px] text-primary disabled:opacity-40"
      >
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Activity className="h-3 w-3" />}
        探针
      </button>
    </form>
  );
}

/** 通用 result 展示：找不到结构化摘要字段时退化为 JSON 文本（诚实原样）。 */
function summarizeEnvelope(env: TrendradarEnvelope): string {
  if (env.status !== "OK") return failureText(env);
  const result = envelopeResult(env);
  if (result == null) return "(工具未返回结果)";
  try {
    return typeof result === "string"
      ? result.slice(0, 4000)
      : JSON.stringify(result, null, 1).slice(0, 4000);
  } catch {
    return "(不可序列化结果)";
  }
}

function renderTrendingResult(env?: TrendradarEnvelope): ReactNode {
  if (!env || env.status !== "OK") return null;
  const result = envelopeResult(env);
  const topics = Array.isArray(result)
    ? result.filter((topic): topic is string => typeof topic === "string")
    : result && typeof result === "object"
      ? Object.values(result).find(
          (value): value is string[] =>
            Array.isArray(value) && value.every((topic) => typeof topic === "string"),
        )
      : undefined;
  if (topics && topics.length > 0) {
    return (
      <div className="mt-3 flex flex-wrap gap-1.5" aria-label="热点话题列表">
        {topics.slice(0, 30).map((topic) => (
          <span key={topic} className="rounded-full bg-primary/10 px-2 py-1 text-[11px] text-primary">
            {topic}
          </span>
        ))}
      </div>
    );
  }
  return (
    <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/40 bg-muted/10 p-2 font-mono text-[10px] text-muted-foreground">
      {summarizeEnvelope(env)}
    </pre>
  );
}
