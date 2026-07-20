import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Sparkles, Loader2, AlertCircle, RefreshCw, Gauge, TrendingUp, TrendingDown,
  Plus, X, Flame, BarChart3, Globe, Layers, Save, History, Eye, ChevronLeft, ChevronRight,
  GitCompare,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  api, ApiError, dailyReviewAnalyzeStream,
  type Quote, type DailyReviewData, type BoardRankItem, type MarketSnapshotItem,
  type DataStatus, type DailyReviewHistoryItem, type DailyReviewHistorySnapshot,
  type DailyReviewComparison, type NumericComparison, type RankingComparison,
  type HighlightComparison,
} from "@/lib/api";
import { loadLlm } from "@/lib/llm";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { loadWatch, saveWatch, addCodes } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

const HISTORY_LIMIT = 20;
const COMPARE_BOARD_LIMIT = 10;
const COMPARE_STOCK_LIMIT = 10;

const rateCell = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)}%`;

/** 相对变化比例 → ±xx.xx%（不重算，只格式化后端 change_pct） */
const fmtChangePct = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const p = v * 100;
  return `${p > 0 ? "+" : ""}${p.toFixed(2)}%`;
};

const fmtSigned = (v: number | null | undefined, digits = 2) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  return v > 0 ? `+${s}` : s;
};

const fmtYiDelta = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const yiVal = v / 1e8;
  const s = yiVal.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return `${yiVal > 0 ? "+" : ""}${s} 亿`;
};

const comparisonStatusLabel = (s: DataStatus | undefined) => {
  if (s === "normal") return { text: "可完整比较", cls: "bg-muted/40 text-muted-foreground" };
  if (s === "partial") return { text: "部分数据不可比较", cls: "bg-warning/15 text-warning" };
  if (s === "unavailable") return { text: "核心数据不可比较", cls: "bg-destructive/15 text-destructive" };
  return null;
};

const itemLabel = (it: { name?: string; code?: string } | null | undefined) => {
  if (!it) return "—";
  return it.name || it.code || "—";
};

// A股红涨绿跌。全球市场（美股/港股指数）**也沿用红涨**——与整个看板及东财等中国平台一致。
const pctColor = (p: number) => (p > 0 ? "text-danger" : p < 0 ? "text-success" : "text-muted-foreground");
const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null | undefined) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`);
const numCell = (v: number | null | undefined): string | number => (v == null ? "—" : v);
const pctCell = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`;

/** 与后端 market._breadth_label 一致 */
const breadthLabel = (upRatio: number | null | undefined): string => {
  if (upRatio == null || !Number.isFinite(upRatio)) return "—";
  if (upRatio < 0.25) return "冰点";
  if (upRatio < 0.4) return "偏弱";
  if (upRatio <= 0.6) return "中性";
  if (upRatio <= 0.75) return "偏强";
  return "普涨";
};

/** 与后端 market._speculation_label 一致 */
const speculationLabel = (zt: number | null | undefined): string => {
  if (zt == null) return "—";
  if (zt >= 100) return "亢奋";
  if (zt >= 60) return "活跃";
  if (zt >= 30) return "普通";
  return "冰点";
};

const formatUpRatio = (r: number | null | undefined): string => {
  if (r != null && Number.isFinite(r)) return `${(r * 100).toFixed(1)}%`;
  return "—";
};

const statusBadge = (status: DataStatus | undefined) => {
  if (status === "partial") return { text: "部分缺失", cls: "bg-warning/15 text-warning" };
  if (status === "unavailable") return { text: "不可用", cls: "bg-destructive/15 text-destructive" };
  if (status === "normal") return { text: "正常", cls: "bg-muted/40 text-muted-foreground/70" };
  return null;
};

export function DailyReview() {
  const [review, setReview] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewErr, setReviewErr] = useState<string | null>(null);
  const [needConfig, setNeedConfig] = useState(false);

  // 统一聚合包
  const [dr, setDr] = useState<DailyReviewData | null>(null);
  const [drDone, setDrDone] = useState(false);
  const [drErr, setDrErr] = useState<string | null>(null);

  // 自选（独立请求）
  const [watchCodes, setWatchCodes] = useState<string[]>(loadWatch);
  const [watchQuotes, setWatchQuotes] = useState<Record<string, Quote>>({});
  const [watchInput, setWatchInput] = useState("");
  const [watchLoading, setWatchLoading] = useState(false);

  const [boardTab, setBoardTab] = useState<"industry" | "concept" | "region">("industry");

  // 显式保存当前复盘（不自动触发）
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  // 历史列表（与实时复盘独立）
  const [histItems, setHistItems] = useState<DailyReviewHistoryItem[]>([]);
  const [histLoading, setHistLoading] = useState(false);
  const [histDone, setHistDone] = useState(false);
  const [histErr, setHistErr] = useState<string | null>(null);
  const [histFilterDate, setHistFilterDate] = useState("");
  const [histOffset, setHistOffset] = useState(0);
  const [histCount, setHistCount] = useState(0);

  // 历史详情（只读，不替换当前实时 dr）
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<number | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedSnapshot, setSelectedSnapshot] = useState<DailyReviewHistorySnapshot | null>(null);

  // 快照对比（只读；不替换实时 dr / 不触发 AI / 不自动请求）
  const [baseSnapshot, setBaseSnapshot] = useState<DailyReviewHistoryItem | null>(null);
  const [targetSnapshot, setTargetSnapshot] = useState<DailyReviewHistoryItem | null>(null);
  const [comparison, setComparison] = useState<DailyReviewComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);

  const loadDailyReview = () => {
    setDrDone(false);
    setDrErr(null);
    api.dailyReview()
      .then(setDr)
      .catch((e) => {
        setDr(null);
        setDrErr(e instanceof ApiError ? e.message : "每日复盘请求失败");
      })
      .finally(() => setDrDone(true));
  };

  const loadHistory = (opts?: { trade_date?: string; offset?: number }) => {
    const offset = opts?.offset ?? histOffset;
    const tradeDate = opts?.trade_date !== undefined ? opts.trade_date : histFilterDate;
    setHistLoading(true);
    setHistErr(null);
    const params: { trade_date?: string; limit: number; offset: number } = {
      limit: HISTORY_LIMIT,
      offset,
    };
    if (tradeDate) params.trade_date = tradeDate;
    api.listDailyReviewHistory(params)
      .then((res) => {
        setHistItems(res.items || []);
        setHistCount(res.count ?? (res.items?.length ?? 0));
        setHistOffset(res.offset ?? offset);
      })
      .catch((e) => {
        setHistItems([]);
        setHistCount(0);
        setHistErr(e instanceof ApiError ? e.message : "历史记录加载失败");
      })
      .finally(() => {
        setHistLoading(false);
        setHistDone(true);
      });
  };

  const pending = (done: boolean, emptyMsg = "暂无数据") => (
    <p className="py-4 text-center text-sm text-muted-foreground/60">
      {done ? emptyMsg : "加载中…"}
    </p>
  );

  const refreshWatch = (codes: string[]) => {
    if (!codes.length) { setWatchQuotes({}); return; }
    setWatchLoading(true);
    api.quote(codes.join(",")).then(setWatchQuotes).catch(() => {}).finally(() => setWatchLoading(false));
  };

  useEffect(() => {
    loadDailyReview();
    loadHistory({ trade_date: "", offset: 0 });
    refreshWatch(loadWatch());
    // 仅首次挂载：不自动保存
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveCurrentReview = async () => {
    if (saveLoading) return;
    setSaveLoading(true);
    setSaveMsg(null);
    setSaveErr(null);
    try {
      // 不发送当前页面 dr；服务器自行聚合
      const result = await api.saveDailyReviewHistory();
      if (result.snapshot.inserted) {
        setSaveMsg("当前复盘已保存");
      } else {
        setSaveMsg("相同内容的复盘快照已存在");
      }
      // 刷新历史列表，不重载当前实时复盘
      loadHistory({ offset: 0 });
      setHistOffset(0);
    } catch (e) {
      if (e instanceof ApiError) {
        setSaveErr(e.message || "保存每日复盘失败");
      } else {
        setSaveErr("保存每日复盘失败");
      }
    } finally {
      setSaveLoading(false);
    }
  };

  const openHistoryDetail = async (id: number) => {
    setSelectedSnapshotId(id);
    setSelectedSnapshot(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const snap = await api.getDailyReviewHistorySnapshot(id);
      setSelectedSnapshot(snap);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setDetailError("该历史快照不存在");
      } else {
        setDetailError(e instanceof ApiError ? e.message : "历史详情加载失败");
      }
    } finally {
      setDetailLoading(false);
    }
  };

  const closeHistoryDetail = () => {
    setSelectedSnapshotId(null);
    setSelectedSnapshot(null);
    setDetailError(null);
    setDetailLoading(false);
  };

  const onHistDateChange = (value: string) => {
    setHistFilterDate(value);
    setHistOffset(0);
    loadHistory({ trade_date: value, offset: 0 });
  };

  const clearCompareSelection = () => {
    setBaseSnapshot(null);
    setTargetSnapshot(null);
    setComparison(null);
    setComparisonError(null);
  };

  const runCompare = async () => {
    if (!baseSnapshot || !targetSnapshot || comparisonLoading) return;
    setComparisonLoading(true);
    setComparisonError(null);
    try {
      // 仅比较接口；不拉详情、不保存、不 AI、不重算 delta
      const result = await api.compareDailyReviewHistory({
        base_id: baseSnapshot.id,
        target_id: targetSnapshot.id,
        board_limit: COMPARE_BOARD_LIMIT,
        stock_limit: COMPARE_STOCK_LIMIT,
      });
      setComparison(result);
    } catch (e) {
      setComparison(null);
      setComparisonError(e instanceof ApiError ? e.message : "快照对比失败");
    } finally {
      setComparisonLoading(false);
    }
  };

  const histPage = Math.floor(histOffset / HISTORY_LIMIT) + 1;
  const histPrevDisabled = histOffset === 0 || histLoading;
  const histNextDisabled = histCount < HISTORY_LIMIT || histLoading;

  /** 数值比较表行渲染 */
  const renderNumericTable = (
    rows: { label: string; c: NumericComparison; kind?: "count" | "ratio" | "rate" | "amount" }[],
  ) => (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
            {["指标", "基础值", "目标值", "变化", "相对变化"].map((h) => (
              <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, c, kind = "count" }) => {
            let baseStr: string | number = "—";
            let targetStr: string | number = "—";
            let deltaStr = "—";
            if (kind === "ratio") {
              baseStr = formatUpRatio(c.base);
              targetStr = formatUpRatio(c.target);
              deltaStr = c.delta == null || !Number.isFinite(c.delta)
                ? "—"
                : `${c.delta > 0 ? "+" : ""}${(c.delta * 100).toFixed(2)} 个百分点`;
            } else if (kind === "rate") {
              baseStr = rateCell(c.base);
              targetStr = rateCell(c.target);
              deltaStr = c.delta == null || !Number.isFinite(c.delta)
                ? "—"
                : `${c.delta > 0 ? "+" : ""}${(c.delta * 100).toFixed(2)} 个百分点`;
            } else if (kind === "amount") {
              baseStr = yi(c.base);
              targetStr = yi(c.target);
              deltaStr = fmtYiDelta(c.delta);
            } else {
              baseStr = numCell(c.base);
              targetStr = numCell(c.target);
              deltaStr = fmtSigned(c.delta, 4);
            }
            return (
              <tr key={label} className="border-b border-border/30">
                <td className="px-2 py-2 text-muted-foreground">{label}</td>
                <td className="px-2 py-2 font-mono">{baseStr}</td>
                <td className="px-2 py-2 font-mono">{targetStr}</td>
                <td className={cn(
                  "px-2 py-2 font-mono",
                  c.delta != null && c.delta > 0 ? "text-danger" : c.delta != null && c.delta < 0 ? "text-success" : "",
                )}>{deltaStr}</td>
                <td className="px-2 py-2 font-mono text-xs">{fmtChangePct(c.change_pct)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  const renderRankingBlock = <T extends { name?: string; code?: string; change_pct?: number | null }>(
    title: string,
    ranking: RankingComparison<T> | undefined,
    extra?: (item: T) => string,
  ) => {
    if (!ranking) return null;
    const entered = ranking.entered ?? [];
    const exited = ranking.exited ?? [];
    const changes = ranking.rank_changes ?? [];
    return (
      <div className="mb-3">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">
          {title}{" "}
          <span className="font-normal text-muted-foreground/60">
            （基础 {ranking.base_count} / 目标 {ranking.target_count}）
          </span>
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg bg-muted/15 p-2">
            <p className="mb-1 text-[11px] text-primary">新进入</p>
            {entered.length === 0 ? (
              <p className="text-[11px] text-muted-foreground/50">无</p>
            ) : (
              <ul className="space-y-0.5 text-xs">
                {entered.map((e) => (
                  <li key={e.key}>
                    #{e.target_rank} {itemLabel(e.item)}
                    {extra ? ` ${extra(e.item)}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded-lg bg-muted/15 p-2">
            <p className="mb-1 text-[11px] text-muted-foreground">退出</p>
            {exited.length === 0 ? (
              <p className="text-[11px] text-muted-foreground/50">无</p>
            ) : (
              <ul className="space-y-0.5 text-xs">
                {exited.map((e) => (
                  <li key={e.key}>
                    #{e.base_rank} {itemLabel(e.item)}
                    {extra ? ` ${extra(e.item)}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded-lg bg-muted/15 p-2">
            <p className="mb-1 text-[11px] text-muted-foreground">排名变化</p>
            {changes.length === 0 ? (
              <p className="text-[11px] text-muted-foreground/50">无</p>
            ) : (
              <ul className="space-y-0.5 text-xs">
                {changes.map((c) => (
                  <li key={c.key}>
                    {itemLabel(c.target_item)} {c.base_rank}→{c.target_rank}{" "}
                    <span className={cn(
                      "font-mono",
                      c.rank_delta > 0 ? "text-danger" : c.rank_delta < 0 ? "text-success" : "",
                    )}>
                      ({fmtSigned(c.rank_delta, 0)})
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderHighlight = (label: string, h: HighlightComparison<BoardRankItem> | undefined) => {
    if (!h) return null;
    const changedText = h.changed === true ? "已变化" : h.changed === false ? "未变" : "无法判定";
    return (
      <div className="rounded-lg bg-muted/20 p-2">
        <p className="text-[11px] text-muted-foreground">{label} · {changedText}</p>
        <p className="mt-0.5 text-xs">
          基：{itemLabel(h.base)}{" "}
          <span className="font-mono text-muted-foreground">{h.base ? pctCell(h.base.change_pct) : ""}</span>
        </p>
        <p className="text-xs">
          目：{itemLabel(h.target)}{" "}
          <span className="font-mono text-muted-foreground">{h.target ? pctCell(h.target.change_pct) : ""}</span>
        </p>
      </div>
    );
  };

  const addWatch = () => {
    const { next, added } = addCodes(watchCodes, watchInput);
    setWatchInput("");
    if (!added) return;
    setWatchCodes(next); saveWatch(next); refreshWatch(next);
  };

  const removeWatch = (c: string) => {
    const next = watchCodes.filter((x) => x !== c);
    setWatchCodes(next); saveWatch(next); refreshWatch(next);
  };

  // —— 从聚合包取数 ——
  const indices = dr?.market_environment?.indices?.data ?? [];
  const globalIdx = dr?.market_environment?.global_indices?.data ?? [];
  const breadthEnv = dr?.market_environment?.breadth;
  const breadth = breadthEnv?.data ?? null;
  const emotionEnv = dr?.short_term_emotion;
  const emotion = emotionEnv?.data ?? null;
  const amountTop = dr?.capital_activity?.amount_top ?? [];
  const highTurnover = dr?.capital_activity?.high_turnover ?? [];
  const totalAmount = dr?.capital_activity?.total_amount ?? breadth?.total_amount ?? null;
  const sector = dr?.sector_rotation;
  const highlights = sector?.highlights;

  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  const tradeDateLabel = dr?.trade_date ?? "—";
  const generatedAt = dr?.generated_at ?? "—";

  // 顶栏「问 AI」仍用页面指数摘要作通用聊天上下文；AI 当日复盘不再拼装提示词/市场数据。
  const dataSummary = indices.length
    ? indices.map((i) => `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`).join("；")
    : "（指数数据未取到）";

  const runReview = async () => {
    setReviewErr(null);
    setNeedConfig(false);
    const llm = loadLlm();
    if (!llm) { setNeedConfig(true); return; }
    // 生成中禁用按钮，避免并发流；partial/unavailable 仍允许请求（由后端契约约束输出）
    setReviewLoading(true);
    setReview("");
    try {
      // 仅发送 user_request + llm；市场上下文与 system prompt 由服务器生成
      await dailyReviewAnalyzeStream(
        { user_request: null, llm },
        { onDelta: (t) => setReview((r) => r + t) },
      );
    } catch (e) {
      setReviewErr(e instanceof ApiError ? e.message : "复盘失败");
    } finally {
      setReviewLoading(false);
    }
  };

  // 市场广度指标
  const breadthCells = breadth ? [
    { k: "上涨家数", v: numCell(breadth.up_count), up: true as boolean | null },
    { k: "下跌家数", v: numCell(breadth.down_count), up: false as boolean | null },
    { k: "平盘家数", v: numCell(breadth.flat_count), up: null as boolean | null },
    { k: "上涨占比", v: formatUpRatio(breadth.up_ratio), up: null as boolean | null },
    { k: "涨幅≥3%", v: numCell(breadth.up_3pct_count), up: true as boolean | null },
    { k: "跌幅≤-3%", v: numCell(breadth.down_3pct_count), up: false as boolean | null },
    { k: "全市场成交额", v: yi(totalAmount), up: null as boolean | null },
    { k: "样本家数", v: numCell(breadth.stock_count), up: null as boolean | null },
  ] : [];

  const topWarnings = (dr?.warnings || []).filter(Boolean);
  const overall = dr?.status;

  const boardData = (tab: "industry" | "concept" | "region") => {
    const env = sector?.[tab];
    return { env, list: env?.data?.top ?? [], status: env?.status as DataStatus | undefined };
  };
  const activeBoard = boardData(boardTab);

  const highlightCard = (label: string, item: BoardRankItem | null | undefined) => (
    <div className="rounded-lg bg-muted/20 p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      {item ? (
        <>
          <p className="mt-0.5 truncate text-sm font-medium">{item.name}</p>
          <p className={cn("font-mono text-sm font-bold", item.change_pct == null ? "" : pctColor(item.change_pct))}>
            {pctCell(item.change_pct)}
          </p>
        </>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground/50">—</p>
      )}
    </div>
  );

  return (
    <div>
      <PageHeader
        title="每日复盘"
        subtitle={`${tradeDateLabel !== "—" ? tradeDateLabel : today} · 大盘 / 情绪 / 板块涨幅一屏看全`}
        actions={
          <div className="flex items-center gap-2">
            <button onClick={loadDailyReview} className="text-muted-foreground hover:text-primary" title="刷新复盘数据">
              <RefreshCw className={cn("h-4 w-4", !drDone && "animate-spin")} />
            </button>
            <button
              onClick={saveCurrentReview}
              disabled={saveLoading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-muted/40 px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/60 disabled:opacity-50"
              title="显式保存当前复盘到历史库（不自动保存）"
            >
              {saveLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {saveLoading ? "保存中…" : "保存当前复盘"}
            </button>
            <AskAiButton
              context={`今日大盘数据：${dataSummary}`}
              label="问 AI"
              suggestions={["今天大盘怎么走", "哪些指数领涨领跌", "盘面有什么值得注意"]}
            />
          </div>
        }
      />

      {saveMsg && (
        <div className="mb-4 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm text-primary">
          {saveMsg}
        </div>
      )}
      {saveErr && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {saveErr}
        </div>
      )}

      {/* 整体状态 */}
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>交易日期：<b className="text-foreground">{tradeDateLabel}</b></span>
        <span className="text-muted-foreground/40">·</span>
        <span>生成时间：{generatedAt}</span>
        {overall === "normal" && (
          <span className="rounded-full bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground/70">数据正常</span>
        )}
        {overall === "partial" && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] text-warning">部分数据源不可用</span>
        )}
        {overall === "unavailable" && (
          <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-[10px] text-destructive">每日复盘数据暂不可用</span>
        )}
      </div>

      {drErr && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> 每日复盘请求失败：{drErr}
        </div>
      )}

      {(overall === "partial" || overall === "unavailable") && topWarnings.length > 0 && (
        <div
          className={cn(
            "mb-4 rounded-lg border p-3 text-xs",
            overall === "unavailable"
              ? "border-destructive/30 bg-destructive/5 text-destructive"
              : "border-warning/30 bg-warning/5 text-warning",
          )}
        >
          <p className="font-medium">
            {overall === "unavailable" ? "每日复盘数据暂不可用" : "部分数据源不可用"}
          </p>
          <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-[11px] opacity-90">
            {topWarnings.slice(0, 5).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
          {topWarnings.length > 5 && (
            <p className="mt-1 text-[11px] opacity-70">另有 {topWarnings.length - 5} 条提示</p>
          )}
        </div>
      )}

      {/* 1. 大盘指数 */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          大盘指数
          {statusBadge(dr?.data_health?.components?.indices) && (
            <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", statusBadge(dr?.data_health?.components?.indices)!.cls)}>
              {statusBadge(dr?.data_health?.components?.indices)!.text}
            </span>
          )}
        </h3>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {!drDone
          ? [1, 2, 3, 4].map((i) => (
              <GlassCard key={i} className="p-3">
                <p className="text-xs text-muted-foreground">加载中…</p>
                <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
              </GlassCard>
            ))
          : indices.length === 0
            ? [1, 2, 3, 4].map((i) => (
                <GlassCard key={i} className="p-3">
                  <p className="text-xs text-muted-foreground">行情未接通</p>
                  <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
                </GlassCard>
              ))
            : indices.map((i) => (
                <GlassCard key={i.name} className="p-3">
                  <p className="truncate text-xs text-muted-foreground">{i.name}</p>
                  <p className={cn("mt-1 font-mono text-lg font-bold", pctColor(i.change_pct))}>{i.price}</p>
                  <p className={cn("text-xs", pctColor(i.change_pct))}>{i.change_pct > 0 ? "+" : ""}{i.change_pct}%</p>
                </GlassCard>
              ))}
      </div>

      {/* 1b. 全球市场（可选组件） */}
      {(globalIdx.length > 0 || (drDone && dr?.data_health?.components?.global_indices === "unavailable")) && (
        <>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
              <Globe className="h-4 w-4" /> 全球市场
            </h3>
            <span className="text-[11px] text-muted-foreground/50">隔夜外围 · 可选组件</span>
            {dr?.data_health?.components?.global_indices === "unavailable" && (
              <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-[10px] text-destructive">不可用</span>
            )}
          </div>
          {globalIdx.length > 0 ? (
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
              {globalIdx.map((g) => (
                <GlassCard key={g.key} className="p-3">
                  <p className="truncate text-xs text-muted-foreground">{g.name} <span className="text-muted-foreground/40">{g.region}</span></p>
                  <p className={cn("mt-1 font-mono text-lg font-bold", g.change_pct == null ? "text-foreground" : pctColor(g.change_pct))}>{g.price ?? "—"}</p>
                  <p className={cn("text-xs", g.change_pct == null ? "text-muted-foreground" : pctColor(g.change_pct))}>
                    {g.change_pct == null ? "—" : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}
                  </p>
                </GlassCard>
              ))}
            </div>
          ) : (
            <GlassCard className="mb-6">{pending(true, "全球指数暂不可用（不影响 A 股主体）")}</GlassCard>
          )}
        </>
      )}

      {/* 2. 关注股票（独立请求） */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">关注股票</h3>
        {watchCodes.length > 0 && (
          <button onClick={() => refreshWatch(watchCodes)} className="text-muted-foreground hover:text-primary" title="刷新价格">
            {watchLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        )}
      </div>
      <GlassCard className="mb-6">
        <div className="mb-3 flex gap-2">
          <input
            value={watchInput}
            onChange={(e) => setWatchInput(e.target.value.replace(/[^\d,\s]/g, "").slice(0, 80))}
            onKeyDown={(e) => e.key === "Enter" && addWatch()}
            placeholder="加自选：可批量，如 600519 000858"
            className="w-60 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button onClick={addWatch}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25">
            <Plus className="h-4 w-4" /> 增加
          </button>
        </div>
        {watchCodes.length === 0 ? (
          <p className="text-sm text-muted-foreground/60">加上你关注的股票，随时看它们的实时价格与涨跌。数据存本地，不上传。</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {watchCodes.map((c) => {
              const q = watchQuotes[c];
              return (
                <div key={c} className="group relative rounded-lg bg-muted/25 p-3">
                  <button onClick={() => removeWatch(c)} title="移除"
                    className="absolute right-1.5 top-1.5 text-muted-foreground/40 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100">
                    <X className="h-3.5 w-3.5" />
                  </button>
                  <p className="truncate text-xs text-muted-foreground">{q?.name || c}</p>
                  <p className={cn("mt-1 font-mono text-lg font-bold", q ? pctColor(q.change_pct) : "text-muted-foreground/40")}>{q ? q.price : "—"}</p>
                  <p className={cn("text-xs", q ? pctColor(q.change_pct) : "text-muted-foreground/40")}>
                    {q ? `${q.change_pct > 0 ? "+" : ""}${q.change_pct}%` : c}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </GlassCard>

      {/* 3. AI 当日复盘（POST /api/daily-review/analyze，上下文由服务器生成） */}
      <GlassCard glow className="mb-6">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-primary" /> AI 当日复盘</h3>
          <button onClick={runReview} disabled={reviewLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
            {reviewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {review ? "重新复盘" : "让 AI 复盘今天"}
          </button>
        </div>
        {needConfig && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">
            <AlertCircle className="h-4 w-4 shrink-0 text-warning" />
            还没接入 AI。<Link to="/settings" className="text-primary">先去接入你的 AI</Link>，之后一键出复盘。
          </div>
        )}
        {reviewErr && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {reviewErr}
          </div>
        )}
        {review ? (
          <>
            <div className="prose prose-sm prose-invert mt-4 max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{review}</ReactMarkdown></div>
            {!reviewLoading && <div className="mt-3"><SaveNoteButton kind="复盘" title={`每日复盘 ${dr?.trade_date || today}`} content={review} /></div>}
          </>
        ) : !needConfig && !reviewErr && !reviewLoading ? (
          <p className="mt-3 text-sm text-muted-foreground">点上方按钮，由服务器聚合当日数据并按事实/推断/建议结构生成复盘。</p>
        ) : null}
      </GlassCard>

      {/* 4. 市场广度 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Gauge className="h-4 w-4" /> 市场广度</h3>
        {statusBadge(breadthEnv?.status || dr?.data_health?.components?.breadth) && (
          <span className={cn("rounded-full px-2 py-0.5 text-[10px]", statusBadge(breadthEnv?.status || dr?.data_health?.components?.breadth)!.cls)}>
            {statusBadge(breadthEnv?.status || dr?.data_health?.components?.breadth)!.text}
          </span>
        )}
      </div>
      <GlassCard className="mb-6">
        {!drDone && pending(false)}
        {drDone && !breadth && (
          <p className="py-4 text-center text-sm text-muted-foreground/60">市场广度数据暂不可用</p>
        )}
        {breadth && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { k: "大盘宽度", v: breadthLabel(breadth.up_ratio), hint: "冰点 / 偏弱 / 中性 / 偏强 / 普涨" },
                { k: "题材投机", v: speculationLabel(emotion?.zt_count), hint: "冰点 / 普通 / 活跃 / 亢奋（按涨停家数）" },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-4">
                  <p className="text-xs text-muted-foreground">{m.k}</p>
                  <p className="mt-1 text-2xl font-bold text-primary">{m.v}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground/60">{m.hint}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-4">
              {breadthCells.map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2 text-center">
                  <p className="truncate text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.up === null ? "text-foreground" : c.up ? "text-danger" : "text-success")}>{c.v}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </GlassCard>

      {/* 5. 短线情绪 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Flame className="h-4 w-4" /> 短线情绪</h3>
        <span className="text-[11px] text-muted-foreground/50">连板股 · 打板情绪</span>
        {emotion?.date && <span className="ml-auto text-[11px] text-muted-foreground/50">{emotion.date}</span>}
        {statusBadge(emotionEnv?.status) && (
          <span className={cn("rounded-full px-2 py-0.5 text-[10px]", statusBadge(emotionEnv?.status)!.cls)}>
            {statusBadge(emotionEnv?.status)!.text}
          </span>
        )}
      </div>
      <GlassCard className="mb-6">
        {!drDone && pending(false)}
        {drDone && !emotion && pending(true, "短线情绪暂不可用")}
        {emotion && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { k: "涨停", v: numCell(emotion.zt_count), cls: "text-danger" },
                { k: "跌停", v: numCell(emotion.dt_count), cls: "text-success" },
                { k: "最高连板", v: emotion.max_boards == null ? "—" : `${emotion.max_boards} 板`, cls: "text-primary" },
                { k: "连板（2板+）", v: emotion.lianban_count == null ? "—" : `${emotion.lianban_count} 家`, cls: "text-primary" },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/25 p-3 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-xl font-bold", c.cls)}>{c.v}</p>
                </div>
              ))}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[
                { k: "封板率", v: emotion.seal_rate, hint: "封住 / 尝试涨停", strong: true },
                { k: "炸板率", v: emotion.break_rate, hint: "炸板 / 尝试涨停", strong: false },
                { k: "晋级率", v: emotion.promotion_rate, hint: "昨涨停今又停", strong: true },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.strong ? "text-danger" : "text-success")}>
                    {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground/50">{c.hint}</p>
                </div>
              ))}
            </div>
            <div className="mt-3">
              <p className="mb-1.5 text-[11px] text-muted-foreground">连板股（2 板以上连续涨停）</p>
              {!emotion.lianban_stocks?.length ? (
                <p className="text-xs text-muted-foreground/50">今日无 2 板以上个股</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                        {["名称", "连板", "现价", "涨停%", "成交额", "流通市值", "概念"].map((h) => (
                          <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {emotion.lianban_stocks.map((s) => (
                        <tr key={s.code} className="border-b border-border/30">
                          <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
                          <td className="px-2 py-2 font-mono">{s.price}</td>
                          <td className="px-2 py-2 font-mono text-danger">+{s.pct}%</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.float_cap)}</td>
                          <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </GlassCard>

      {/* 6. 全市场成交额榜（优先 amount_top） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <BarChart3 className="h-4 w-4" /> 全市场成交额榜
        </h3>
        <span className="text-[11px] text-muted-foreground/50">来自全 A 快照 · 按成交额</span>
      </div>
      <GlassCard className="mb-6">
        {!drDone && pending(false)}
        {drDone && amountTop.length === 0 && pending(true, "成交额榜暂不可用")}
        {amountTop.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["#", "名称", "现价", "涨跌%", "成交额", "换手%", "总市值"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {amountTop.slice(0, 20).map((s: MarketSnapshotItem, i) => (
                  <tr key={s.code} className="border-b border-border/30">
                    <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                    <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                    <td className="px-2 py-2 font-mono">{s.price ?? "—"}</td>
                    <td className={cn("px-2 py-2 font-mono", s.change_pct == null ? "text-muted-foreground" : pctColor(s.change_pct))}>
                      {pctCell(s.change_pct)}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono">{yi(s.amount)}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.turnover_pct == null ? "—" : `${s.turnover_pct}%`}</td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.market_cap)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {highTurnover.length > 0 && (
          <div className="mt-4 border-t border-border/40 pt-3">
            <p className="mb-2 text-xs text-muted-foreground">高换手（≥15%）Top</p>
            <div className="flex flex-wrap gap-2">
              {highTurnover.slice(0, 12).map((s) => (
                <span key={s.code} className="rounded-md bg-muted/30 px-2 py-1 text-xs">
                  {s.name} <span className="font-mono text-primary">{s.turnover_pct ?? "—"}%</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </GlassCard>

      {/* 7. 板块强弱亮点 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <TrendingUp className="h-4 w-4" /> 板块强弱亮点
        </h3>
        <span className="text-[11px] text-muted-foreground/50">按涨跌幅 · 非资金流</span>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {highlightCard("最强行业", highlights?.strongest_industry)}
        {highlightCard("最弱行业", highlights?.weakest_industry)}
        {highlightCard("最强概念", highlights?.strongest_concept)}
        {highlightCard("最弱概念", highlights?.weakest_concept)}
        {highlightCard("最强地域", highlights?.strongest_region)}
        {highlightCard("最弱地域", highlights?.weakest_region)}
      </div>

      {/* 8. 板块涨幅排名 */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <Layers className="h-4 w-4" /> 板块涨幅排名
        </h3>
        <div className="flex gap-1">
          {([
            ["industry", "行业涨幅排名"],
            ["concept", "概念涨幅排名"],
            ["region", "地域涨幅排名"],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setBoardTab(key)}
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] transition-colors",
                boardTab === key ? "bg-primary/20 text-primary" : "bg-muted/30 text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {statusBadge(activeBoard.status) && (
          <span className={cn("rounded-full px-2 py-0.5 text-[10px]", statusBadge(activeBoard.status)!.cls)}>
            {statusBadge(activeBoard.status)!.text}
          </span>
        )}
      </div>
      <GlassCard className="mb-6">
        {!drDone && pending(false)}
        {drDone && activeBoard.status === "unavailable" && pending(true, "该板块排名暂不可用")}
        {drDone && activeBoard.status !== "unavailable" && activeBoard.list.length === 0 && pending(true)}
        {activeBoard.list.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["#", "板块名称", "涨跌幅", "上涨", "下跌", "领涨股票", "领涨%"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {activeBoard.list.slice(0, boardTab === "region" ? 5 : 10).map((s, i) => (
                  <tr key={s.code} className="border-b border-border/30">
                    <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                    <td className="px-2 py-2 font-medium">{s.name}</td>
                    <td className={cn("px-2 py-2 font-mono", s.change_pct == null ? "text-muted-foreground" : pctColor(s.change_pct))}>
                      {pctCell(s.change_pct)}
                    </td>
                    <td className="px-2 py-2 font-mono text-danger">{numCell(s.up_count)}</td>
                    <td className="px-2 py-2 font-mono text-success">{numCell(s.down_count)}</td>
                    <td className="px-2 py-2 text-muted-foreground">{s.leader || "—"}</td>
                    <td className={cn("px-2 py-2 font-mono", s.leader_change_pct == null ? "text-muted-foreground" : pctColor(s.leader_change_pct))}>
                      {pctCell(s.leader_change_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {/* 最弱一侧简表（行业/概念） */}
        {boardTab !== "region" && (sector?.[boardTab]?.data?.bottom?.length ?? 0) > 0 && (
          <div className="mt-4 border-t border-border/40 pt-3">
            <p className="mb-2 flex items-center gap-1 text-xs text-muted-foreground">
              <TrendingDown className="h-3.5 w-3.5" /> 涨幅排名靠后（最弱）
            </p>
            <div className="flex flex-wrap gap-2">
              {(sector?.[boardTab]?.data?.bottom ?? []).slice(0, 5).map((s) => (
                <span key={s.code} className="rounded-md bg-muted/30 px-2 py-1 text-xs">
                  {s.name}{" "}
                  <span className={cn("font-mono", s.change_pct == null ? "" : pctColor(s.change_pct))}>
                    {pctCell(s.change_pct)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </GlassCard>

      {/* 9. 历史复盘（显式保存；只读浏览；不替换当前实时数据） */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <History className="h-4 w-4" /> 历史复盘
        </h3>
        <span className="text-[11px] text-muted-foreground/50">仅展示已保存快照 · 不自动写入</span>
      </div>
      <GlassCard className="mb-6">
        {/* 快照对比控制区 */}
        <div className="mb-4 rounded-lg border border-border/50 bg-muted/10 p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h4 className="flex items-center gap-1.5 text-sm font-semibold">
              <GitCompare className="h-4 w-4 text-primary" /> 快照对比
            </h4>
            <span className="text-[11px] text-muted-foreground/50">结构化差异 · 不调用 AI</span>
          </div>
          <div className="mb-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
            <p>
              基础快照：{" "}
              {baseSnapshot ? (
                <b className="text-foreground">
                  {baseSnapshot.trade_date} / {baseSnapshot.generated_at} / #{baseSnapshot.id}
                </b>
              ) : (
                <span className="text-muted-foreground/60">未选择</span>
              )}
            </p>
            <p>
              目标快照：{" "}
              {targetSnapshot ? (
                <b className="text-foreground">
                  {targetSnapshot.trade_date} / {targetSnapshot.generated_at} / #{targetSnapshot.id}
                </b>
              ) : (
                <span className="text-muted-foreground/60">未选择</span>
              )}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={runCompare}
              disabled={!baseSnapshot || !targetSnapshot || comparisonLoading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
            >
              {comparisonLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitCompare className="h-3.5 w-3.5" />}
              {comparisonLoading ? "对比中…" : "开始对比"}
            </button>
            <button
              type="button"
              onClick={clearCompareSelection}
              className="rounded-lg bg-muted/30 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
            >
              清除选择
            </button>
          </div>
          {comparisonError && (
            <div className="mt-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {comparisonError}
            </div>
          )}
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label className="text-xs text-muted-foreground">
            交易日期
            <input
              type="date"
              value={histFilterDate}
              onChange={(e) => onHistDateChange(e.target.value)}
              className="ml-2 rounded-lg border border-border bg-black/20 px-2 py-1.5 text-sm outline-none focus:border-primary/50"
            />
          </label>
          {histFilterDate && (
            <button
              type="button"
              onClick={() => onHistDateChange("")}
              className="text-xs text-muted-foreground hover:text-primary"
            >
              清除筛选
            </button>
          )}
          <button
            type="button"
            onClick={() => loadHistory()}
            disabled={histLoading}
            className="ml-auto text-muted-foreground hover:text-primary"
            title="刷新历史列表"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", histLoading && "animate-spin")} />
          </button>
        </div>

        {histErr && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> 历史记录加载失败：{histErr}
          </div>
        )}

        {histLoading && !histDone && pending(false)}
        {histLoading && histDone && (
          <p className="py-2 text-center text-xs text-muted-foreground/60">刷新中…</p>
        )}
        {!histLoading && histDone && !histErr && histItems.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground/60">暂无已保存的每日复盘</p>
        )}

        {histItems.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["交易日期", "生成时间", "保存时间", "状态", "schema", ""].map((h) => (
                    <th key={h || "act"} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {histItems.map((item) => {
                  const badge = statusBadge(item.status);
                  const isBase = baseSnapshot?.id === item.id;
                  const isTarget = targetSnapshot?.id === item.id;
                  return (
                    <tr
                      key={item.id}
                      className={cn(
                        "border-b border-border/30",
                        (isBase || isTarget) && "bg-primary/5",
                      )}
                    >
                      <td className="whitespace-nowrap px-2 py-2 font-mono font-medium">
                        {item.trade_date}
                        {isBase && (
                          <span className="ml-1 rounded bg-primary/20 px-1 text-[10px] text-primary">基础</span>
                        )}
                        {isTarget && (
                          <span className="ml-1 rounded bg-warning/20 px-1 text-[10px] text-warning">目标</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-xs text-muted-foreground">{item.generated_at}</td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-xs text-muted-foreground">{item.created_at}</td>
                      <td className="px-2 py-2">
                        {badge ? (
                          <span className={cn("rounded-full px-2 py-0.5 text-[10px]", badge.cls)}>{badge.text}</span>
                        ) : (
                          item.status
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground/70">{item.schema_version}</td>
                      <td className="px-2 py-2 text-right">
                        <div className="flex flex-wrap justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => setBaseSnapshot(item)}
                            className="rounded-md bg-muted/40 px-1.5 py-1 text-[11px] text-muted-foreground hover:text-primary"
                          >
                            设为基础
                          </button>
                          <button
                            type="button"
                            onClick={() => setTargetSnapshot(item)}
                            className="rounded-md bg-muted/40 px-1.5 py-1 text-[11px] text-muted-foreground hover:text-warning"
                          >
                            设为目标
                          </button>
                          <button
                            type="button"
                            onClick={() => openHistoryDetail(item.id)}
                            className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/20"
                          >
                            <Eye className="h-3 w-3" /> 查看
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {(histItems.length > 0 || histOffset > 0) && (
          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span>第 {histPage} 页</span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={histPrevDisabled}
                onClick={() => {
                  const next = Math.max(0, histOffset - HISTORY_LIMIT);
                  setHistOffset(next);
                  loadHistory({ offset: next });
                }}
                className="inline-flex items-center gap-1 rounded-md bg-muted/30 px-2 py-1 disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" /> 上一页
              </button>
              <button
                type="button"
                disabled={histNextDisabled}
                onClick={() => {
                  const next = histOffset + HISTORY_LIMIT;
                  setHistOffset(next);
                  loadHistory({ offset: next });
                }}
                className="inline-flex items-center gap-1 rounded-md bg-muted/30 px-2 py-1 disabled:opacity-40"
              >
                下一页 <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {/* 历史详情：页面内只读卡片，不替换当前实时 dr */}
        {selectedSnapshotId != null && (
          <div className="mt-4 border-t border-border/40 pt-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-sm font-semibold">历史快照详情 #{selectedSnapshotId}</h4>
              <button
                type="button"
                onClick={closeHistoryDetail}
                className="text-muted-foreground hover:text-foreground"
                title="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {detailLoading && (
              <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> 加载详情…
              </p>
            )}
            {detailError && (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" /> {detailError}
              </div>
            )}
            {selectedSnapshot && !detailLoading && (() => {
              const snap = selectedSnapshot;
              const rev = snap.review;
              const b = rev.market_environment?.breadth?.data;
              const emo = rev.short_term_emotion?.data;
              const hl = rev.sector_rotation?.highlights;
              const cap = rev.capital_activity;
              const snapBadge = statusBadge(snap.status);
              const warnList = (rev.warnings || []).filter(Boolean).slice(0, 5);
              return (
                <div className="space-y-4 text-sm">
                  <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>交易日期：<b className="text-foreground">{snap.trade_date}</b></span>
                    <span>生成：{snap.generated_at}</span>
                    <span>保存：{snap.created_at}</span>
                    <span>schema：{snap.schema_version}</span>
                    {snapBadge && (
                      <span className={cn("rounded-full px-2 py-0.5 text-[10px]", snapBadge.cls)}>{snapBadge.text}</span>
                    )}
                  </div>

                  {warnList.length > 0 && (
                    <div className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning">
                      <p className="font-medium">warnings</p>
                      <ul className="mt-1 list-inside list-disc space-y-0.5 opacity-90">
                        {warnList.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">市场广度</p>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {[
                        { k: "上涨家数", v: numCell(b?.up_count) },
                        { k: "下跌家数", v: numCell(b?.down_count) },
                        { k: "平盘家数", v: numCell(b?.flat_count) },
                        { k: "上涨占比", v: formatUpRatio(b?.up_ratio) },
                        { k: "涨幅≥3%", v: numCell(b?.up_3pct_count) },
                        { k: "跌幅≤-3%", v: numCell(b?.down_3pct_count) },
                        { k: "全市场成交额", v: yi(cap?.total_amount ?? b?.total_amount) },
                      ].map((c) => (
                        <div key={c.k} className="rounded-lg bg-muted/20 p-2 text-center">
                          <p className="text-[11px] text-muted-foreground">{c.k}</p>
                          <p className="mt-0.5 font-mono text-sm font-bold">{c.v}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">短线情绪</p>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {[
                        { k: "涨停", v: numCell(emo?.zt_count) },
                        { k: "跌停", v: numCell(emo?.dt_count) },
                        { k: "炸板", v: numCell(emo?.zb_count) },
                        { k: "最高连板", v: emo?.max_boards == null ? "—" : `${emo.max_boards}` },
                        { k: "连板股数量", v: numCell(emo?.lianban_count) },
                        { k: "封板率", v: rateCell(emo?.seal_rate) },
                        { k: "炸板率", v: rateCell(emo?.break_rate) },
                      ].map((c) => (
                        <div key={c.k} className="rounded-lg bg-muted/20 p-2 text-center">
                          <p className="text-[11px] text-muted-foreground">{c.k}</p>
                          <p className="mt-0.5 font-mono text-sm font-bold">{c.v}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">板块亮点</p>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {[
                        ["最强行业", hl?.strongest_industry],
                        ["最弱行业", hl?.weakest_industry],
                        ["最强概念", hl?.strongest_concept],
                        ["最弱概念", hl?.weakest_concept],
                        ["最强地域", hl?.strongest_region],
                        ["最弱地域", hl?.weakest_region],
                      ].map(([label, item]) => {
                        const it = item as BoardRankItem | null | undefined;
                        return (
                          <div key={String(label)} className="rounded-lg bg-muted/20 p-2">
                            <p className="text-[11px] text-muted-foreground">{label as string}</p>
                            {it ? (
                              <>
                                <p className="truncate text-sm font-medium">{it.name}</p>
                                <p className={cn("font-mono text-xs", it.change_pct == null ? "" : pctColor(it.change_pct))}>
                                  {pctCell(it.change_pct)}
                                </p>
                              </>
                            ) : (
                              <p className="text-sm text-muted-foreground/50">—</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">
                      成交活跃 · 全市场成交额 {yi(cap?.total_amount)}
                    </p>
                    {(cap?.amount_top?.length ?? 0) > 0 && (
                      <div className="mb-2">
                        <p className="mb-1 text-[11px] text-muted-foreground">成交额 Top 10</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(cap?.amount_top ?? []).slice(0, 10).map((s) => (
                            <span key={s.code} className="rounded-md bg-muted/30 px-2 py-1 text-xs">
                              {s.name}{" "}
                              <span className="font-mono text-muted-foreground">{yi(s.amount)}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {(cap?.high_turnover?.length ?? 0) > 0 && (
                      <div>
                        <p className="mb-1 text-[11px] text-muted-foreground">高换手 Top 10</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(cap?.high_turnover ?? []).slice(0, 10).map((s) => (
                            <span key={s.code} className="rounded-md bg-muted/30 px-2 py-1 text-xs">
                              {s.name}{" "}
                              <span className="font-mono text-primary">
                                {s.turnover_pct == null ? "—" : `${s.turnover_pct}%`}
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {(cap?.amount_top?.length ?? 0) === 0 && (cap?.high_turnover?.length ?? 0) === 0 && (
                      <p className="text-xs text-muted-foreground/50">无成交活跃明细</p>
                    )}
                  </div>
                </div>
              );
            })()}
          </div>
        )}

        {/* 快照对比结果（只读；不替换实时复盘） */}
        {comparison && (
          <div className="mt-4 border-t border-border/40 pt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h4 className="flex items-center gap-1.5 text-sm font-semibold">
                <GitCompare className="h-4 w-4 text-primary" /> 快照对比结果
              </h4>
              <button
                type="button"
                onClick={() => { setComparison(null); setComparisonError(null); }}
                className="text-muted-foreground hover:text-foreground"
                title="关闭对比结果"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mb-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
              <span>
                基础：{comparison.base.trade_date ?? "—"} / {comparison.base.generated_at ?? "—"} /{" "}
                {comparison.base.status ?? "—"}
              </span>
              <span>
                目标：{comparison.target.trade_date ?? "—"} / {comparison.target.generated_at ?? "—"} /{" "}
                {comparison.target.status ?? "—"}
              </span>
              {comparisonStatusLabel(comparison.comparison_status) && (
                <span className={cn(
                  "rounded-full px-2 py-0.5 text-[10px]",
                  comparisonStatusLabel(comparison.comparison_status)!.cls,
                )}>
                  {comparisonStatusLabel(comparison.comparison_status)!.text}
                </span>
              )}
              {!comparison.schema_compatible && (
                <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] text-warning">
                  快照结构版本不一致
                </span>
              )}
            </div>

            {(comparison.warnings?.length ?? 0) > 0 && (
              <div className="mb-3 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning">
                <p className="font-medium">比较提示</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5 opacity-90">
                  {comparison.warnings.slice(0, 5).map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
                {comparison.warnings.length > 5 && (
                  <p className="mt-1 opacity-70">另有 {comparison.warnings.length - 5} 条</p>
                )}
              </div>
            )}
            {(comparison.unknowns?.length ?? 0) > 0 && (
              <div className="mb-3 rounded-lg border border-border/50 bg-muted/10 p-3 text-xs text-muted-foreground">
                <p className="font-medium text-foreground/80">不可比较项</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {comparison.unknowns.slice(0, 10).map((u, i) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
                {comparison.unknowns.length > 10 && (
                  <p className="mt-1 opacity-70">另有 {comparison.unknowns.length - 10} 条</p>
                )}
              </div>
            )}

            <div className="mb-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground">
                市场广度
                {!comparison.market_breadth?.available && (
                  <span className="ml-2 text-warning">市场广度仅部分可比较</span>
                )}
              </p>
              {renderNumericTable([
                { label: "股票总数", c: comparison.market_breadth.stock_count },
                { label: "有效涨跌幅数量", c: comparison.market_breadth.valid_count },
                { label: "上涨家数", c: comparison.market_breadth.up_count },
                { label: "下跌家数", c: comparison.market_breadth.down_count },
                { label: "平盘家数", c: comparison.market_breadth.flat_count },
                { label: "上涨占比", c: comparison.market_breadth.up_ratio, kind: "ratio" },
                { label: "涨幅≥3%", c: comparison.market_breadth.up_3pct_count },
                { label: "跌幅≤-3%", c: comparison.market_breadth.down_3pct_count },
                { label: "全市场成交额", c: comparison.market_breadth.total_amount, kind: "amount" },
                { label: "有效成交额数量", c: comparison.market_breadth.amount_valid_count },
              ])}
            </div>

            <div className="mb-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground">
                短线情绪
                {!comparison.short_term_emotion?.available && (
                  <span className="ml-2 text-warning">短线情绪仅部分可比较</span>
                )}
              </p>
              {renderNumericTable([
                { label: "涨停家数", c: comparison.short_term_emotion.zt_count },
                { label: "跌停家数", c: comparison.short_term_emotion.dt_count },
                { label: "炸板家数", c: comparison.short_term_emotion.zb_count },
                { label: "最高连板", c: comparison.short_term_emotion.max_boards },
                { label: "连板股数量", c: comparison.short_term_emotion.lianban_count },
                { label: "封板率", c: comparison.short_term_emotion.seal_rate, kind: "rate" },
                { label: "炸板率", c: comparison.short_term_emotion.break_rate, kind: "rate" },
                { label: "晋级率", c: comparison.short_term_emotion.promotion_rate, kind: "rate" },
                { label: "昨日涨停数量", c: comparison.short_term_emotion.yzt_count },
              ])}
            </div>

            <div className="mb-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground">板块亮点</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {renderHighlight("最强行业", comparison.sector_rotation?.highlights?.strongest_industry)}
                {renderHighlight("最弱行业", comparison.sector_rotation?.highlights?.weakest_industry)}
                {renderHighlight("最强概念", comparison.sector_rotation?.highlights?.strongest_concept)}
                {renderHighlight("最弱概念", comparison.sector_rotation?.highlights?.weakest_concept)}
                {renderHighlight("最强地域", comparison.sector_rotation?.highlights?.strongest_region)}
                {renderHighlight("最弱地域", comparison.sector_rotation?.highlights?.weakest_region)}
              </div>
            </div>

            <div className="mb-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground">板块排名变化</p>
              {renderRankingBlock(
                "行业涨幅 Top",
                comparison.sector_rotation?.industry?.top,
                (it) => pctCell(it.change_pct),
              )}
              {renderRankingBlock(
                "行业涨幅 Bottom",
                comparison.sector_rotation?.industry?.bottom,
                (it) => pctCell(it.change_pct),
              )}
              {renderRankingBlock(
                "概念涨幅 Top",
                comparison.sector_rotation?.concept?.top,
                (it) => pctCell(it.change_pct),
              )}
              {renderRankingBlock(
                "概念涨幅 Bottom",
                comparison.sector_rotation?.concept?.bottom,
                (it) => pctCell(it.change_pct),
              )}
              {renderRankingBlock(
                "地域涨幅 Top",
                comparison.sector_rotation?.region?.top,
                (it) => pctCell(it.change_pct),
              )}
              {renderRankingBlock(
                "地域涨幅 Bottom",
                comparison.sector_rotation?.region?.bottom,
                (it) => pctCell(it.change_pct),
              )}
            </div>

            <div className="mb-2">
              <p className="mb-2 text-xs font-medium text-muted-foreground">成交活跃</p>
              {renderNumericTable([
                { label: "全市场成交额", c: comparison.capital_activity.total_amount, kind: "amount" },
                { label: "有效成交额数量", c: comparison.capital_activity.amount_valid_count },
              ])}
              <div className="mt-3">
                {renderRankingBlock(
                  "成交额榜",
                  comparison.capital_activity?.amount_top,
                  (it) => yi(it.amount),
                )}
                {renderRankingBlock(
                  "高换手榜",
                  comparison.capital_activity?.high_turnover,
                  (it) => (it.turnover_pct == null ? "—" : `${it.turnover_pct}%`),
                )}
              </div>
            </div>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
