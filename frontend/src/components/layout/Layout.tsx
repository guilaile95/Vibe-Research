import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Activity, Radar, LayoutGrid, Wallet, Settings, Search, NotebookPen,
  Moon, Sun, ChevronsLeft, ChevronsRight, LineChart, Github,
  Cog, Cpu, Database, Cable, Rocket, FlaskConical, Star, FileText,
  Target, BookOpen, HeartPulse, ReceiptText, MessageSquareCode, ShieldCheck,
  Settings2, BarChart3, PieChart, Menu, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";
import { DailyReviewAiTaskIndicator } from "./DailyReviewAiTaskIndicator";
import { PortfolioAdviceTaskIndicator } from "./PortfolioAdviceTaskIndicator";

const APP_VERSION = "v0.1.3";
const REPO_URL = "https://github.com/guilaile95/Vibe-Research";

/** 三组导航：市场 / 研究 / 管理。路径集合与 router.tsx 保持一致（19 项）。 */
const NAV_GROUPS = [
  {
    id: "nav-group-market",
    label: "市场",
    items: [
      { to: "/daily-review", icon: Activity, label: "每日复盘" },
      { to: "/intel", icon: Radar, label: "资讯雷达" },
      { to: "/sectors", icon: LayoutGrid, label: "板块中心" },
      { to: "/stock-data", icon: Search, label: "个股数据" },
      { to: "/watchlist", icon: Star, label: "自选股" },
      { to: "/signal-ledger", icon: Activity, label: "信号账本" },
    ],
  },
  {
    id: "nav-group-research",
    label: "研究",
    items: [
      { to: "/cockpit", icon: Target, label: "决策舱" },
      { to: "/decision-feedback", icon: MessageSquareCode, label: "决策反馈" },
      { to: "/decision-performance", icon: BarChart3, label: "决策绩效" },
      { to: "/performance-attribution", icon: PieChart, label: "收益归因" },
      { to: "/decision-evidence", icon: ShieldCheck, label: "决策依据" },
      { to: "/thesis", icon: BookOpen, label: "投资逻辑" },
      { to: "/my-reports", icon: FileText, label: "我的研报" },
      { to: "/notes", icon: NotebookPen, label: "研究记录" },
    ],
  },
  {
    id: "nav-group-manage",
    label: "管理",
    items: [
      { to: "/portfolio", icon: Wallet, label: "我的持仓" },
      { to: "/trades", icon: ReceiptText, label: "交易流水" },
      { to: "/account-policy", icon: Settings2, label: "执行策略" },
      { to: "/data-health", icon: HeartPulse, label: "数据健康" },
      { to: "/settings", icon: Settings, label: "接入 AI" },
    ],
  },
];

// 常看的板块，作为「板块中心」下的快捷入口（缩进显示）。
const SECTOR_LINKS = [
  { to: "/sectors/humanoid", icon: Cog, label: "人形机器人" },
  { to: "/sectors/ai-computing", icon: Cpu, label: "AI 算力" },
  { to: "/sectors/hbm", icon: Database, label: "HBM" },
  { to: "/sectors/cpo", icon: Cable, label: "光互联" },
  { to: "/sectors/business-space", icon: Rocket, label: "商业航天" },
  { to: "/sectors/ai-pharma", icon: FlaskConical, label: "生物医药" },
];

/** 当前路由高亮：根路径必须精确匹配，否则会命中所有页面。 */
function isActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(to + "/");
}

