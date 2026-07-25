import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { innovativeDrugSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { targetBlocks } from "./target.ts";
import { clinicalBlocks } from "./clinical.ts";
import { cxoBlocks } from "./cxo.ts";
import { chuhaiBlocks } from "./chuhai.ts";
import { industryBlocks } from "./industry.ts";

export const innovativeDrugResearch: SectorResearchWorkspace = {
  key: "innovative-drug",
  label: "创新药",
  fullName: "创新药（Innovative Drug）",
  tagline: "靶点、临床、CXO 与出海",
  defaultTag: "overview",
  sources: innovativeDrugSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "target", label: "靶点与前沿技术", title: "靶点与前沿技术", status: "draft", blocks: targetBlocks },
    { slug: "clinical", label: "临床管线", title: "临床管线", status: "draft", blocks: clinicalBlocks },
    { slug: "cxo", label: "CXO 一体化服务", title: "CXO 一体化服务", status: "draft", blocks: cxoBlocks },
    { slug: "chuhai", label: "出海与授权", title: "出海与授权", status: "draft", blocks: chuhaiBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(innovativeDrugResearch);
