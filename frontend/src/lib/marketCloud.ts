/**
 * 市场云图数据转换与颜色映射
 *
 * V1 语义：
 * - 个股 tile 面积 = 真实流通市值（float_market_cap）
 * - 个股 tile 颜色 = 当日涨跌幅（红涨绿跌，中性灰）
 * - 行业分组：个股按行业聚合，行业区域面积 = 行业内个股流通市值之和
 *
 * fail-closed：
 * - 缺流通市值或缺涨跌幅的股票不进入云图，计入 partial
 * - 不伪造 0，不估算
 */

export interface MarketCloudStock {
  code: string;
  name: string;
  price: number | null;
  change_pct: number;
  amount: number | null;
  float_market_cap: number;
  turnover_pct: number | null;
  industry: string;
}

export interface MarketCloudIndustry {
  name: string;
  stock_count: number;
  total_float_cap: number;
  avg_change_pct: number;
  up_count: number;
  down_count: number;
  stocks: MarketCloudStock[];
}

export interface MarketCloudData {
  scope: string;
  period: string;
  stock_count: number;
  valid_count: number;
  industry_count: number;
  no_industry_count: number;
  industries: MarketCloudIndustry[];
}

export interface MarketCloudEnvelope {
  status: "normal" | "partial" | "stale" | "unavailable";
  data: MarketCloudData | null;
  warnings: string[];
  is_stale: boolean;
  fetched_at?: string;
  source?: string;
  trade_date?: string | null;
  data_time?: string | null;
}

// ── 颜色映射 ──────────────────────────────────────────────────────────

const NEUTRAL_GRAY = "#3f3f46";
const UP_RED = "#dc2626";
const DOWN_GREEN = "#16a34a";
const SATURATION_LIMIT = 5.0; // 涨跌幅绝对值超过 5% 颜色不再加深

/**
 * 涨跌幅 → 颜色。
 * 红涨绿跌，接近 0 为中性灰，深浅随 |涨跌幅| 变化。
 * 不制造"越红越应该买"的投资语义。
 */
export function changePctToColor(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(pct)) {
    return NEUTRAL_GRAY;
  }
  if (Math.abs(pct) < 0.05) {
    return NEUTRAL_GRAY;
  }
  const t = Math.min(Math.abs(pct) / SATURATION_LIMIT, 1);
  if (pct > 0) {
    return mixColor(NEUTRAL_GRAY, UP_RED, t);
  }
  return mixColor(NEUTRAL_GRAY, DOWN_GREEN, t);
}

function mixColor(a: string, b: string, t: number): string {
  const ar = parseInt(a.slice(1, 3), 16);
  const ag = parseInt(a.slice(3, 5), 16);
  const ab = parseInt(a.slice(5, 7), 16);
  const br = parseInt(b.slice(1, 3), 16);
  const bg = parseInt(b.slice(3, 5), 16);
  const bb = parseInt(b.slice(5, 7), 16);
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bl = Math.round(ab + (bb - ab) * t);
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${bl.toString(16).padStart(2, "0")}`;
}

// ── 数据转换：行业树 → ECharts Treemap data ─────────────────────────

export interface TreemapNode {
  name: string;
  value: number; // 流通市值（面积）
  itemStyle?: { color: string };
  children?: TreemapNode[];
  // 自定义数据，用于 tooltip 和 click
  code?: string;
  change_pct?: number;
  amount?: number | null;
  price?: number | null;
  industry?: string;
  node_type?: "industry" | "stock";
  stock_count?: number;
  up_count?: number;
  down_count?: number;
}

/**
 * 将市场云图数据转换为 ECharts Treemap 层级结构。
 * 根 → 行业 → 个股。
 * 行业节点 value = 行业内个股流通市值之和（自动由 children 求和，但显式设置更可靠）。
 */
export function marketCloudToTreemap(data: MarketCloudData): TreemapNode[] {
  return data.industries.map((ind) => ({
    name: ind.name,
    value: ind.total_float_cap,
    node_type: "industry" as const,
    stock_count: ind.stock_count,
    up_count: ind.up_count,
    down_count: ind.down_count,
    change_pct: ind.avg_change_pct,
    itemStyle: { color: changePctToColor(ind.avg_change_pct) },
    children: ind.stocks.map((s) => ({
      name: s.name,
      value: s.float_market_cap,
      code: s.code,
      change_pct: s.change_pct,
      amount: s.amount,
      price: s.price,
      industry: s.industry,
      node_type: "stock" as const,
      itemStyle: { color: changePctToColor(s.change_pct) },
    })),
  }));
}

// ── 格式化 ────────────────────────────────────────────────────────────

export function formatMarketCap(cap: number | null | undefined): string {
  if (cap === null || cap === undefined || Number.isNaN(cap)) return "—";
  if (cap >= 1e12) return `${(cap / 1e12).toFixed(2)} 万亿`;
  if (cap >= 1e8) return `${(cap / 1e8).toFixed(0)} 亿`;
  if (cap >= 1e4) return `${(cap / 1e4).toFixed(0)} 万`;
  return `${cap.toFixed(0)}`;
}

export function formatAmount(amount: number | null | undefined): string {
  return formatMarketCap(amount);
}

export function formatChangePct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export function formatPrice(price: number | null | undefined): string {
  if (price === null || price === undefined || Number.isNaN(price)) return "—";
  return price.toFixed(2);
}
