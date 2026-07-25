import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { humanoidSources } from "./humanoid/sources.ts";
import { overviewBlocks } from "./humanoid/overview.ts";
import { architectureBlocks } from "./humanoid/architecture.ts";
import { valueBlocks } from "./humanoid/value.ts";
import { actuatorsBlocks } from "./humanoid/actuators.ts";
import { industryBlocks } from "./humanoid/industry.ts";
import { pricingBlocks } from "./humanoid/pricing.ts";

export const humanoidResearch: SectorResearchWorkspace = {
  key: "humanoid",
  label: "人形机器人",
  fullName: "人形机器人（Humanoid Robotics）",
  tagline: "具身智能的最佳物理载体——融合AI大模型、精密传动、执行器与传感器",
  defaultTag: "overview",
  sources: humanoidSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "architecture", label: "机械、电控和具身智能架构", title: "机械、电控和具身智能架构", status: "draft", blocks: architectureBlocks },
    { slug: "value", label: "单机 BOM 与价值量", title: "单机 BOM 与价值量", status: "draft", blocks: valueBlocks },
    { slug: "actuators", label: "执行器、丝杠和灵巧手", title: "执行器、丝杠和灵巧手", status: "draft", blocks: actuatorsBlocks },
    { slug: "industry", label: "零部件、整机与客户格局", title: "零部件、整机与客户格局", status: "draft", blocks: industryBlocks },
    { slug: "pricing", label: "降本能力、客户认证和量产信号", title: "降本能力、客户认证和量产信号", status: "draft", blocks: pricingBlocks },
  ],
};

assertWorkspaceInvariants(humanoidResearch);
