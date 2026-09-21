import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  BarChart3,
  BookOpen,
  ChevronsLeft,
  ChevronsRight,
  HeartPulse,
  Inbox,
  LineChart,
  Moon,
  ReceiptText,
  Search,
  Settings,
  Star,
  Sun,
  Wallet,
  X,
  Menu,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";
import { NAV_GROUPS, entriesInGroup, matchRoute, navEntry } from "@/lib/navigation";
import { DailyReviewAiTaskIndicator } from "./DailyReviewAiTaskIndicator";
import { PortfolioAdviceTaskIndicator } from "./PortfolioAdviceTaskIndicator";
import { SectionNav } from "./SectionNav";

/**
 * 侧栏跟随用户的工作情境，而不是实现模块（TASK = IA-CONVERGENCE-V1）。
 *
 * 一级入口固定为 10 个，来自 `navigation.ts` 的单一权威配置：
 * 工作（今天 / 决策待办）、研究（自选股 / 投资研究 / 研究资料）、
 * 账户与复盘（我的持仓 / 交易记录 / 决策复盘）、系统（数据健康 / 设置）。
 *
 * 分组标题是静态文字，不再是要先点开的折叠层；
 * 一级入口内部的二级页面由 `<SectionNav>` 呈现。
 */
const NAV_ICONS: Record<string, LucideIcon> = {
  today: Activity,
  decision: Inbox,
  watchlist: Star,
  research: Search,
  library: BookOpen,
  portfolio: Wallet,
  trades: ReceiptText,
  review: BarChart3,
  health: HeartPulse,
  settings: Settings,
};

const WIDE_WORKSPACE_PATHS = ["/daily-review", "/market-cloud"];

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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    setMobileOpen(false);
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
  const currentOwner = matchRoute(pathname)?.owner ?? null;
  const currentTitle = navEntry(currentOwner ?? "")?.label ?? "";

  const renderEntry = (id: string) => {
    const entry = navEntry(id);
    if (!entry) return null;
    const Icon = NAV_ICONS[entry.id] ?? Activity;
    const active = currentOwner === entry.id;
    return (
      <Link
        key={entry.id}
        to={entry.to}
        data-nav-entry={entry.id}
        title={compact ? entry.label : undefined}
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
        {!compact && <span className="truncate">{entry.label}</span>}
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
          collapsed ? "md:w-14" : "md:w-[200px]",
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

        <nav aria-label="主导航" className={cn("flex-1 overflow-y-auto px-2 pb-3 pt-1", compact && "px-1.5")}>
          {NAV_GROUPS.map((group, index) => {
            const entries = entriesInGroup(group.id);
            if (!entries.length) return null;
            return (
              <div key={group.id} data-nav-group={group.id} className={cn(index > 0 && "mt-4")}>
                {!compact && (
                  <p className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wide text-sidebar-muted">
                    {group.label}
                  </p>
                )}
                {compact && index > 0 && <div className="mx-2 mb-2 border-t border-border/40" />}
                <div className="space-y-0.5">{entries.map((entry) => renderEntry(entry.id))}</div>
              </div>
            );
          })}
        </nav>

        <div className={cn("space-y-0.5 px-2 pb-2", compact && "flex flex-col items-center px-1.5")}>
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
            <button
              type="button"
              onClick={toggle}
              className="flex min-h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-sidebar-foreground transition-colors hover:bg-sidebar-hover hover:text-foreground"
            >
              {dark ? <Sun className="h-[17px] w-[17px]" /> : <Moon className="h-[17px] w-[17px]" />}
              <span>{dark ? "亮色模式" : "暗色模式"}</span>
            </button>
          )}
        </div>
      </aside>

      <main ref={mainRef} className="flex-1 overflow-auto bg-background">
        <div
          className={cn(
            "mx-auto w-full px-6 pb-12 pt-16 sm:px-6 md:px-6 md:pt-7",
            WIDE_WORKSPACE_PATHS.includes(pathname) ? "max-w-[1760px]" : "max-w-[1320px]",
          )}
        >
          <DailyReviewAiTaskIndicator />
          <PortfolioAdviceTaskIndicator />
          <SectionNav ownerId={currentOwner} pathname={pathname} title={currentTitle} />
          <Outlet />
        </div>
      </main>
    </div>
  );
}
