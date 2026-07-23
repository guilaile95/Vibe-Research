import { Link } from "react-router-dom";
import { Flame, ChevronRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import sectorsData from "@/data/sectors.json";
import {
  getDefaultResearchPath,
  hasSectorResearchWorkspace,
} from "@/data/sectorResearch";
import { getSectorTagCount } from "@/data/sectorResearch/sectorTagPlans";

type SectorRow = (typeof sectorsData.sectors)[number] & {
  researchWorkspace?: boolean;
};

export function Sectors() {
  const sectors = sectorsData.sectors as SectorRow[];
  const hotCount = sectors.filter((s) => s.hot).length;

  return (
    <div>
      <PageHeader
        title="板块中心"
        subtitle={`${sectors.length} 个热门赛道的产业链骨架 · 只有环节，不含标的`}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sectors.map((s) => {
          const workspace = hasSectorResearchWorkspace(s.key) || s.researchWorkspace;
          const tagCount = getSectorTagCount(s.key);

          // 链接：完整研究工作台 → 默认 Tag；仅有 Tag 规划 → 通用详情；否则通用详情
          const href = workspace
            ? getDefaultResearchPath(s.key) ?? `/sectors/${s.key}`
            : `/sectors/${s.key}`;

          let footer: string;
          if (tagCount > 0) {
            footer = `${tagCount} 个研究栏目`;
          } else if (s.verified) {
            footer = `${s.nodes.length} 个环节`;
          } else {
            footer = "环节梳理中";
          }

          return (
            <Link key={s.key} to={href}>
              <GlassCard glow={s.hot} className="flex h-full flex-col justify-between">
                <div>
                  <div className="mb-1 flex items-center gap-2">
                    <h3 className="text-base font-bold">{s.label}</h3>
                    {s.hot && (
                      <span className="inline-flex items-center gap-0.5 rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                        <Flame className="h-3 w-3" /> 热门
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground">{s.tagline}</p>
                </div>
                <div className="mt-3 flex items-center justify-between border-t border-border/50 pt-3 text-xs">
                  <span className="text-muted-foreground">{footer}</span>
                  <ChevronRight className="h-4 w-4 text-primary" />
                </div>
              </GlassCard>
            </Link>
          );
        })}
      </div>

      <p className="mt-4 text-center text-xs text-muted-foreground/60">
        共 {sectors.length} 个板块，其中 {hotCount} 个热门 · 环节持续实时核实补全
      </p>
    </div>
  );
}
