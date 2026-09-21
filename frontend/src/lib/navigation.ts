/**
 * 信息架构（IA）单一权威配置 —— TASK = IA-CONVERGENCE-V1
 *
 * 这里只描述「用户看到什么、在哪里」，不描述实现模块：
 * - `NAV_ENTRIES`：10 个常驻一级入口，分组与顺序固定；
 * - `ROUTE_OWNERS`：全部路由声明各自的一级归属与统一名称；
 * - `SECTION_NAVS`：一级入口内部的二级入口（含「旧版分析工具」目录）。
 *
 * 约定：
 * - 本文件保持纯净（无 React、无图标、无副作用），便于直接单测归属与激活匹配；
 * - 一级归属唯一：任一路由只属于一个入口；
 * - 归属只决定导航高亮与面包屑名称，不改变页面自身的标题语义。
 */

export type NavGroupId = "work" | "research" | "account" | "system";

export interface NavGroup {
  id: NavGroupId;
  label: string;
}

/** 分组是静态标题，不是可折叠层；顺序即渲染顺序。 */
export const NAV_GROUPS: readonly NavGroup[] = [
  { id: "work", label: "工作" },
  { id: "research", label: "研究" },
  { id: "account", label: "账户与复盘" },
  { id: "system", label: "系统" },
];

export interface NavEntry {
  id: string;
  group: NavGroupId;
  /** 侧栏标签；在未另行指定的页面上也作为一级面包屑名称。 */
  label: string;
  /** 该入口的默认落点。 */
  to: string;
}

/** 10 个常驻入口。 */
export const NAV_ENTRIES: readonly NavEntry[] = [
  { id: "today", group: "work", label: "今天", to: "/daily-review" },
  { id: "decision", group: "work", label: "决策待办", to: "/decision-inbox" },
  { id: "watchlist", group: "research", label: "自选股", to: "/watchlist" },
  { id: "research", group: "research", label: "投资研究", to: "/screener" },
  { id: "library", group: "research", label: "研究资料", to: "/thesis" },
  { id: "portfolio", group: "account", label: "我的持仓", to: "/portfolio" },
  { id: "trades", group: "account", label: "交易记录", to: "/trades" },
  { id: "review", group: "account", label: "决策复盘", to: "/decision-performance" },
  { id: "health", group: "system", label: "数据健康", to: "/data-health" },
  { id: "settings", group: "system", label: "设置", to: "/settings" },
];

export function navEntry(id: string): NavEntry | undefined {
  return NAV_ENTRIES.find((entry) => entry.id === id);
}

export function entriesInGroup(group: NavGroupId): NavEntry[] {
  return NAV_ENTRIES.filter((entry) => entry.group === group);
}

/**
 * 路由归属表：覆盖 `router.tsx` 的全部路由声明。
 * `pattern` 支持 `:param` 形式的动态段；匹配取最长者，避免详情路由被列表路由吞掉。
 */
export interface RouteOwner {
  pattern: string;
  owner: string;
  /** 统一名称：说明具体功能或对象，不重复一级菜单名。 */
  name: string;
}

export const ROUTE_OWNERS: readonly RouteOwner[] = [
  // 工作 / 今天
  { pattern: "/", owner: "today", name: "今天" },
  { pattern: "/daily-review", owner: "today", name: "今天" },
  { pattern: "/market-cloud", owner: "today", name: "市场全景" },
  { pattern: "/market-history", owner: "today", name: "北向成交额历史" },

  // 工作 / 决策待办
  { pattern: "/decision-inbox", owner: "decision", name: "决策待办" },
  { pattern: "/campaigns/:campaignId/decision-proposal", owner: "decision", name: "正式决策" },

  // 研究 / 自选股
  { pattern: "/watchlist", owner: "watchlist", name: "自选股" },

  // 研究 / 投资研究
  { pattern: "/screener", owner: "research", name: "市场发现" },
  { pattern: "/stock-data", owner: "research", name: "个股数据" },
  { pattern: "/candidates/:code", owner: "research", name: "候选研究" },
  { pattern: "/sectors", owner: "research", name: "板块研究" },
  { pattern: "/sectors/:key", owner: "research", name: "板块研究" },
  { pattern: "/sectors/:key/:tag", owner: "research", name: "板块研究" },
  { pattern: "/intel", owner: "research", name: "资讯中心" },
  { pattern: "/signals", owner: "research", name: "产业信号" },
  { pattern: "/signals/:tab", owner: "research", name: "产业信号" },
  { pattern: "/debate", owner: "research", name: "多空辩论" },

  // 账户与复盘 / 我的持仓
  { pattern: "/portfolio", owner: "portfolio", name: "我的持仓" },

  // 账户与复盘 / 交易记录
  { pattern: "/trades", owner: "trades", name: "交易记录" },
  { pattern: "/performance-attribution", owner: "trades", name: "收益归因" },

  // 账户与复盘 / 决策复盘
  { pattern: "/decision-performance", owner: "review", name: "决策复盘" },

  // 研究 / 研究资料
  { pattern: "/thesis", owner: "library", name: "投资逻辑" },
  { pattern: "/thesis/new", owner: "library", name: "新建投资逻辑" },
  { pattern: "/thesis/:id", owner: "library", name: "投资逻辑详情" },
  { pattern: "/thesis/:id/revision/:rev", owner: "library", name: "投资逻辑历史版本" },
  { pattern: "/evidence", owner: "library", name: "证据库" },
  { pattern: "/evidence/new", owner: "library", name: "新建证据" },
  { pattern: "/evidence/:id", owner: "library", name: "证据详情" },
  { pattern: "/my-reports", owner: "library", name: "我的研报" },
  { pattern: "/notes", owner: "library", name: "研究笔记" },

  // 研究 / 研究资料 → 旧版分析工具
  { pattern: "/decision-evidence", owner: "library", name: "建议依据追踪（旧版）" },
  { pattern: "/decision-feedback", owner: "library", name: "建议采纳反馈（旧版）" },
  { pattern: "/signal-ledger", owner: "library", name: "建议信号账本（旧版）" },
  { pattern: "/cockpit", owner: "library", name: "决策驾驶舱（旧版）" },

  // 系统
  { pattern: "/data-health", owner: "health", name: "数据健康" },
  { pattern: "/settings", owner: "settings", name: "设置" },
  { pattern: "/account-policy", owner: "settings", name: "执行参数" },
];

