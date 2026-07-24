import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { ssBatterySources } from "./solid-state-battery/sources.ts";
import { overviewBlocks } from "./solid-state-battery/overview.ts";
import { chemistryBlocks } from "./solid-state-battery/chemistry.ts";
import { valueBlocks } from "./solid-state-battery/value.ts";
import { manufacturingBlocks } from "./solid-state-battery/manufacturing.ts";
import { industryBlocks } from "./solid-state-battery/industry.ts";
import { pricingBlocks } from "./solid-state-battery/pricing.ts";

export const ssBatteryResearch: SectorResearchWorkspace = {
  key: "solid-state-battery",
  label: "固态电池",
  fullName: "固态电池（Solid-State Battery）",
  tagline: "下一代动力电池的核心路线——安全性、能量密度与产业链重构",
  defaultTag: "overview",
  sources: ssBatterySources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "chemistry", label: "硫化物、氧化物和聚合物路线", title: "硫化物、氧化物和聚合物路线", status: "draft", blocks: chemistryBlocks },
    { slug: "value", label: "单机与材料价值量", title: "单机与材料价值量", status: "draft", blocks: valueBlocks },
    { slug: "manufacturing", label: "电解质、设备和量产工艺", title: "电解质、设备和量产工艺", status: "draft", blocks: manufacturingBlocks },
    { slug: "industry", label: "材料、电池厂和设备格局", title: "材料、电池厂和设备格局", status: "draft", blocks: industryBlocks },
    { slug: "pricing", label: "良率、成本、专利与量产信号", title: "良率、成本、专利与量产信号", status: "draft", blocks: pricingBlocks },
  ],
};

assertWorkspaceInvariants(ssBatteryResearch);
