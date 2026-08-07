import { useEffect, useRef, useState } from "react";
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

// 常看板块仍用于最长路由匹配；P0 视觉试验不再在主侧栏展开这些快捷入口。
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

const NAV_PATHS = [
  ...NAV_GROUPS.flatMap((group) => group.items.map((item) => item.to)),
  ...SECTOR_LINKS.map((item) => item.to),
];

/** aria-current 只标记最长匹配路径；父级仍可保持视觉高亮。 */
function getCurrentNavPath(pathname: string) {
  return NAV_PATHS.reduce<string | null>((best, to) => {
    if (!isActive(pathname, to)) return best;
    return !best || to.length > best.length ? to : best;
  }, null);
}

const DESKTOP_QUERY = "(min-width: 768px)";

/** SSR / 测试环境可能没有 matchMedia，缺失时按桌面处理（与旧行为一致）。 */
function readDesktop() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia(DESKTOP_QUERY).matches;
}

/** 抽屉内可聚焦元素（用于焦点约束），跳过隐藏元素。 */
function focusableIn(container: HTMLElement | null) {
  if (!container) return [] as HTMLElement[];
  const nodes = container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  );
  return Array.from(nodes).filter((el) => el.offsetParent !== null || el.getClientRects().length > 0);
}

export function Layout() {
  const { pathname } = useLocation();
  const { dark, toggle } = useDarkMode();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  // 窄屏抽屉（md 以下）。桌面断点下强制为 false。
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(readDesktop);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  // 路由切换后自动关闭抽屉
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // 断点监听：进入桌面断点必须关闭移动抽屉，否则会污染桌面侧栏状态
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(DESKTOP_QUERY);
    const apply = (matches: boolean) => {
      setIsDesktop(matches);
      if (matches) setMobileOpen(false);
    };
    apply(mql.matches);
    const handler = (event: MediaQueryListEvent) => apply(event.matches);
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", handler);
      return () => mql.removeEventListener("change", handler);
    }
    // 旧版 Safari / jsdom 兼容
    mql.addListener(handler);
    return () => mql.removeListener(handler);
  }, []);

  // 抽屉打开：焦点进入、Escape 关闭、焦点约束、背景 inert + body 锁滚动（清理全在同一 cleanup）
  useEffect(() => {
    if (!mobileOpen) return;
    const trigger = triggerRef.current;
    const main = mainRef.current;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (main) {
      main.setAttribute("inert", "");
      main.setAttribute("aria-hidden", "true");
    }

    const first = focusableIn(drawerRef.current)[0];
    if (first) first.focus();
    else drawerRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusableIn(drawerRef.current);
      if (!items.length) {
        event.preventDefault();
        return;
      }
      const active = document.activeElement as HTMLElement | null;
      const index = active ? items.indexOf(active) : -1;
      if (index === -1) {
        event.preventDefault();
        items[event.shiftKey ? items.length - 1 : 0].focus();
        return;
      }
      if (event.shiftKey && index === 0) {
        event.preventDefault();
        items[items.length - 1].focus();
      } else if (!event.shiftKey && index === items.length - 1) {
        event.preventDefault();
        items[0].focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = prevOverflow;
      if (main) {
        main.removeAttribute("inert");
        main.removeAttribute("aria-hidden");
      }
      if (trigger && document.body.contains(trigger)) trigger.focus();
    };
  }, [mobileOpen]);

  // 图标模式仅属于桌面折叠态；移动抽屉内始终显示完整标签。
  // 桌面宽度只由 collapsed 决定（见 aside class），与 mobileOpen 无关。
  const compact = isDesktop && collapsed;
  const currentNavPath = getCurrentNavPath(pathname);

  return (
    <div className="flex h-screen bg-background">
      {/* 窄屏汉堡按钮 */}
      <button
        ref={triggerRef}
        type="button"
        data-testid="nav-drawer-trigger"
        onClick={() => setMobileOpen((v) => !v)}
        aria-label={mobileOpen ? "关闭导航菜单" : "打开导航菜单"}
        aria-expanded={mobileOpen}
        aria-controls="app-sidebar"
        className="fixed left-3 top-3 z-50 rounded-md border border-border bg-card p-2 text-foreground transition-colors duration-150 hover:bg-muted md:hidden"
      >
        {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {/* 抽屉遮罩 */}
      {mobileOpen && (
        <div
          aria-hidden="true"
          data-testid="nav-drawer-overlay"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
        />
      )}

      {/* Sidebar：固定、扁平、无 glass/glow，保留原移动端可访问性契约。 */}
      <aside
        id="app-sidebar"
        ref={drawerRef}
        tabIndex={-1}
        data-testid="app-sidebar"
        data-mobile-open={mobileOpen ? "true" : "false"}
        role={mobileOpen ? "dialog" : undefined}
        aria-modal={mobileOpen ? true : undefined}
        aria-label={mobileOpen ? "导航菜单" : undefined}
        className={cn(
          "z-40 flex flex-col border-r border-border/80 bg-card transition-[width] duration-200",
          "fixed inset-y-0 left-0 w-56",
          "md:static md:inset-auto md:shrink-0",
          mobileOpen ? "flex" : "hidden md:flex",
          collapsed ? "md:w-14" : "md:w-56",
        )}
      >
        {/* 抽屉内的键盘可达关闭控件（焦点约束的第一个目标） */}
        {mobileOpen && (
          <button
            type="button"
            data-testid="nav-drawer-close"
            onClick={() => setMobileOpen(false)}
            className="sr-only md:hidden"
          >
            关闭导航菜单
          </button>
        )}

        {/* Brand */}
        <div className={cn("border-b border-border/60", compact ? "flex justify-center p-3" : "px-3.5 py-4")}>
          <Link to="/daily-review" className={cn("flex items-center", compact ? "justify-center" : "gap-2.5")}>
            <LineChart className="h-5 w-5 shrink-0 text-primary" />
            {!compact && (
              <span className="font-display text-[15px] font-semibold tracking-tight text-foreground">
                Vibe Research
              </span>
            )}
          </Link>
          {!compact && (
            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground/75">
              个人 AI 投研系统 · A股/美股/港股
            </p>
          )}
        </div>

        {/* Nav — P0 保留原业务分组与路由，仅收敛视觉密度。 */}
        <nav aria-label="主导航" className={cn("flex-1 overflow-auto", compact ? "space-y-1 p-1.5" : "space-y-3.5 p-2.5")}>
          {NAV_GROUPS.map((group) => (
            <div key={group.id} role="group" aria-labelledby={group.id}>
              <h2
                id={group.id}
                className={cn(
                  "mb-1 px-2.5 text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground/70",
                  compact && "sr-only",
                )}
              >
                {group.label}
              </h2>
              <div className="space-y-0.5">
                {group.items.map(({ to, icon: Icon, label }) => {
                  const active = isActive(pathname, to);
                  return (
                    <Link
                      key={to}
                      to={to}
                      title={compact ? label : undefined}
                      aria-current={currentNavPath === to ? "page" : undefined}
                      className={cn(
                        "flex items-center rounded-md text-[13px] transition-colors duration-150",
                        compact ? "justify-center p-2.5" : "gap-2.5 px-2.5 py-2",
                        active
                          ? "bg-muted font-medium text-foreground"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                      )}
                    >
                      <Icon
                        className={cn(
                          "h-4 w-4 shrink-0 transition-colors duration-150",
                          active ? "text-primary" : "text-muted-foreground/80",
                        )}
                      />
                      {!compact && label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className={cn("border-t border-border/60", compact ? "flex flex-col items-center gap-2 p-2" : "space-y-2 p-3")}>
          {compact ? (
            <>
              <button
                onClick={toggle}
                className="rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
                title={dark ? "亮色" : "暗色"}
                aria-label={dark ? "切换到亮色主题" : "切换到暗色主题"}
              >
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <button
                onClick={() => setCollapsed(false)}
                className="rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
                title="展开"
                aria-label="展开侧栏"
              >
                <ChevronsRight className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <button
                  onClick={toggle}
                  className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
                >
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                  {dark ? "亮色" : "暗色"}
                </button>
                <div className="flex items-center gap-1.5">
                  <a
                    href={REPO_URL}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
                    title="GitHub"
                    aria-label="GitHub 仓库"
                  >
                    <Github className="h-3.5 w-3.5" />
                  </a>
                  <button
                    onClick={() => setCollapsed(true)}
                    className="hidden rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground md:block"
                    title="收起"
                    aria-label="收起侧栏"
                  >
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <p className="px-1.5 text-[10px] leading-relaxed text-muted-foreground/70">{APP_VERSION}</p>
            </>
          )}
        </div>
      </aside>

      {/* Main */}
      <main ref={mainRef} className="flex-1 overflow-auto bg-background">
        <div className="mx-auto w-full max-w-[1440px] px-4 pb-10 pt-16 sm:px-6 md:px-8 md:pt-7">
          <DailyReviewAiTaskIndicator />
          <PortfolioAdviceTaskIndicator />
          <Outlet />
        </div>
      </main>
    </div>
  );
}
