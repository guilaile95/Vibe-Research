import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { clearResearchVisits, loadResearchVisits, RESEARCH_SECTIONS } from "@/lib/researchResume";

export function RecentResearch() {
  const [visits, setVisits] = useState(loadResearchVisits);
  useEffect(() => {
    const refresh = () => setVisits(loadResearchVisits());
    window.addEventListener("storage", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);
  if (!visits.length) return null;
  return (
    <section className="rounded-xl border border-border/60 bg-card/40 p-4" aria-labelledby="recent-research-title" data-testid="recent-research">
      <div className="flex items-center justify-between gap-2">
        <h2 id="recent-research-title" className="text-sm font-semibold">接着上次看</h2>
        <button type="button" className="px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground" onClick={() => { clearResearchVisits(); setVisits(loadResearchVisits()); }} aria-label="清除最近浏览记录">清除</button>
      </div>
      <ul className="divide-y divide-border/40">
        {visits.map((visit) => {
          const section = RESEARCH_SECTIONS.find(({ id }) => visit.href.endsWith(`#${id}`));
          return <li key={visit.code} className="py-2">
            <Link to={visit.href} className="block text-sm hover:text-primary" data-testid="resume-research">
              <span className="font-mono">{visit.code}</span><span className="ml-2 text-xs">{section?.label || "候选研究"} →</span>
            </Link>
            <p className="mt-1 text-[11px] text-muted-foreground">上次浏览 <time dateTime={visit.visitedAt}>{new Date(visit.visitedAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</time></p>
          </li>;
        })}
      </ul>
      <p className="mt-2 text-[11px] leading-5 text-muted-foreground">仅本浏览器最近位置。打开后重新读取资讯、证据缺口与已有研究变化。</p>
    </section>
  );
}
