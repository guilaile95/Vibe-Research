import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { lowAltitudeSources } from "./low-altitude/sources.ts";
import { overviewBlocks } from "./low-altitude/overview.ts";
import { architectureBlocks } from "./low-altitude/architecture.ts";
import { valueBlocks } from "./low-altitude/value.ts";
import { airworthinessBlocks } from "./low-altitude/airworthiness.ts";
import { industryBlocks } from "./low-altitude/industry.ts";
import { pricingBlocks } from "./low-altitude/pricing.ts";

/**
 * 低空经济研究工作台 —— 六 Tag 正式内容（证据草案状态）。
 * 内容按 Tag 分拆到 low-altitude/<slug>.ts，共享来源注册表在 low-altitude/sources.ts。
 */
export const lowAltitudeResearch: SectorResearchWorkspace = {
  key: "low-altitude",
  label: "低空经济",
  fullName: "低空经济（Low-Altitude Economy）",
  tagline: "eVTOL、无人机与低空运营——政策驱动走向适航落地的万亿级赛道",
  defaultTag: "overview",
  sources: lowAltitudeSources,
  tags: [
    {
      slug: "overview",
      label: "总览",
      title: "总览",
      status: "draft",
      blocks: overviewBlocks,
    },
    {
      slug: "architecture",
      label: "飞行器、空域和运营体系",
      title: "飞行器、空域和运营体系",
      status: "draft",
      blocks: architectureBlocks,
    },
    {
      slug: "value",
      label: "eVTOL 与基础设施价值量",
      title: "eVTOL 与基础设施价值量",
      status: "draft",
      blocks: valueBlocks,
    },
    {
      slug: "airworthiness",
      label: "适航、量产和商业运营",
      title: "适航、量产和商业运营",
      status: "draft",
      blocks: airworthinessBlocks,
    },
    {
      slug: "industry",
      label: "整机、零部件、空管和运营格局",
      title: "整机、零部件、空管和运营格局",
      status: "draft",
      blocks: industryBlocks,
    },
    {
      slug: "pricing",
      label: "政策依赖、订单质量和盈利路径",
      title: "政策依赖、订单质量和盈利路径",
      status: "draft",
      blocks: pricingBlocks,
    },
  ],
};

assertWorkspaceInvariants(lowAltitudeResearch);
