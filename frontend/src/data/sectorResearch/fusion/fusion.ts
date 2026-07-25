import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { fusionSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { magneticBlocks } from "./magnetic.ts";
import { superconductingBlocks } from "./superconducting.ts";
import { firstwallBlocks } from "./firstwall.ts";
import { plasmaBlocks } from "./plasma.ts";
import { industryBlocks } from "./industry.ts";

export const fusionResearch: SectorResearchWorkspace = {
  key: "fusion",
  label: "可控核聚变",
  fullName: "可控核聚变（Magnetic Confinement Fusion）",
  tagline: "磁约束、超导与第一壁材料",
  defaultTag: "overview",
  sources: fusionSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "magnetic", label: "磁约束", title: "磁约束与托卡马克", status: "draft", blocks: magneticBlocks },
    { slug: "superconducting", label: "超导材料", title: "超导材料", status: "draft", blocks: superconductingBlocks },
    { slug: "firstwall", label: "第一壁", title: "第一壁与偏滤器", status: "draft", blocks: firstwallBlocks },
    { slug: "plasma", label: "等离子体", title: "等离子体物理与加热", status: "draft", blocks: plasmaBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(fusionResearch);
