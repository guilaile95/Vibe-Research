import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { aiComputingSources } from "./ai-computing/sources.ts";
import { overviewBlocks } from "./ai-computing/overview.ts";
import { architectureBlocks } from "./ai-computing/architecture.ts";
import { valueBlocks } from "./ai-computing/value.ts";
import { scaleUpBlocks } from "./ai-computing/scale-up.ts";
import { industryBlocks } from "./ai-computing/industry.ts";
import { pricingBlocks } from "./ai-computing/pricing.ts";

export const aiComputingResearch: SectorResearchWorkspace = {
  key: "ai-computing",
  label: "AI算力",
  fullName: "AI算力（AI Computing Infrastructure）",
  tagline: "大模型时代的物理底座——芯片、服务器、高速网络与绿色液冷基础设施",
  defaultTag: "overview",
  sources: aiComputingSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "architecture", label: "算力系统架构", title: "算力系统架构", status: "draft", blocks: architectureBlocks },
    { slug: "value", label: "单机、单柜与集群价值量", title: "单机、单柜与集群价值量", status: "draft", blocks: valueBlocks },
    { slug: "scale-up", label: "Scale-up 网络与机柜架构", title: "Scale-up 网络与机柜架构", status: "draft", blocks: scaleUpBlocks },
    { slug: "industry", label: "芯片、服务器、网络、散热产业格局", title: "芯片、服务器、网络、散热产业格局", status: "draft", blocks: industryBlocks },
    { slug: "pricing", label: "供给约束、定价权与资本开支信号", title: "供给约束、定价权与资本开支信号", status: "draft", blocks: pricingBlocks },
  ],
};

assertWorkspaceInvariants(aiComputingResearch);
