// 板块热力图数据转换与状态语义。
//
// 设计原则：
// - 面积 = 真实成交额（amount），缺失不替换为市值 / 家数 / 估算；
// - 颜色 = 真实涨跌幅（change_pct），红涨绿跌中性灰；
// - fail-closed：数据不可用 / 过期 / 部分缺失显式表达，不伪造 0；
// - 概念板块过多时按成交额取主要板块，其余聚合为"其他 N 个"（纯 UI 聚合，非真实板块）。

import type { BoardRankItem, BoardRankingData, TimedComponentEnvelope } from "./api";
import { formatSectorPercent } from "./sectorMarketView.ts";

/** 热力图单个矩形的数据结构（ECharts treemap data item）。 */
export interface HeatmapItem {
  name: string;
  value: number;
  itemStyle: { color: string };
  data: BoardRankItem & { isAggregate?: boolean; aggregateCount?: number };
}

/** 热力图状态信封。 */
export type HeatmapStatus = "loading" | "normal" | "partial" | "stale" | "unavailable";

export interface HeatmapState {
  status: HeatmapStatus;
  items: HeatmapItem[];
  /** 被聚合到"其他"的板块数量 */
  aggregateCount: number;
  /** 被聚合板块的总成交额（用于"其他"矩形面积） */
  aggregateAmount: number;
  warnings: string[];
  /** 数据更新时间（来自信封 fetched_at） */
  updatedAt: string | null;
  /** 板块总数（来自 data.total） */
  totalCount: number;
  /** 有有效成交额的板块数 */
  validAmountCount: number;
}

// ── 颜色映射 ──────────────────────────────────────────────────────────

/** 涨跌幅颜色映射的视觉饱和上限（超过此值颜色不再加深）。 */
const COLOR_SATURATION_PCT = 5;

/** 接近 0 的阈值（绝对值小于此值视为中性灰）。 */
const NEUTRAL_THRESHOLD_PCT = 0.05;

// 深色主题下的颜色阶（Vibe 深色视觉体系）
const RED_DEEP = "#b91c1c";   // 大涨
const RED_MID = "#dc2626";
const RED_LIGHT = "#ef4444";  // 小涨
const NEUTRAL = "#3f3f46";    // 接近 0（深灰，zinc-700）
const GREEN_LIGHT = "#10b981"; // 小跌
const GREEN_MID = "#059669";
const GREEN_DEEP = "#047857";  // 大跌

