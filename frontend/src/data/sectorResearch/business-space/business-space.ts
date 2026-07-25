import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { businessSpaceSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { rocketBlocks } from "./rocket.ts";
import { satelliteBlocks } from "./satellite.ts";
import { internetBlocks } from "./internet.ts";
import { ttcBlocks } from "./ttc.ts";
import { industryBlocks } from "./industry.ts";

export const businessSpaceResearch: SectorResearchWorkspace = {
  key: "business-space",
  label: "商业航天",
  fullName: "商业航天（Commercial Space）",
  tagline: "火箭、卫星制造与卫星互联网",
  defaultTag: "overview",
  sources: businessSpaceSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "rocket", label: "火箭", title: "运载火箭", status: "draft", blocks: rocketBlocks },
    { slug: "satellite", label: "卫星制造", title: "卫星制造", status: "draft", blocks: satelliteBlocks },
    { slug: "internet", label: "卫星互联网", title: "卫星互联网", status: "draft", blocks: internetBlocks },
    { slug: "ttc", label: "测控", title: "测控与航天电子", status: "draft", blocks: ttcBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(businessSpaceResearch);
