import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { aiHardwareSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { aiGlassesBlocks } from "./ai-glasses.ts";
import { edgeChipBlocks } from "./edge-chip.ts";
import { wearableBlocks } from "./wearable.ts";
import { smartHomeBlocks } from "./smart-home.ts";
import { industryBlocks } from "./industry.ts";

export const aiHardwareResearch: SectorResearchWorkspace = {
  key: "ai-hardware",
  label: "AI 硬件",
  fullName: "AI 硬件（AI Glasses & Edge Devices）",
  tagline: "端侧、AI 眼镜与消费终端",
  defaultTag: "overview",
  sources: aiHardwareSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "ai-glasses", label: "AI眼镜", title: "AI眼镜", status: "draft", blocks: aiGlassesBlocks },
    { slug: "edge-chip", label: "端侧芯片", title: "端侧芯片", status: "draft", blocks: edgeChipBlocks },
    { slug: "wearable", label: "可穿戴", title: "可穿戴", status: "draft", blocks: wearableBlocks },
    { slug: "smart-home", label: "智能家居", title: "智能家居", status: "draft", blocks: smartHomeBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(aiHardwareResearch);
