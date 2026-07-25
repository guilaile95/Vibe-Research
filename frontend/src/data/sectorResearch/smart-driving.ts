import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { smartDrivingSources } from "./smart-driving/sources.ts";
import { overviewBlocks } from "./smart-driving/overview.ts";
import { architectureBlocks } from "./smart-driving/architecture.ts";
import { valueBlocks } from "./smart-driving/value.ts";
import { nextGenBlocks } from "./smart-driving/next-gen.ts";
import { industryBlocks } from "./smart-driving/industry.ts";
import { pricingBlocks } from "./smart-driving/pricing.ts";

/**
 * 智能驾驶（Smart Driving）研究工作台 —— 六 Tag 正式内容（证据草案状态）。
 * 内容按 Tag 分拆到 smart-driving/<slug>.ts，共享来源注册表在 smart-driving/sources.ts。
 */
export const smartDrivingResearch: SectorResearchWorkspace = {
  key: "smart-driving",
  label: "智能驾驶",
  fullName: "智能驾驶（Smart Driving）",
  tagline: "感知→计算→执行的智能化闭环——融合传感器、域控、线控与 AI 算法的汽车产业主线",
  defaultTag: "overview",
  sources: smartDrivingSources,
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
      label: "感知、计算、规划与线控",
      title: "感知、计算、规划与线控",
      status: "draft",
      blocks: architectureBlocks,
    },
    {
      slug: "value",
      label: "单车价值量",
      title: "单车价值量",
      status: "draft",
      blocks: valueBlocks,
    },
    {
      slug: "next-gen",
      label: "端到端、城市 NOA 与 Robotaxi",
      title: "端到端、城市 NOA 与 Robotaxi",
      status: "draft",
      blocks: nextGenBlocks,
    },
    {
      slug: "industry",
      label: "芯片、算法、零部件与车企格局",
      title: "芯片、算法、零部件与车企格局",
      status: "draft",
      blocks: industryBlocks,
    },
    {
      slug: "pricing",
      label: "软件收费、成本转嫁和监管风险",
      title: "软件收费、成本转嫁和监管风险",
      status: "draft",
      blocks: pricingBlocks,
    },
  ],
};

assertWorkspaceInvariants(smartDrivingResearch);
