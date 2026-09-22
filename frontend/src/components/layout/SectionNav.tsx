import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { activeSectionItem, sectionNavsOf } from "@/lib/navigation";

/**
 * 一级入口内部的二级导航。
 *
 * 取代旧的「研究链路」横条：之前那条横条的标签与侧栏同名却顺序不同，
 * 现在二级入口由 `navigation.ts` 的 SECTION_NAVS 统一驱动，
 * 只展示当前一级入口内部的页面，不再横向串起不相干的模块。
 */
export function SectionNav({ ownerId, pathname, title }: { ownerId: string | null; pathname: string; title: string }) {
  const groups = sectionNavsOf(ownerId);
  if (!groups.length) return null;

  const active = activeSectionItem(pathname, groups);

  return (
    <div className="mb-6 space-y-2" data-testid="section-nav" data-section-owner={ownerId ?? ""}>
      {groups.map((group, index) => (
        <div
          key={group.label ?? `primary-${index}`}
          className={cn(
            "flex min-w-0 items-center gap-3",
            index > 0 && "border-t border-border/40 pt-2",
          )}
        >
          <span className="hidden shrink-0 text-[11px] font-medium text-muted-foreground lg:inline">
            {group.label ?? title}
          </span>
          <nav
            aria-label={group.label ? `${title}·${group.label}` : title}
            className="min-w-0 flex-1 overflow-x-auto"
          >
            <div className="flex min-w-max items-center gap-1">
              {group.items.map((item) => {
                const itemActive = active === item.to;
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    aria-current={itemActive ? "page" : undefined}
                    className={cn(
                      "relative px-3 pb-2 pt-1 text-[13px] transition-colors",
                      itemActive ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {item.label}
                    {itemActive ? <span className="absolute inset-x-3 bottom-0 h-px bg-foreground" /> : null}
                  </Link>
                );
              })}
            </div>
          </nav>
        </div>
      ))}
    </div>
  );
}
