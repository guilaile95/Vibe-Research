import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { powerGridSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { uhvBlocks } from "./uhv.ts";
import { transmissionBlocks } from "./transmission.ts";
import { newEnergyBlocks } from "./new-energy.ts";
import { intelligenceBlocks } from "./intelligence.ts";
import { industryBlocks } from "./industry.ts";

export const powerGridResearch: SectorResearchWorkspace = {
  key: "power-grid",
  label: "电网与特高压",
  fullName: "电网与特高压（Power Grid & UHV）",
  tagline: "输配电设备与新型电力系统",
  defaultTag: "overview",
  sources: powerGridSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "uhv", label: "特高压", title: "特高压", status: "draft", blocks: uhvBlocks },
    { slug: "transmission", label: "输配电", title: "输配电", status: "draft", blocks: transmissionBlocks },
    { slug: "new-energy", label: "新能源接入", title: "新能源接入", status: "draft", blocks: newEnergyBlocks },
    { slug: "intelligence", label: "智能化", title: "智能化", status: "draft", blocks: intelligenceBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(powerGridResearch);
