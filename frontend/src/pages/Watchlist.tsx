import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, X, RefreshCw, Star } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  addCodes,
  filterAndSortWatchlistCodes,
  loadWatchAuthoritative,
  saveWatchAuthoritative,
  type WatchlistSort,
} from "@/lib/watchlist";
import {
  getWatchlistAnomalies,
  type WatchlistAnomalies,
  type WatchlistAnomalyItem,
} from "@/lib/decisionCockpit";
import { useLiveQuotes, isTradingHours } from "@/hooks/useLiveQuotes";
import { cn } from "@/lib/utils";
import { NativeIntelWatchlistContext } from "@/components/native-intel/NativeIntelWatchlistContext";

// A 股红涨绿跌（与整个看板一致）。
const color = (v: number | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
const pct = (v: number | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);
const money = (v: number | undefined) =>
  v == null ? "—" : v >= 10_000 ? `${(v / 10_000).toFixed(2)} 亿` : `${v.toFixed(0)} 万`;

const LIVE_KEY = "vr-watchlist-live";

// localStorage 在隐私模式 / 嵌入式浏览器里可能直接抛异常。读写都要兜底，
// 否则初始化时一抛整个自选股页就白屏（与 lib/storage.ts 的处理一致）。
const loadLive = (): boolean => {
  try {
    return localStorage.getItem(LIVE_KEY) === "on";
  } catch {
    return false;
  }
};
const saveLive = (on: boolean) => {
  try {
    localStorage.setItem(LIVE_KEY, on ? "on" : "off");
  } catch {
    /* 存储不可用：开关本次会话内仍生效，只是不被记住 */
  }
};

export function Watchlist() {
  const [codes, setCodes] = useState<string[]>([]);
  const [etag, setEtag] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [anomalies, setAnomalies] = useState<WatchlistAnomalies | null>(null);
  const [anomalyLoading, setAnomalyLoading] = useState(false);
  const [anomalyError, setAnomalyError] = useState<string | null>(null);
  const [onlyAnomalies, setOnlyAnomalies] = useState(false);
  const [sort, setSort] = useState<WatchlistSort>("anomaly");
  const anomalyRunRef = useRef(0);
  // 实时行情默认**关闭**——开着会持续请求，让用户自己决定要不要开。
  const [live, setLive] = useState(loadLive);

  const { quotes, loading, updatedAt, polling, error, refresh: refreshQuotes } = useLiveQuotes(codes, live);

  const toggleLive = () => {
    setLive((on) => {
      const next = !on;
      saveLive(next);
      return next;
    });
  };

  const load = useCallback(async () => {
    try {
      const r = await loadWatchAuthoritative();
      setCodes(r.codes);
      setEtag(r.etag);
      if (r.migrated) {
        setHint(`已从本地草稿迁移至后端权威自选（共 ${r.codes.length} 只）`);
      }
    } catch (e) {
      setHint(e instanceof Error ? e.message : "加载自选失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadAnomalies = useCallback(async () => {
    const run = ++anomalyRunRef.current;
    if (codes.length === 0) {
      setAnomalies(null);
      setAnomalyError(null);
      setAnomalyLoading(false);
      return;
    }
    setAnomalyLoading(true);
    setAnomalyError(null);
    try {
      const result = await getWatchlistAnomalies();
      if (run === anomalyRunRef.current) setAnomalies(result);
    } catch (e) {
      if (run === anomalyRunRef.current) {
        setAnomalies(null);
        setAnomalyError(e instanceof Error ? e.message : "异动数据暂不可用");
      }
    } finally {
      if (run === anomalyRunRef.current) setAnomalyLoading(false);
    }
  }, [codes]);

  useEffect(() => {
    void loadAnomalies();
  }, [loadAnomalies]);

  const persist = async (next: string[], msg?: string) => {
    setSaving(true);
    setHint(null);
    try {
      const r = await saveWatchAuthoritative(next, etag);
      setCodes(r.codes);
      setEtag(r.etag);
      if (msg) setHint(msg);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "保存失败（可能版本冲突，请刷新）");
      await load();
    } finally {
      setSaving(false);
    }
  };

  const add = () => {
    const { next, added } = addCodes(codes, input);
    if (added === 0) {
      setHint(input.trim() ? "没识别到新的 6 位代码（可能已在自选里）" : null);
      setInput("");
      return;
    }
    setInput("");
    void persist(next, `已添加 ${added} 只（后端权威）`);
  };

  const remove = (c: string) => {
    const next = codes.filter((x) => x !== c);
    void persist(next);
  };

  const anomalyByCode = useMemo(() => {
    const grouped: Record<string, WatchlistAnomalyItem[]> = {};
    for (const item of anomalies?.items ?? []) {
      (grouped[item.code] ??= []).push(item);
    }
    return grouped;
  }, [anomalies]);

  const anomalyUnavailableCodes = useMemo(
    () => new Set(anomalies?.unavailable_codes ?? []),
    [anomalies],
  );

  const visibleCodes = useMemo(
    () => filterAndSortWatchlistCodes(
      codes,
      quotes,
      anomalies?.items ?? [],
      sort,
      onlyAnomalies && anomalies !== null,
    ),
    [anomalies, codes, onlyAnomalies, quotes, sort],
  );

  const aiContext = useMemo(
    () =>
      codes.length
        ? "我的自选股（后端权威）：\n" +
          codes
            .map((c) => {
              const q = quotes[c];
              const events = anomalyByCode[c] ?? [];
              const eventText = events.length
                ? ` 异动：${events.map((item) => `${item.type}（${item.reason}）`).join("；")}`
                : "";
              return q
                ? `${q.name}(${c}) 现价${q.price} ${pct(q.change_pct)} PE(TTM)${q.pe_ttm ?? "—"} 换手${q.turnover_pct ?? "—"}%${eventText}`
                : `${c}（行情未取到）${eventText}`;
            })
            .join("\n")
        : "还没有自选股。",
    [anomalyByCode, codes, quotes],
  );

  return (
    <div>
      <PageHeader
        title="自选股"
        subtitle="批量添加、一屏总览你关注的标的。数据存后端权威自选（迁移后清除本地草稿）。"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleLive}
              title={live ? "关闭实时行情" : "开启实时行情（交易时段每 3 秒自动刷新）"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                live
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border/60 text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="relative flex h-2 w-2">
                {polling && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/70" />
                )}
                <span
                  className={cn(
                    "relative inline-flex h-2 w-2 rounded-full",
                    live ? "bg-primary" : "bg-muted-foreground/40",
                  )}
                />
              </span>
              实时行情
            </button>
            {codes.length > 0 && (
              <AskAiButton
                context={aiContext}
                label="让 AI 读自选"
                suggestions={["这几只里哪些估值偏高", "帮我按赛道分组看看", "各自最大的风险点是什么"]}
              />
            )}
          </div>
        }
      />

      <GlassCard className="mb-4">
        <label className="mb-1.5 block text-xs text-muted-foreground">
          批量添加 —— 粘贴一串代码即可（逗号 / 空格 / 换行都行，自动识别 6 位 A 股代码）
        </label>
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add();
            }}
            rows={2}
            placeholder={"如：600519 000858, 002463\n300750 688017"}
            className="flex-1 resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            onClick={add}
            disabled={saving}
            className="inline-flex h-9 shrink-0 items-center gap-1.5 self-start rounded-lg bg-primary/15 px-4 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
        </div>
        {hint && <p className="mt-2 text-xs text-muted-foreground/70">{hint}</p>}
      </GlassCard>

      <GlassCard glow>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-1.5 font-semibold">
            <Star className="h-4 w-4 text-primary" /> 自选总览
            <span className="text-xs font-normal text-muted-foreground">（{codes.length}）</span>
          </h3>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground/70">
            {error ? (
              <span className="text-warning">{error}</span>
            ) : (
              <>
                {/* 把「开着却没在刷」的原因说清楚，否则用户会以为坏了 */}
                {live && !polling && codes.length > 0 && (
                  <span>{isTradingHours() ? "已暂停（页面未激活）" : "非交易时段 · 已暂停"}</span>
                )}
                {polling && <span className="text-primary/80">实时 · 每 3 秒</span>}
                {updatedAt && (
                  <span className="font-mono">{new Date(updatedAt).toLocaleTimeString("zh-CN", { hour12: false })}</span>
                )}
              </>
            )}
            <button
              onClick={() => {
                refreshQuotes();
                void loadAnomalies();
              }}
              disabled={loading || anomalyLoading}
              className="text-muted-foreground hover:text-primary"
              title="刷新行情与异动"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", (loading || anomalyLoading) && "animate-spin")} />
            </button>
          </div>
        </div>
            {codes.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground/60">
                还没有自选股，用上面的框粘贴一串代码批量添加。
              </p>
            ) : (
              <>
                <NativeIntelWatchlistContext codes={codes} />

            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted/20 px-3 py-2 text-xs">
              <div className="text-muted-foreground">
                <span>HiThink · 当日异动快照</span>
                {anomalies?.as_of_ms != null && (
                  <span className="ml-2 font-mono">
                    数据截至 {new Date(anomalies.as_of_ms).toLocaleString("zh-CN", { hour12: false })}
                  </span>
                )}
                {anomalyError && <span className="ml-2 text-warning">异动数据暂不可用：{anomalyError}</span>}
              </div>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={onlyAnomalies}
                    disabled={anomalies === null}
                    onChange={(e) => setOnlyAnomalies(e.target.checked)}
                  />
                  仅看有异动
                </label>
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value as WatchlistSort)}
                  className="rounded border border-border bg-background px-2 py-1"
                  aria-label="自选排序"
                >
                  <option value="anomaly">异动优先</option>
                  <option value="watchlist">自选顺序</option>
                  <option value="change">涨跌幅绝对值</option>
                  <option value="amount">成交额</option>
                </select>
              </div>
            </div>
            {visibleCodes.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground/60">
                当前筛选下没有可显示的异动记录。
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm" data-testid="watchlist-anomaly-table">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="px-2 py-2 font-normal">股票</th>
                      <th className="px-2 py-2 text-right font-normal">最新价</th>
                      <th className="px-2 py-2 text-right font-normal">涨跌幅</th>
                      <th className="px-2 py-2 text-right font-normal">成交额</th>
                      <th className="px-2 py-2 font-normal">当日异动事实</th>
                      <th className="w-8 px-2 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {visibleCodes.map((c) => {
                      const q = quotes[c];
                      const events = anomalyByCode[c] ?? [];
                      return (
                        <tr key={c} data-watchlist-code={c}>
                  <td className="px-2 py-3">
                    <Link to={`/stock-data?code=${c}`} className="font-mono hover:text-primary hover:underline">
                      {c}
                    </Link>
                    {(q?.name || events[0]?.name) && (
                      <span className="ml-2 text-muted-foreground">{q?.name || events[0]?.name}</span>
                    )}
                  </td>
                  <td className="px-2 py-3 text-right font-mono">{q?.price ?? "—"}</td>
                  <td className={cn("px-2 py-3 text-right font-mono", color(q?.change_pct))}>
                      {pct(q?.change_pct)}
                  </td>
                  <td className="px-2 py-3 text-right font-mono">{money(q?.amount_wan)}</td>
                  <td className="max-w-[420px] px-2 py-3">
                    {events.length > 0 ? (
                      <div className="space-y-1">
                        {events.map((item, index) => (
                          <div key={`${item.provider_symbol}-${item.type}-${index}`}>
                            <span className="mr-2 rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">{item.type}</span>
                            <span className="text-muted-foreground">{item.reason || "当前数据源未提供原因"}</span>
                          </div>
                        ))}
                      </div>
                    ) : anomalyLoading ? (
                      <span className="text-muted-foreground/60">读取中…</span>
                    ) : anomalies && anomalyUnavailableCodes.has(c) ? (
                      <span className="text-warning">当前数据源未覆盖该标的异动查询</span>
                    ) : anomalies ? (
                      <span className="text-muted-foreground/60">当前数据源未返回异动记录</span>
                    ) : (
                      <span className="text-warning">异动数据暂不可用</span>
                    )}
                  </td>
                  <td className="px-2 py-3 text-right">
                    <button
                      onClick={() => remove(c)}
                      disabled={saving}
                      className="text-muted-foreground hover:text-danger disabled:opacity-50"
                      title="移除"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </GlassCard>
    </div>
  );
}
