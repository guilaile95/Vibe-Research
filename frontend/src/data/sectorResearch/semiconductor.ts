import type { SectorResearchWorkspace } from "./types.ts";
import { overviewBlocks } from "./semiconductor/overview.ts";
import { processBlocks } from "./semiconductor/process.ts";
import { valueBlocks } from "./semiconductor/value.ts";
import { breakthroughBlocks } from "./semiconductor/breakthrough.ts";
import { industryBlocks } from "./semiconductor/industry.ts";
import { pricingBlocks } from "./semiconductor/pricing.ts";
import { semiconductorSources } from "./semiconductor/sources.ts";

export const semiconductorResearch: SectorResearchWorkspace = {
  key: "semiconductor",
  label: "半导体国产替代",
  fullName: "半导体产业链：设备、材料与国产替代",
  tagline: "设备、材料、EDA、制造的自主链条",
  defaultTag: "overview",
  sources: semiconductorSources,
  tags: [
    {
      slug: "overview",
      label: "总览",
      title: "总览",
      status: "draft",
      blocks: overviewBlocks,
    },
    {
      slug: "process",
      label: "晶圆制造流程与核心技术",
      title: "晶圆制造流程与核心技术",
      status: "draft",
      blocks: processBlocks,
    },
    {
      slug: "value",
      label: "设备和材料价值量",
      title: "设备和材料价值量",
      status: "draft",
      blocks: valueBlocks,
    },
    {
      slug: "breakthrough",
      label: "先进制程、先进封装和关键设备突破",
      title: "先进制程、先进封装和关键设备突破",
      status: "draft",
      blocks: breakthroughBlocks,
    },
    {
      slug: "industry",
      label: "全球供应链与国产化梯队",
      title: "全球供应链与国产化梯队",
      status: "draft",
      blocks: industryBlocks,
    },
    {
      slug: "pricing",
      label: "全球不可替代性与国产替代溢价",
      title: "全球不可替代性与国产替代溢价",
      status: "draft",
      blocks: pricingBlocks,
    },
  ],
};
