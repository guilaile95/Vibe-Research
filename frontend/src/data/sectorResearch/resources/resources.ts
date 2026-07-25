import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { resourcesSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { rareEarthBlocks } from "./rare-earth.ts";
import { germaniumBlocks } from "./germanium.ts";
import { lithiumBlocks } from "./lithium.ts";
import { tungstenBlocks } from "./tungsten.ts";
import { industryBlocks } from "./industry.ts";

export const resourcesResearch: SectorResearchWorkspace = {
  key: "resources",
  label: "资源卡口",
  fullName: "资源卡口（Critical Resources）",
  tagline: "稀土、锗、铟等被卡的关键资源",
  defaultTag: "overview",
  sources: resourcesSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "rare-earth", label: "稀土", title: "稀土", status: "draft", blocks: rareEarthBlocks },
    { slug: "germanium", label: "锗铟镓", title: "锗铟镓", status: "draft", blocks: germaniumBlocks },
    { slug: "lithium", label: "锂钴镍", title: "锂钴镍", status: "draft", blocks: lithiumBlocks },
    { slug: "tungsten", label: "钨钼", title: "钨钼", status: "draft", blocks: tungstenBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(resourcesResearch);