/** 把 `:param` 形式的路由模板编译成精确匹配的正则。 */
function compilePattern(pattern: string): RegExp {
  const source = pattern
    .split("/")
    .map((segment) => (segment.startsWith(":") ? "[^/]+" : segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("/");
  return new RegExp(`^${source}$`);
}

const COMPILED: readonly { owner: RouteOwner; regex: RegExp }[] = ROUTE_OWNERS.map((owner) => ({
  owner,
  regex: compilePattern(owner.pattern),
}));

/** 精确匹配：路径与路由模板逐段相等（动态段算一段）。 */
export function matchRoute(pathname: string): RouteOwner | null {
  let best: RouteOwner | null = null;
  for (const item of COMPILED) {
    if (!item.regex.test(pathname)) continue;
    if (!best || item.owner.pattern.length > best.pattern.length) best = item.owner;
  }
  return best;
}

/** 归属到某个一级入口的路由模板集合（用于「该入口下是否有此路由」的判断）。 */
export function routesOf(ownerId: string): RouteOwner[] {
  return ROUTE_OWNERS.filter((item) => item.owner === ownerId);
}

export interface SectionNavGroup {
  /** null 表示不显示分组标题。 */
  label: string | null;
  items: { to: string; label: string }[];
}

/**
 * 一级入口内部的二级入口。未在此声明的入口不显示二级导航。
 * 注：自选股是独立一级入口，不再出现在投资研究的二级导航里。
 */
export const SECTION_NAVS: Record<string, SectionNavGroup[]> = {
  research: [
    {
      label: null,
      items: [
        { to: "/screener", label: "市场发现" },
        { to: "/sectors", label: "板块研究" },
        { to: "/stock-data", label: "个股数据" },
        { to: "/intel", label: "资讯中心" },
        { to: "/signals", label: "产业信号" },
      ],
    },
    {
      label: "研究工具",
      items: [{ to: "/debate", label: "多空辩论" }],
    },
  ],
  library: [
    {
      label: null,
      items: [
        { to: "/thesis", label: "投资逻辑" },
        { to: "/evidence", label: "证据库" },
        { to: "/my-reports", label: "我的研报" },
        { to: "/notes", label: "研究笔记" },
      ],
    },
    {
      label: "旧版分析工具",
      items: [
        { to: "/decision-evidence", label: "建议依据追踪（旧版）" },
        { to: "/decision-feedback", label: "建议采纳反馈（旧版）" },
        { to: "/signal-ledger", label: "建议信号账本（旧版）" },
        { to: "/cockpit", label: "决策驾驶舱（旧版）" },
      ],
    },
  ],
  trades: [
    {
      label: null,
      items: [
        { to: "/trades", label: "交易记录" },
        { to: "/performance-attribution", label: "收益归因" },
      ],
    },
  ],
  settings: [
    {
      label: null,
      items: [
        { to: "/settings", label: "设置" },
        { to: "/account-policy", label: "执行参数" },
      ],
    },
  ],
};

export function sectionNavsOf(ownerId: string | null): SectionNavGroup[] {
  if (!ownerId) return [];
  return SECTION_NAVS[ownerId] ?? [];
}

/**
 * 二级入口激活判定：`to` 与其任意子路径都算激活。
 * `/thesis` 与 `/thesis/new` 这类同级项按「精确优先」处理，避免新建页把列表页点亮。
 */
export function isSectionItemActive(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}

/**
 * 取当前路径在给定二级导航中命中的项：优先精确匹配，其次最长前缀匹配。
 * 返回 null 表示当前页面不属于该二级导航的任何一项（例如候选研究）。
 */
export function activeSectionItem(pathname: string, groups: SectionNavGroup[]): string | null {
  const items = groups.flatMap((group) => group.items);
  const exact = items.find((item) => item.to === pathname);
  if (exact) return exact.to;
  let best: string | null = null;
  for (const item of items) {
    if (!pathname.startsWith(`${item.to}/`)) continue;
    if (!best || item.to.length > best.length) best = item.to;
  }
  return best;
}
