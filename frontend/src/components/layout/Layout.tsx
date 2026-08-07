import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  Radar,
  LayoutGrid,
  Wallet,
  Settings,
  Search,
  NotebookPen,
  Moon,
  Sun,
  ChevronsLeft,
  ChevronsRight,
  LineChart,
  Github,
  Star,
  FileText,
  Target,
  BookOpen,
  HeartPulse,
  ReceiptText,
  ShieldCheck,
  Settings2,
  BarChart3,
  PieChart,
  Menu,
  X,
  ChevronDown,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";
import { DailyReviewAiTaskIndicator } from "./DailyReviewAiTaskIndicator";
import { PortfolioAdviceTaskIndicator } from "./PortfolioAdviceTaskIndicator";

const APP_VERSION = "v0.1.3";
const REPO_URL = "https://github.com/guilaile95/Vibe-Research";

const PRIMARY_NAV = [
  { to: "/daily-review", icon: Activity, label: "Today" },
  { to: "/intel", icon: Radar, label: "Market" },
  { to: "/stock-data", icon: Search, label: "Stocks" },
  { to: "/portfolio", icon: Wallet, label: "Portfolio" },
];

const RESEARCH_NAV = [
  { to: "/sectors", icon: LayoutGrid, label: "板块研究" },
  { to: "/watchlist", icon: Star, label: "自选股" },
  { to: "/thesis", icon: BookOpen, label: "投资逻辑" },
  { to: "/my-reports", icon: FileText, label: "我的研报" },
  { to: "/notes", icon: NotebookPen, label: "研究记录" },
];

const MORE_NAV = [
  { to: "/cockpit", icon: Target, label: "决策舱" },
  { to: "/decision-evidence", icon: ShieldCheck, label: "决策依据" },
  { to: "/signal-ledger", icon: Activity, label: "信号账本" },
  { to: "/trades", icon: ReceiptText, label: "交易流水" },
  { to: "/decision-feedback", icon: BarChart3, label: "决策反馈" },
  { to: "/decision-performance", icon: BarChart3, label: "决策绩效" },
  { to: "/performance-attribution", icon: PieChart, label: "收益归因" },
  { to: "/account-policy", icon: Settings2, label: "执行策略" },
  { to: "/data-health", icon: HeartPulse, label: "数据健康" },
  { to: "/settings", icon: Settings, label: "设置与 AI" },
];

const SECTOR_LINKS = [
  { to: "/sectors/humanoid", label: "人形机器人" },
  { to: "/sectors/ai-computing", label: "AI 算力" },
  { to: "/sectors/hbm", label: "HBM" },
  { to: "/sectors/cpo", label: "光互联" },
  { to: "/sectors/business-space", label: "商业航天" },
  { to: "/sectors/ai-pharma", label: "生物医药" },
];

const VISIBLE_NAV = [...PRIMARY_NAV, ...RESEARCH_NAV, ...MORE_NAV];

function isActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(to + "/");
}

function getCurrentNavPath(pathname: string) {
  if (SECTOR_LINKS.some(({ to }) => isActive(pathname, to))) return "/sectors";
  if (pathname.startsWith("/thesis/")) return "/thesis";
  if (pathname.startsWith("/evidence")) return "/decision-evidence";
  return VISIBLE_NAV.reduce<string | null>((best, item) => {
    if (!isActive(pathname, item.to)) return best;
    return !best || item.to.length > best.length ? item.to : best;
  }, null);
}

const DESKTOP_QUERY = "(min-width: 768px)";

