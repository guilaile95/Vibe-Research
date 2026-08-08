import { Link, useLocation } from "react-router-dom";
import { BookOpen, History, Search, ShieldCheck, Wallet, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface WorkflowItem {
  to: string;
  label: string;
  hint: string;
  icon: LucideIcon;
}

const WORKFLOW_NAV: WorkflowItem[] = [
  { to: "/stock-data", label: "研究", hint: "Research", icon: Search },
  { to: "/thesis", label: "逻辑", hint: "Thesis", icon: BookOpen },
  { to: "/decision-evidence", label: "依据", hint: "Evidence", icon: ShieldCheck },
  { to: "/portfolio", label: "持仓", hint: "Position", icon: Wallet },
  { to: "/decision-feedback", label: "复盘", hint: "Review", icon: History },
];

function isActive(pathname: string, to: string) {
  if (to === "/thesis" && pathname.startsWith("/thesis/")) return true;
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function ResearchWorkflowNav() {
  const { pathname } = useLocation();

  return (
    <div className="mb-6 flex min-w-0 items-end gap-4 border-b border-border/45">
      <div className="hidden shrink-0 pb-2.5 lg:block">
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground/60">Workspace</p>
        <p className="mt-0.5 text-[12px] font-medium text-muted-foreground">研究工作区</p>
      </div>

      <nav aria-label="研究工作区" className="min-w-0 flex-1 overflow-x-auto">
        <div className="flex min-w-max items-center gap-0.5">
          {WORKFLOW_NAV.map(({ to, label, hint, icon: Icon }) => {
            const active = isActive(pathname, to);
            return (
              <Link
                key={to}
                to={to}
                aria-current={active ? "page" : undefined}
                title={`${label} · ${hint}`}
                className={cn(
                  "group relative flex min-h-11 items-center gap-2 px-3 pb-2.5 pt-1.5 text-[13px] transition-colors",
                  active ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className={cn("h-3.5 w-3.5", active ? "text-foreground" : "text-muted-foreground/70 group-hover:text-foreground")} />
                <span>{label}</span>
                <span className="hidden text-[10px] font-normal text-muted-foreground/55 2xl:inline">{hint}</span>
                {active ? <span className="absolute inset-x-2 bottom-0 h-px bg-foreground" /> : null}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