export function Layout() {
  const { pathname } = useLocation();
  const { dark, toggle } = useDarkMode();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  // 窄屏抽屉（md 以下）。桌面端始终为 false，不影响原有行为。
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  // 路由切换后自动关闭抽屉
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // 抽屉展开时按图标模式收起会让内容不可读，故窄屏抽屉内始终显示完整标签
  const compact = collapsed && !mobileOpen;

  return (
    <div className="flex h-screen">
      {/* 窄屏汉堡按钮 */}
      <button
        type="button"
        onClick={() => setMobileOpen((v) => !v)}
        aria-label={mobileOpen ? "关闭导航菜单" : "打开导航菜单"}
        aria-expanded={mobileOpen}
        aria-controls="app-sidebar"
        className="glass fixed left-3 top-3 z-50 rounded-lg p-2 text-foreground md:hidden"
      >
        {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {/* 抽屉遮罩 */}
      {mobileOpen && (
        <div
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
        />
      )}

      {/* Sidebar */}
      <aside
        id="app-sidebar"
        className={cn(
          "glass z-40 flex flex-col rounded-2xl transition-all duration-200",
          "fixed inset-y-2 left-2 w-60",
          "md:static md:m-2 md:inset-auto md:shrink-0",
          mobileOpen ? "flex" : "hidden md:flex",
          compact ? "md:w-14" : "md:w-60",
        )}
      >
        {/* Brand */}
        <div className={cn("border-b border-border/40", compact ? "flex justify-center p-3" : "p-4")}>
          <Link to="/daily-review" className={cn("flex items-center", compact ? "justify-center" : "gap-2.5")}>
            <LineChart className="h-6 w-6 shrink-0 text-primary text-glow" />
            {!compact && (
              <span className="font-display text-lg font-bold tracking-tight">
                Vibe-<span className="text-primary">Research</span>
              </span>
            )}
          </Link>
          {!compact && <p className="mt-1 text-[11px] text-muted-foreground">个人 AI 投研系统 · A股/美股/港股</p>}
        </div>

        {/* Nav — 三组：市场 / 研究 / 管理 */}
        <nav aria-label="主导航" className={cn("flex-1 overflow-auto", compact ? "space-y-1 p-1.5" : "space-y-4 p-3")}>
          {NAV_GROUPS.map((group) => (
            <div key={group.id} role="group" aria-labelledby={group.id}>
              <h2
                id={group.id}
                className={cn(
                  "mb-1.5 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground",
                  compact && "sr-only",
                )}
              >
                {group.label}
              </h2>
              <div className="space-y-0.5">
                {group.items.map(({ to, icon: Icon, label }) => {
                  const active = isActive(pathname, to);
                  return (
                    <div key={to}>
                      <Link
                        to={to}
                        title={compact ? label : undefined}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex items-center rounded-lg text-[13px] transition-colors duration-150",
                          compact ? "justify-center p-2.5" : "gap-2.5 px-3 py-2",
                          active
                            ? "bg-primary/15 font-medium text-primary shadow-glow"
                            : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                        )}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        {!compact && label}
                      </Link>

                      {/* 板块中心下方：常看板块的快捷入口（缩进） */}
                      {to === "/sectors" && (
                        <div className={cn("mt-0.5 space-y-0.5", !compact && "ml-4 border-l border-border/30 pl-1.5")}>
                          {SECTOR_LINKS.map(({ to: st, icon: SIcon, label: slabel }) => {
                            const sactive = pathname === st;
                            return (
                              <Link
                                key={st}
                                to={st}
                                title={compact ? slabel : undefined}
                                aria-current={sactive ? "page" : undefined}
                                className={cn(
                                  "flex items-center rounded-md transition-colors",
                                  compact ? "justify-center p-2" : "gap-2 px-2.5 py-1.5 text-xs",
                                  sactive
                                    ? "bg-primary/10 font-medium text-primary"
                                    : "text-muted-foreground hover:bg-muted/30 hover:text-foreground",
                                )}
                              >
                                <SIcon className="h-3.5 w-3.5 shrink-0" />
                                {!compact && slabel}
                              </Link>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className={cn("border-t border-border/40", compact ? "flex flex-col items-center gap-2 p-2" : "space-y-2 p-3")}>
          {compact ? (
            <>
              <button onClick={toggle} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" title={dark ? "亮色" : "暗色"} aria-label={dark ? "切换到亮色主题" : "切换到暗色主题"}>
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <button onClick={() => setCollapsed(false)} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" title="展开" aria-label="展开侧栏">
                <ChevronsRight className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <button onClick={toggle} className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground">
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                  {dark ? "亮色" : "暗色"}
                </button>
                <div className="flex items-center gap-2">
                  <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-muted-foreground transition-colors hover:text-foreground" title="GitHub" aria-label="GitHub 仓库">
                    <Github className="h-3.5 w-3.5" />
                  </a>
                  <button onClick={() => setCollapsed(true)} className="hidden rounded p-1 text-muted-foreground transition-colors hover:text-foreground md:block" title="收起" aria-label="收起侧栏">
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">{APP_VERSION}</p>
            </>
          )}
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        <div className="mx-auto max-w-6xl px-4 pb-8 pt-16 sm:px-6 md:pt-8">
          <DailyReviewAiTaskIndicator />
          <PortfolioAdviceTaskIndicator />
          <Outlet />
        </div>
      </main>
    </div>
  );
}