function lerpColor(a: string, b: string, t: number): string {
  const ah = parseInt(a.slice(1), 16);
  const bh = parseInt(b.slice(1), 16);
  const ar = (ah >> 16) & 255, ag = (ah >> 8) & 255, ab = ah & 255;
  const br = (bh >> 16) & 255, bg = (bh >> 8) & 255, bb = bh & 255;
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bl = Math.round(ab + (bb - ab) * t);
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, "0")}`;
}

/** 根据涨跌幅返回矩形颜色（红涨绿跌，接近 0 中性灰）。 */
export function heatmapColor(changePct: number | null | undefined): string {
  if (changePct == null || !Number.isFinite(changePct)) return NEUTRAL;
  if (Math.abs(changePct) < NEUTRAL_THRESHOLD_PCT) return NEUTRAL;
  const t = Math.min(Math.abs(changePct) / COLOR_SATURATION_PCT, 1);
  if (changePct > 0) {
    return t < 0.5
      ? lerpColor(RED_LIGHT, RED_MID, t * 2)
      : lerpColor(RED_MID, RED_DEEP, (t - 0.5) * 2);
  }
  return t < 0.5
    ? lerpColor(GREEN_LIGHT, GREEN_MID, t * 2)
    : lerpColor(GREEN_MID, GREEN_DEEP, (t - 0.5) * 2);
}

// ── 成交额格式化 ──────────────────────────────────────────────────────

/** 成交额格式化为可读字符串（元 → 亿 / 万）。 */
export function formatAmount(amount: number | null | undefined): string {
  if (amount == null || !Number.isFinite(amount) || amount < 0) return "—";
  if (amount >= 1e8) return `${(amount / 1e8).toFixed(1)} 亿`;
  if (amount >= 1e4) return `${(amount / 1e4).toFixed(0)} 万`;
  return `${amount.toFixed(0)} 元`;
}

// ── 数据转换 ──────────────────────────────────────────────────────────

export interface TransformOptions {
  /** 最多展示的板块数（按成交额降序取前 N），其余聚合为"其他" */
  maxItems: number;
}

const DEFAULT_OPTIONS: TransformOptions = { maxItems: 30 };

/**
 * 将 BoardRankingData（amount_top）转换为热力图 treemap 数据。
 *
 * fail-closed 规则：
 * - amount 为 null / 非有限数的板块不进入热力图（不计入面积）；
 * - 不因为 amount 缺失而改用市值 / 家数 / 随机权重；
 * - 全部 amount 缺失时返回空 items + unavailable 语义由调用方判定。
 */
export function transformBoardRankingToHeatmap(
  data: BoardRankingData | null,
  options: Partial<TransformOptions> = {},
): { items: HeatmapItem[]; aggregateCount: number; aggregateAmount: number; validAmountCount: number } {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  if (!data || !Array.isArray(data.amount_top)) {
    return { items: [], aggregateCount: 0, aggregateAmount: 0, validAmountCount: 0 };
  }

  // 只保留有真实成交额的板块
  const withAmount = data.amount_top.filter(
    (b): b is BoardRankItem & { amount: number } =>
      b.amount != null && Number.isFinite(b.amount) && b.amount > 0,
  );

  const main = withAmount.slice(0, opts.maxItems);
  const rest = withAmount.slice(opts.maxItems);
  const aggregateAmount = rest.reduce((sum, b) => sum + b.amount, 0);

  const items: HeatmapItem[] = main.map((b) => ({
    name: b.name,
    value: b.amount,
    itemStyle: { color: heatmapColor(b.change_pct) },
    data: b,
  }));

  if (rest.length > 0 && aggregateAmount > 0) {
    items.push({
      name: `其他 ${rest.length} 个`,
      value: aggregateAmount,
      itemStyle: { color: NEUTRAL },
      data: {
        code: "__aggregate__",
        name: `其他 ${rest.length} 个`,
        change_pct: null,
        amount: aggregateAmount,
        turnover_pct: null,
        market_cap: null,
        up_count: null,
        down_count: null,
        up_ratio: null,
        leader: null,
        leader_change_pct: null,
        isAggregate: true,
        aggregateCount: rest.length,
      },
    });
  }

  return {
    items,
    aggregateCount: rest.length,
    aggregateAmount,
    validAmountCount: withAmount.length,
  };
}

/** 从 TimedComponentEnvelope 解析热力图状态（fail-closed 语义）。 */
export function resolveHeatmapState(
  envelope: TimedComponentEnvelope<BoardRankingData> | null,
  loading: boolean,
  error: boolean,
  options?: Partial<TransformOptions>,
): HeatmapState {
  if (loading) {
    return {
      status: "loading",
      items: [],
      aggregateCount: 0,
      aggregateAmount: 0,
      warnings: [],
      updatedAt: null,
      totalCount: 0,
      validAmountCount: 0,
    };
  }

  if (error || !envelope) {
    return {
      status: "unavailable",
      items: [],
      aggregateCount: 0,
      aggregateAmount: 0,
      warnings: ["板块数据请求失败"],
      updatedAt: null,
      totalCount: 0,
      validAmountCount: 0,
    };
  }

  const status = envelope.status;
  const isStale = envelope.is_stale === true;
  const data = envelope.data;

  const transformed = transformBoardRankingToHeatmap(data, options);

  // 全部成交额缺失 → 不可用（不伪造 0 面积）
  if (transformed.validAmountCount === 0) {
    return {
      status: "unavailable",
      items: [],
      aggregateCount: 0,
      aggregateAmount: 0,
      warnings: [...(envelope.warnings ?? []), "当前无可用板块成交额数据"],
      updatedAt: envelope.fetched_at ?? null,
      totalCount: data?.total ?? 0,
      validAmountCount: 0,
    };
  }

  // 部分成交额缺失 → partial（但仍展示有数据的板块）
  const totalBoards = data?.total ?? 0;
  const partialAmount = totalBoards > 0 && transformed.validAmountCount < totalBoards;

  let heatmapStatus: HeatmapStatus = "normal";
  if (status === "unavailable") heatmapStatus = "unavailable";
  else if (isStale) heatmapStatus = "stale";
  else if (status === "partial" || partialAmount) heatmapStatus = "partial";

  return {
    status: heatmapStatus,
    items: transformed.items,
    aggregateCount: transformed.aggregateCount,
    aggregateAmount: transformed.aggregateAmount,
    warnings: envelope.warnings ?? [],
    updatedAt: envelope.fetched_at ?? null,
    totalCount: totalBoards,
    validAmountCount: transformed.validAmountCount,
  };
}

// ── Hover tooltip 格式化 ──────────────────────────────────────────────

export interface HeatmapTooltipData {
  name: string;
  changePct: number | null;
  amount: number | null;
  upCount: number | null;
  downCount: number | null;
  leader: string | null;
  leaderChangePct: number | null;
  isAggregate: boolean;
  aggregateCount: number;
}

export function formatHeatmapTooltip(item: HeatmapItem): string {
  const d = item.data;
  const lines: string[] = [];
  lines.push(`<div style="font-weight:600;margin-bottom:4px">${d.name}</div>`);
  lines.push(`<div>涨跌幅：<span style="color:${heatmapColor(d.change_pct)};font-weight:600">${formatSectorPercent(d.change_pct)}</span></div>`);
  lines.push(`<div>成交额：${formatAmount(d.amount)}</div>`);
  if (d.up_count != null) lines.push(`<div>上涨：${d.up_count} 家</div>`);
  if (d.down_count != null) lines.push(`<div>下跌：${d.down_count} 家</div>`);
  if (d.leader) {
    const leaderStr = d.leader_change_pct != null
      ? `${d.leader} (${formatSectorPercent(d.leader_change_pct)})`
      : d.leader;
    lines.push(`<div>领涨：${leaderStr}</div>`);
  }
  return lines.join("");
}
