import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, X, RefreshCw, Star } from "lucide-react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  addCodes,
  parseCodes,
  filterAndSortWatchlistCodes,
  loadWatchAuthoritative,
  loadLocalDraft,
  saveWatchAuthoritative,
  type WatchlistSort,
} from "@/lib/watchlist";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import {
  getWatchlistAnomalies,
  type WatchlistAnomalies,
  type WatchlistAnomalyItem,
} from "@/lib/decisionCockpit";
import { useLiveQuotes, isTradingHours } from "@/hooks/useLiveQuotes";
import { formatQuoteTime, quoteSnapshotLabel } from "@/lib/quoteSnapshot";
import { cn } from "@/lib/utils";
import { WatchlistImport } from "@/components/watchlist/WatchlistImport";
import { NativeIntelWatchlistContext } from "@/components/native-intel/NativeIntelWatchlistContext";

import type { NativeIntelWatchlistContext as IntelContext } from "@/lib/api";

// A 股红涨绿跌（与整个看板一致）。
const color = (v: number | null | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);
const money = (v: number | null | undefined) =>
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
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [codes, setCodes] = useState<string[]>([]);
  // Reuse the existing backend security-directory projection; codes stay the identity.
  // Bind each response to its requested list so late results cannot name a new list.
  const [nameContext, setNameContext] = useState<{ codes: string[]; context: IntelContext | null } | null>(null);
  const onNameContext = useCallback((context: IntelContext | null, requestedCodes: string[]) => {
    setNameContext({ codes: requestedCodes, context });
  }, []);
  const metadataNames = useMemo(() => {
    const context = nameContext?.codes === codes ? nameContext.context : null;
    return new Map((context?.securities ?? []).map((item) => [item.code, item.company_name]));
  }, [codes, nameContext]);
  const [etag, setEtag] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [watchlistLoading, setWatchlistLoading] = useState(true);
  const [watchlistReady, setWatchlistReady] = useState(false);
  const saveInFlight = useRef(false);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [migrationError, setMigrationError] = useState<string | null>(null);
  const [anomalies, setAnomalies] = useState<WatchlistAnomalies | null>(null);
  const [anomalyLoading, setAnomalyLoading] = useState(false);
  const [anomalyError, setAnomalyError] = useState<string | null>(null);
  const onlyAnomalies = searchParams.get("anomalies") === "1";
  const requestedSort = searchParams.get("sort");
  const sort: WatchlistSort = requestedSort === "watchlist" || requestedSort === "change" || requestedSort === "amount" ? requestedSort : "anomaly";
  const updateView = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    next.set(key, value);
    setSearchParams(next, { replace: true });
  };

  const anomalyRunRef = useRef(0);
  const listHeadingRef = useRef<HTMLHeadingElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // 实时行情默认**关闭**——开着会持续请求，让用户自己决定要不要开。
  const [live, setLive] = useState(loadLive);

  const { quotes, loading, updatedAt, requestCompletedAt, snapshots, polling, error, refresh: refreshQuotes } = useLiveQuotes(codes, live);

  const toggleLive = () => {
    setLive((on) => {
      const next = !on;
      saveLive(next);
      return next;
    });
  };

  const load = useCallback(async () => {
    setWatchlistLoading(true);
    setWatchlistReady(false);
    setWatchlistError(null);
    setMigrationError(null);
    try {
      const r = await loadWatchAuthoritative();
      setCodes(r.codes);
      setEtag(r.etag);
      setWatchlistReady(r.status === "valid" || r.status === "not_configured");
      setMigrationError(r.migrationError ?? null);
      if (r.migrated) {
        setHint(`已从本地草稿迁移至后端权威自选（共 ${r.codes.length} 只）`);
      }
    } catch (e) {
      setWatchlistError(e instanceof Error ? e.message : "加载自选失败");
    } finally {
      setWatchlistLoading(false);
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

  const persist = async (next: string[], msg?: string): Promise<boolean> => {
    if (saveInFlight.current) return false;
    saveInFlight.current = true;
    setSaving(true);
    setHint(null);
    try {
      const r = await saveWatchAuthoritative(next, etag ?? "NOT_CONFIGURED");
      setCodes(r.codes);
      setEtag(r.etag);
      setWatchlistError(null);
      setMigrationError(null);
      if (msg) setHint(msg);
      return true;
    } catch (e) {
      setHint(e instanceof Error ? e.message : "保存失败（可能版本冲突，请刷新）");
      await load();
      return false;
    } finally {
      saveInFlight.current = false;
      setSaving(false);
    }
  };

  const add = () => {
    const { next, added } = addCodes(codes, input);
    // An explicitly edited migration draft may retain only existing codes.
    // Still save through the authority/ETag path before clearing that draft.
    if (added === 0 && !(migrationError && parseCodes(input).length > 0)) {
      setHint(input.trim() ? "没识别到新的 6 位代码（可能已在自选里）" : null);
      setInput("");
      return;
    }
    setInput("");
    void persist(next, added > 0 ? `已添加 ${added} 只（后端权威）` : "已保存自选（后端权威）");
  };

  const remove = (c: string) => {
    const next = codes.filter((x) => x !== c);
    void persist(next, `已移除 ${c}（后端权威）`).finally(() => {
      listHeadingRef.current?.focus();
    });
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
  useEffect(() => {
    if (!/^#watchlist-\d{6}$/.test(location.hash)) return;
    const frame = requestAnimationFrame(() => document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "center" }));
    return () => cancelAnimationFrame(frame);
  }, [visibleCodes, location.hash]);

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
                ? `${q.name}(${c}) 快照价格${q.price}（${quoteSnapshotLabel(snapshots?.[c])}） ${pct(q.change_pct)} PE(TTM)${q.pe_ttm ?? "—"} 换手${q.turnover_pct ?? "—"}%${eventText}`
                : `${c}（行情未取到）${eventText}`;
            })
            .join("\n")
        : "还没有自选股。",
    [anomalyByCode, codes, quotes, snapshots],
  );

  return (
    <div className="watchlist-page">
      <style>{`
        .quote-refresh-layout { display: grid; grid-template-columns: minmax(0, 1fr) 44px; align-items: start; gap: 12px; width: 100%; min-width: 0; }
        .quote-provenance { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; min-width: 0; }
        .quote-status-item { min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
        .quote-status-label { display: block; }
        @media (min-width: 768px) {
          .quote-refresh-layout { width: auto; flex: 1 1 560px; }
          .quote-provenance { display: flex; flex-wrap: wrap; gap: 4px 16px; }
          .quote-status-label { display: inline; }
          .quote-status-error { flex-basis: 100%; }
        }
        @media (max-width: 767px) {
          .watchlist-records, .watchlist-records tbody { display: block; min-width: 0; }
          .watchlist-records thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
          .watchlist-records tbody tr { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 12px 0; }
          .watchlist-records td { min-width: 0; padding: 8px 4px; overflow-wrap: anywhere; }
          .watchlist-records td:nth-child(1), .watchlist-records td:nth-child(4), .watchlist-records td:nth-child(5), .watchlist-records td:nth-child(6) { grid-column: 1 / -1; max-width: none; }
          .watchlist-records td:nth-child(2), .watchlist-records td:nth-child(3), .watchlist-records td:nth-child(4) { text-align: left; }
          .watchlist-records .watchlist-field-label { display: block; margin-bottom: 4px; font-family: inherit; font-size: 11px; color: hsl(var(--muted-foreground)); }
        }
      `}</style>
      <PageHeader
        title="自选股"
        subtitle="批量添加、一屏总览你关注的标的。数据存后端权威自选（迁移后清除本地草稿）。"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleLive}
              title={live ? "关闭自动刷新" : "开启自动刷新（按北京时间工作日时段，每次请求后等待 3 秒；不含节假日判断）"}
              className={cn(
                "inline-flex min-h-11 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
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
              自动刷新
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
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add();
            }}
            rows={2}
            placeholder={"如：600519 000858, 002463\n300750 688017"}
            className="min-w-0 flex-1 resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            onClick={add}
            disabled={saving}
            className="inline-flex min-h-11 shrink-0 items-center gap-1.5 self-start rounded-lg bg-primary/15 px-4 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
        </div>
        <p role="status" aria-live="polite" className="mt-2 text-xs text-muted-foreground/70">{hint}</p>
        {migrationError && (
          <div role="alert" className="mt-3 rounded-lg border border-warning/30 p-3 text-sm text-warning">
            <p>本地草稿未导入：{migrationError}</p>
            <p className="mt-1">原草稿已保留。可重试导入，或编辑本地草稿，在上方输入框删减后点击“添加”保存；与后端自选合并后最多 50 只，保存成功才清除原草稿。</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" disabled={watchlistLoading || saving} onClick={() => void load()} className="min-h-11 px-3 text-primary disabled:opacity-50">重试导入</button>
              <button type="button" disabled={watchlistLoading || saving} onClick={() => {
                setInput(loadLocalDraft().join(" "));
                inputRef.current?.focus();
              }} className="min-h-11 px-3 text-primary disabled:opacity-50">编辑本地草稿</button>
            </div>
          </div>
        )}
        <WatchlistImport codes={codes} etag={etag} disabled={saving || watchlistLoading || !watchlistReady || !!watchlistError} onApply={next => persist(next, "表格导入已保存（后端权威）")} />
      </GlassCard>

      <GlassCard glow>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 ref={listHeadingRef} tabIndex={-1} data-testid="watchlist-list-heading" className="flex items-center gap-1.5 rounded font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
            <Star className="h-4 w-4 text-primary" /> 自选总览
            <span className="text-xs font-normal text-muted-foreground">{watchlistLoading || watchlistError ? "（未确认）" : `（${codes.length}）`}</span>
          </h3>
          <div className="quote-refresh-layout" data-testid="quote-refresh-layout">
            <div className="quote-provenance text-xs leading-relaxed text-muted-foreground/70 md:text-[11px]" data-testid="quote-provenance">
              {error && <span role="status" className="quote-status-item quote-status-error text-warning">{error}</span>}
              {codes.length > 0 && (
                <>
                  <span className="quote-status-item"><span className="quote-status-label">快照覆盖 </span><span>{Object.keys(quotes).length}/{codes.length}</span></span>
                  {!live && <span className="quote-status-item">自动刷新已关闭</span>}
                  {live && !polling && <span className="quote-status-item">{isTradingHours() ? "自动刷新已暂停（页面未激活或等待请求）" : "非轮询时段 · 自动刷新已暂停"}</span>}
                  {polling && <span className="quote-status-item">自动刷新 · 常规请求间隔 3 秒，失败时退避</span>}
                  <span className="quote-status-item" title="按北京时间工作日时段判断，不含节假日；轮询状态不代表行情新鲜度">时段规则不含节假日</span>
                  <span className="quote-status-item">{updatedAt != null ? <><span className="quote-status-label">已显示快照最早行情时间 </span><span>{formatQuoteTime(updatedAt)}</span></> : "汇总行情时间未知"}</span>
                  {requestCompletedAt != null && <span className="quote-status-item"><span className="quote-status-label">上次请求完成 </span><span>{formatQuoteTime(requestCompletedAt)}（不是行情时间）</span></span>}
                </>
              )}
            </div>
            <button
              onClick={() => {
                refreshQuotes();
                void loadAnomalies();
              }}
              disabled={loading || anomalyLoading}
              className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              aria-label="刷新行情与异动"
              title="刷新行情与异动"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", (loading || anomalyLoading) && "animate-spin")} />
            </button>
          </div>
        </div>
            {watchlistLoading ? (
              <p className="py-8 text-center text-sm text-muted-foreground" role="status">正在读取自选股…</p>
            ) : watchlistError ? (
              <div className="py-8 text-center text-sm text-warning" role="alert">
                <p>自选股读取失败：{watchlistError}</p>
                <button type="button" onClick={() => void load()} className="mt-2 min-h-11 px-3 text-primary hover:underline">重试读取自选</button>
              </div>
            ) : codes.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground/60">
                还没有自选股，用上面的框粘贴一串代码批量添加。
              </p>
            ) : (
              <>
                <NativeIntelWatchlistContext codes={codes} onContextChange={onNameContext} />

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
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex min-h-11 cursor-pointer items-center gap-1.5 text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={onlyAnomalies}
                    disabled={anomalies === null}
                    onChange={(e) => updateView("anomalies", e.target.checked ? "1" : "0")}
                  />
                  仅看有异动
                </label>
                <select
                  value={sort}
                  onChange={(e) => updateView("sort", e.target.value)}
                  className="min-h-11 rounded border border-border bg-background px-2 py-1"
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
                <table role="table" aria-label="自选总览" className="watchlist-records w-full min-w-[760px] text-sm" data-testid="watchlist-anomaly-table">
                  <thead role="rowgroup">
                    <tr role="row" className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th role="columnheader" scope="col" id="watchlist-stock" className="px-2 py-2 font-normal">股票</th>
                      <th role="columnheader" scope="col" id="watchlist-price" className="px-2 py-2 text-right font-normal">快照价</th>
                      <th role="columnheader" scope="col" id="watchlist-change" className="px-2 py-2 text-right font-normal">涨跌幅</th>
                      <th role="columnheader" scope="col" id="watchlist-amount" className="px-2 py-2 text-right font-normal">成交额</th>
                      <th role="columnheader" scope="col" id="watchlist-anomaly" className="px-2 py-2 font-normal">当日异动事实</th>
                      <th role="columnheader" scope="col" id="watchlist-action" className="w-8 px-2 py-2"><span className="sr-only">操作</span></th>
                    </tr>
                  </thead>
                  <tbody role="rowgroup" className="divide-y divide-border/40">
                    {visibleCodes.map((c) => {
                      const q = quotes[c];
                      const events = anomalyByCode[c] ?? [];
                      const name = q?.name || events[0]?.name || metadataNames.get(c);
                      return (
                        <tr role="row" key={c} id={`watchlist-${c}`} data-watchlist-code={c}>
                  <td role="cell" headers="watchlist-stock" className="px-2 py-3">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <Link to={`/stock-data?code=${c}`} className="inline-flex min-h-11 items-center rounded font-mono hover:text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
                        {c}
                      </Link>
                      <Link
                        to={candidateWorkspaceHref(c, `${location.pathname}${location.search}#watchlist-${c}`)}
                        className="inline-flex min-h-11 items-center rounded px-2 text-[11px] text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                        data-testid={`watchlist-candidate-${c}`}
                      >
                        候选研究
                      </Link>
                    </div>
                    <div className="text-xs text-muted-foreground" data-testid={`quote-status-${c}`}>{quoteSnapshotLabel(snapshots?.[c])}</div>
                    {name && (
                      <span className="ml-2 text-muted-foreground">{name}</span>
                    )}
                  </td>
                  <td role="cell" headers="watchlist-price" className="px-2 py-3 text-right font-mono"><span aria-hidden="true" className="watchlist-field-label hidden">快照价</span>{q?.price ?? "—"}</td>
                  <td role="cell" headers="watchlist-change" className={cn("px-2 py-3 text-right font-mono", color(q?.change_pct))}>
                      <span aria-hidden="true" className="watchlist-field-label hidden">涨跌幅</span>
                      {pct(q?.change_pct)}
                  </td>
                  <td role="cell" headers="watchlist-amount" className="px-2 py-3 text-right font-mono"><span aria-hidden="true" className="watchlist-field-label hidden">成交额</span>{money(q?.amount_wan)}</td>
                  <td role="cell" headers="watchlist-anomaly" className="max-w-[420px] px-2 py-3">
                    <span aria-hidden="true" className="watchlist-field-label hidden">当日异动事实</span>
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
                  <td role="cell" headers="watchlist-action" className="px-2 py-3 text-right">
                    <button
                      onClick={() => remove(c)}
                      disabled={saving}
                      className="inline-flex min-h-11 min-w-11 items-center justify-center rounded text-muted-foreground hover:text-danger disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                      aria-label={`移除 ${name || "股票"}（${c}）`}
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
