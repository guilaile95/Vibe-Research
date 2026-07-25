import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { aiPharmaSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { aiDrugBlocks } from "./ai-drug.ts";
import { geneTherapyBlocks } from "./gene-therapy.ts";
import { cxoBlocks } from "./cxo.ts";
import { devicesBlocks } from "./devices.ts";
import { industryBlocks } from "./industry.ts";

export const aiPharmaResearch: SectorResearchWorkspace = {
  key: "ai-pharma",
  label: "生物医药/AI制药",
  fullName: "生物医药/AI制药（Biotech & AI Pharma）",
  tagline: "创新药、AI 制药与生物技术",
  defaultTag: "overview",
  sources: aiPharmaSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "ai-drug", label: "AI制药", title: "AI制药", status: "draft", blocks: aiDrugBlocks },
    { slug: "gene-therapy", label: "基因治疗", title: "基因治疗", status: "draft", blocks: geneTherapyBlocks },
    { slug: "cxo", label: "CXO", title: "CXO", status: "draft", blocks: cxoBlocks },
    { slug: "devices", label: "医疗器械", title: "医疗器械", status: "draft", blocks: devicesBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(aiPharmaResearch);