function readDesktop() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia(DESKTOP_QUERY).matches;
}

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
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(readDesktop);
  const [moreOpen, setMoreOpen] = useState(() => MORE_NAV.some(({ to }) => isActive(window.location.pathname, to)));
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    setMobileOpen(false);
    if (MORE_NAV.some(({ to }) => isActive(pathname, to)) || pathname.startsWith("/evidence")) {
      setMoreOpen(true);
    }
  }, [pathname]);

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
    mql.addListener(handler);
    return () => mql.removeListener(handler);
  }, []);

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

  const compact = isDesktop && collapsed;
  const currentNavPath = getCurrentNavPath(pathname);

  const navItem = ({ to, icon: Icon, label }: (typeof VISIBLE_NAV)[number]) => {
    const active = currentNavPath === to;
    return (
      <Link
        key={to}
        to={to}
        title={compact ? label : undefined}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex min-h-9 items-center rounded-lg text-[13px] transition-colors duration-150",
          compact ? "justify-center px-2" : "gap-2.5 px-2.5",
          active
            ? "bg-sidebar-active font-medium text-foreground"
            : "text-sidebar-foreground hover:bg-sidebar-hover hover:text-foreground",
        )}
      >
        <Icon className="h-[17px] w-[17px] shrink-0" />
        {!compact && <span className="truncate">{label}</span>}
      </Link>
    );
  };

  return (
    <div className="flex h-screen bg-background text-foreground">
      <button
        ref={triggerRef}
        type="button"
        data-testid="nav-drawer-trigger"
        onClick={() => setMobileOpen((v) => !v)}
        aria-label={mobileOpen ? "关闭导航菜单" : "打开导航菜单"}
        aria-expanded={mobileOpen}
        aria-controls="app-sidebar"
        className="fixed left-3 top-3 z-50 rounded-lg bg-sidebar-hover p-2 text-foreground shadow-sm md:hidden"
      >
        {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {mobileOpen && (
        <div
          aria-hidden="true"
          data-testid="nav-drawer-overlay"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/45 md:hidden"
        />
      )}

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
          "z-40 flex flex-col bg-sidebar transition-[width] duration-200",
          "fixed inset-y-0 left-0 w-[260px]",
          "md:static md:shrink-0",
          mobileOpen ? "flex" : "hidden md:flex",
          collapsed ? "md:w-14" : "md:w-[260px]",
        )}
      >
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

        <div className={cn("flex h-14 items-center", compact ? "justify-center px-2" : "justify-between px-3")}>
          <Link to="/daily-review" className={cn("flex items-center", compact ? "justify-center" : "gap-2.5")}>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-background">
              <LineChart className="h-4 w-4" />
            </span>
            {!compact && <span className="text-sm font-semibold tracking-tight">Vibe Research</span>}
          </Link>
          {!compact && (
            <button
              type="button"
              onClick={() => setCollapsed(true)}
              className="hidden rounded-lg p-2 text-sidebar-muted transition-colors hover:bg-sidebar-hover hover:text-foreground md:block"
              title="收起侧栏"
              aria-label="收起侧栏"
            >
              <ChevronsLeft className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className={cn("space-y-1 px-2 pb-2", compact && "px-1.5")}>
          <Link
            to="/stock-data"
            title={compact ? "新建研究" : undefined}
            className={cn(
              "flex min-h-10 items-center rounded-lg text-[13px] font-medium text-foreground transition-colors hover:bg-sidebar-hover",
              compact ? "justify-center px-2" : "gap-2.5 px-2.5",
            )}
          >
            <Plus className="h-[17px] w-[17px]" />
            {!compact && "新建研究"}
          </Link>
          <Link
            to="/stock-data"
            title={compact ? "搜索" : undefined}
            className={cn(
              "flex min-h-10 items-center rounded-lg text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-hover hover:text-foreground",
              compact ? "justify-center px-2" : "gap-2.5 px-2.5",
            )}
          >
            <Search className="h-[17px] w-[17px]" />
            {!compact && (
              <>
                <span className="flex-1">搜索</span>
                <span className="text-[10px] text-sidebar-muted">Ctrl K</span>
              </>
            )}
          </Link>
        </div>

        <nav aria-label="主导航" className={cn("flex-1 overflow-y-auto px-2 pb-3", compact && "px-1.5")}>
          <div className="space-y-0.5">
            {PRIMARY_NAV.map(navItem)}
          </div>

          <div className="mt-5">
            {!compact && <p className="mb-1.5 px-2.5 text-[11px] font-medium text-sidebar-muted">Research</p>}
            <div className="space-y-0.5">{RESEARCH_NAV.map(navItem)}</div>
          </div>

          {!compact && (
            <div className="mt-5">
              <p className="mb-1.5 px-2.5 text-[11px] font-medium text-sidebar-muted">常用研究</p>
              <div className="space-y-0.5">
                {SECTOR_LINKS.slice(0, 4).map(({ to, label }) => (
                  <Link
                    key={to}
                    to={to}
                    className={cn(
                      "block min-h-8 truncate rounded-lg px-2.5 py-1.5 text-[13px] transition-colors",
                      isActive(pathname, to)
                        ? "bg-sidebar-active text-foreground"
                        : "text-sidebar-foreground hover:bg-sidebar-hover hover:text-foreground",
                    )}
                  >
                    {label}
                  </Link>
                ))}
              </div>
            </div>
          )}

          <div className="mt-5">
            <button
              type="button"
              onClick={() => setMoreOpen((v) => !v)}
              aria-expanded={moreOpen}
              className={cn(
                "flex min-h-9 w-full items-center rounded-lg text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-hover hover:text-foreground",
                compact ? "justify-center px-2" : "gap-2.5 px-2.5",
              )}
            >
              <Settings className="h-[17px] w-[17px]" />
              {!compact && (
                <>
                  <span className="flex-1 text-left">More</span>
                  <ChevronDown className={cn("h-4 w-4 transition-transform", moreOpen && "rotate-180")} />
                </>
              )}
            </button>
            {moreOpen && <div className="mt-0.5 space-y-0.5">{MORE_NAV.map(navItem)}</div>}
          </div>
        </nav>

        <div className={cn("border-t border-white/5 p-2", compact && "flex flex-col items-center gap-1")}>
          {compact ? (
            <>
              <button
                type="button"
                onClick={toggle}
                className="rounded-lg p-2 text-sidebar-muted transition-colors hover:bg-sidebar-hover hover:text-foreground"
                title={dark ? "切换到亮色" : "切换到暗色"}
                aria-label={dark ? "切换到亮色主题" : "切换到暗色主题"}
              >
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <button
                type="button"
                onClick={() => setCollapsed(false)}
                className="rounded-lg p-2 text-sidebar-muted transition-colors hover:bg-sidebar-hover hover:text-foreground"
                title="展开侧栏"
                aria-label="展开侧栏"
              >
                <ChevronsRight className="h-4 w-4" />
              </button>
            </>
          ) : (
            <div className="flex items-center justify-between rounded-lg px-2 py-1.5 text-xs text-sidebar-muted">
              <button
                type="button"
                onClick={toggle}
                className="flex items-center gap-1.5 rounded-md px-1.5 py-1 transition-colors hover:bg-sidebar-hover hover:text-foreground"
              >
                {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                {dark ? "亮色" : "暗色"}
              </button>
              <div className="flex items-center gap-1">
                <span className="px-1 text-[10px]">{APP_VERSION}</span>
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md p-1.5 transition-colors hover:bg-sidebar-hover hover:text-foreground"
                  title="GitHub"
                  aria-label="GitHub 仓库"
                >
                  <Github className="h-3.5 w-3.5" />
                </a>
              </div>
            </div>
          )}
        </div>
      </aside>

      <main ref={mainRef} className="flex-1 overflow-auto bg-background">
        <div className="mx-auto w-full max-w-[1320px] px-4 pb-12 pt-16 sm:px-6 md:px-8 md:pt-7 lg:px-10">
          <DailyReviewAiTaskIndicator />
          <PortfolioAdviceTaskIndicator />
          <Outlet />
        </div>
      </main>
    </div>
  );
}
