import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { energyStorageSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { electrochemicalBlocks } from "./electrochemical.ts";
import { integrationBlocks } from "./integration.ts";
import { pcsBlocks } from "./pcs.ts";
import { gridSideBlocks } from "./grid-side.ts";
import { industryBlocks } from "./industry.ts";

export const energyStorageResearch: SectorResearchWorkspace = {
  key: "energy-storage",
  label: "储能",
  fullName: "储能（Energy Storage）",
  tagline: "电化学储能与电网侧调峰",
  defaultTag: "overview",
  sources: energyStorageSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "electrochemical", label: "电化学储能", title: "电化学储能", status: "draft", blocks: electrochemicalBlocks },
    { slug: "integration", label: "系统集成", title: "系统集成", status: "draft", blocks: integrationBlocks },
    { slug: "pcs", label: "变流器", title: "变流器", status: "draft", blocks: pcsBlocks },
    { slug: "grid-side", label: "电网侧", title: "电网侧", status: "draft", blocks: gridSideBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(energyStorageResearch);
