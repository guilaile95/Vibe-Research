import { Link, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";

const WORKFLOW_NAV = [
  { to: "/stock-data", label: "数据" },
  { to: "/thesis", label: "逻辑" },
  { to: "/decision-evidence", label: "依据" },
  { to: "/portfolio", label: "持仓" },
  { to: "/decision-feedback", label: "复盘" },
];

function isActive(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function ResearchWorkflowNav() {
  const { pathname } = useLocation();

  return (
    <div className="mb-6 flex min-w-0 items-center gap-4 border-b border-border/50">
      <span className="hidden shrink-0 pb-2.5 text-[11px] font-medium text-muted-foreground lg:inline">
        研究工作流
      </span>
      <nav aria-label="研究工作流" className="min-w-0 flex-1 overflow-x-auto">
        <div className="flex min-w-max items-center gap-1">
          {WORKFLOW_NAV.map(({ to, label }) => {
            const active = isActive(pathname, to);
            return (
              <Link
                key={to}
                to={to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative px-3 pb-2.5 pt-1 text-[13px] transition-colors",
                  active ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
                {active ? <span className="absolute inset-x-3 bottom-0 h-px bg-foreground" /> : null}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
