import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type SectionId = "overview" | "fundamentals" | "research" | "capital" | "signals" | "thesis";

type Section = {
  id: SectionId;
  label: string;
  headings: string[];
};

const SECTIONS: Section[] = [
  { id: "overview", label: "概览", headings: [] },
  { id: "fundamentals", label: "基本面", headings: ["关键财务指标", "估值历史分位", "财务关键指标"] },
  { id: "research", label: "研究", headings: ["近期研报", "近期公告", "个股新闻", "投资者互动"] },
  { id: "capital", label: "资金", headings: ["资金面 · 筹码", "龙虎榜", "限售解禁", "板块归属 · 概念"] },
  { id: "signals", label: "信号", headings: ["顶部风险", "技术指标", "扩展数据"] },
  { id: "thesis", label: "逻辑", headings: ["投资逻辑"] },
];

function normalizedText(node: Element | null): string {
  return (node?.textContent || "").replace(/\s+/g, " ").trim();
}

function findHeading(root: HTMLElement, candidates: string[]): HTMLElement | null {
  const headings = Array.from(root.querySelectorAll<HTMLElement>("h2, h3, [data-workspace-heading]"));
  for (const candidate of candidates) {
    const match = headings.find((heading) => normalizedText(heading).includes(candidate));
    if (match) return match;
  }
  return null;
}

function sectionTarget(root: HTMLElement, section: Section): HTMLElement | null {
  if (section.id === "overview") {
    const active = root.querySelector<HTMLElement>("[data-active-code]");
    if (!active?.dataset.activeCode) return null;
    const identity = active.querySelector<HTMLElement>("h2");
    return identity?.closest<HTMLElement>(".card-surface, [class*='rounded']") || identity || active;
  }

  const heading = findHeading(root, section.headings);
  if (!heading) return null;
  return heading.closest<HTMLElement>(".card-surface, [data-workspace-section]") || heading;
}

function readActiveCode(root: HTMLElement): string {
  return root.querySelector<HTMLElement>("[data-active-code]")?.dataset.activeCode || "";
}

function sameSectionSet(a: Set<SectionId>, b: Set<SectionId>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) if (!b.has(id)) return false;
  return true;
}

function preferredScrollBehavior(): ScrollBehavior {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "smooth";
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

export function StockWorkspaceShell({ children }: { children: ReactNode }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [activeCode, setActiveCode] = useState("");
  const [available, setAvailable] = useState<Set<SectionId>>(() => new Set());
  const [activeSection, setActiveSection] = useState<SectionId>("overview");

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    let frame = 0;
    const scan = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const code = readActiveCode(root);
        setActiveCode((current) => (current === code ? current : code));

        const next = new Set<SectionId>();
        if (code) {
          for (const section of SECTIONS) {
            if (sectionTarget(root, section)) next.add(section.id);
          }
        }
        setAvailable((current) => (sameSectionSet(current, next) ? current : next));
      });
    };

    scan();
    const observer = new MutationObserver(scan);
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-active-code"],
    });
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !activeCode) return;

    const candidates = SECTIONS
      .map((section) => ({ section, target: sectionTarget(root, section) }))
      .filter((item): item is { section: Section; target: HTMLElement } => Boolean(item.target));
    if (!candidates.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (!visible) return;
        const found = candidates.find((item) => item.target === visible.target);
        if (found) setActiveSection(found.section.id);
      },
      { rootMargin: "-18% 0px -70% 0px", threshold: [0, 0.01] },
    );

    candidates.forEach((item) => observer.observe(item.target));
    return () => observer.disconnect();
  }, [activeCode, available]);

  useEffect(() => {
    if (!activeCode) return;
    const hash = window.location.hash.replace(/^#/, "") as SectionId;
    if (!SECTIONS.some((section) => section.id === hash)) return;

    const timer = window.setTimeout(() => {
      const root = rootRef.current;
      const section = SECTIONS.find((item) => item.id === hash);
      if (!root || !section) return;
      sectionTarget(root, section)?.scrollIntoView({
        behavior: preferredScrollBehavior(),
        block: "start",
      });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [activeCode]);

  const visibleSections = useMemo(
    () => SECTIONS.filter((section) => available.has(section.id)),
    [available],
  );

  const go = (section: Section) => {
    const root = rootRef.current;
    if (!root) return;
    const target = sectionTarget(root, section);
    if (!target) return;

    setActiveSection(section.id);
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}#${section.id}`,
    );
    target.scrollIntoView({ behavior: preferredScrollBehavior(), block: "start" });
  };

  return (
    <div ref={rootRef} className="relative flex flex-col xl:grid xl:grid-cols-[minmax(0,1fr)_8.5rem] xl:gap-7">
      <div className="min-w-0">{children}</div>

      {activeCode && visibleSections.length > 1 ? (
        <aside className="order-first mb-5 xl:order-none xl:mb-0" aria-label="股票工作区导航">
          <div className="sticky top-0 z-20 -mx-1 overflow-x-auto border-y border-border/45 bg-background/95 px-1 py-1.5 backdrop-blur-md xl:top-4 xl:mx-0 xl:overflow-visible xl:border-y-0 xl:border-l xl:bg-transparent xl:px-0 xl:py-1 xl:pl-3 xl:backdrop-blur-none">
            <div className="flex min-w-max items-center xl:min-w-0 xl:flex-col xl:items-stretch">
              <div className="hidden px-2 pb-2 pt-1 xl:block">
                <p className="font-mono text-[11px] font-medium text-foreground">{activeCode}</p>
                <p className="mt-0.5 text-[10px] text-muted-foreground/70">个股工作区</p>
              </div>
              {visibleSections.map((section) => {
                const active = section.id === activeSection;
                return (
                  <button
                    key={section.id}
                    type="button"
                    onClick={() => go(section)}
                    aria-current={active ? "location" : undefined}
                    className={cn(
                      "relative min-h-8 px-2.5 py-1.5 text-left text-xs transition-colors xl:w-full",
                      active
                        ? "font-medium text-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {section.label}
                    {active ? (
                      <span className="absolute inset-x-2 bottom-0 h-px bg-foreground xl:inset-y-1.5 xl:-left-[13px] xl:right-auto xl:h-auto xl:w-px" />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        </aside>
      ) : null}
    </div>
  );
}
