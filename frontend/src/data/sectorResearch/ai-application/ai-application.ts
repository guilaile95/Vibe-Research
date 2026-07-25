import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { aiApplicationSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { officeAgentBlocks } from "./office-agent.ts";
import { codingAgentBlocks } from "./coding-agent.ts";
import { industryAiBlocks } from "./industry-ai.ts";
import { multimodalBlocks } from "./multimodal.ts";
import { industryBlocks } from "./industry.ts";

export const aiApplicationResearch: SectorResearchWorkspace = {
  key: "ai-application",
  label: "AI 应用",
  fullName: "AI 应用（AI Application & Agent）",
  tagline: "大模型落地的应用与 Agent",
  defaultTag: "overview",
  sources: aiApplicationSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "office-agent", label: "办公Agent", title: "办公Agent", status: "draft", blocks: officeAgentBlocks },
    { slug: "coding-agent", label: "编程Agent", title: "编程Agent", status: "draft", blocks: codingAgentBlocks },
    { slug: "industry-ai", label: "行业应用", title: "行业应用", status: "draft", blocks: industryAiBlocks },
    { slug: "multimodal", label: "多模态", title: "多模态", status: "draft", blocks: multimodalBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(aiApplicationResearch);
