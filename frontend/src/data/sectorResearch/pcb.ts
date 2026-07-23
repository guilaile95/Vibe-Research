import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { pcbSources } from "./pcb/sources.ts";
import { overviewBlocks } from "./pcb/overview.ts";
import { technologyBlocks } from "./pcb/technology.ts";
import { valueBlocks } from "./pcb/value.ts";
import { copperMidplaneBlocks } from "./pcb/copper-midplane.ts";
import { industryBlocks } from "./pcb/industry.ts";
import { pricingPowerBlocks } from "./pcb/pricing-power.ts";

/**
 * PCB（印制电路板）研究工作台 —— 六 Tag 正式内容。
 * 内容按 Tag 分拆到 pcb/<slug>.ts，共享来源注册表在 pcb/sources.ts。
 */
export const pcbResearch: SectorResearchWorkspace = {
  key: "pcb",
  label: "PCB",
  fullName: "PCB（印制电路板）",
  tagline: "AI 服务器的骨架公路——承载加速卡、内存、交换芯片、电源与高速互连",
  defaultTag: "overview",
  sources: pcbSources,
  tags: [
    {
      slug: "overview",
      label: "总览",
      title: "总览",
      status: "ready",
      blocks: overviewBlocks,
    },
    {
      slug: "technology",
      label: "原理与技术路线",
      title: "原理与技术路线",
      status: "ready",
      blocks: technologyBlocks,
    },
    {
      slug: "value",
      label: "价值量",
      title: "价值量",
      status: "ready",
      blocks: valueBlocks,
    },
    {
      slug: "copper-midplane",
      label: "铜中板",
      title: "铜中板",
      status: "ready",
      blocks: copperMidplaneBlocks,
    },
    {
      slug: "industry",
      label: "产业格局",
      title: "产业格局",
      status: "ready",
      blocks: industryBlocks,
    },
    {
      slug: "pricing-power",
      label: "定价权地图",
      title: "定价权地图",
      status: "ready",
      blocks: pricingPowerBlocks,
    },
  ],
};

assertWorkspaceInvariants(pcbResearch);
