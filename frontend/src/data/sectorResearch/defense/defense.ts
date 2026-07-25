import type { SectorResearchWorkspace } from "../types.ts";
import { assertWorkspaceInvariants } from "../types.ts";
import { defenseSources } from "./sources.ts";
import { overviewBlocks } from "./overview.ts";
import { aviationBlocks } from "./aviation.ts";
import { aerospaceBlocks } from "./aerospace.ts";
import { navalBlocks } from "./naval.ts";
import { informatizationBlocks } from "./informatization.ts";
import { industryBlocks } from "./industry.ts";

export const defenseResearch: SectorResearchWorkspace = {
  key: "defense",
  label: "军工",
  fullName: "军工（Defense Industry）",
  tagline: "航空、航天、船舶与信息化",
  defaultTag: "overview",
  sources: defenseSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "aviation", label: "航空", title: "航空", status: "draft", blocks: aviationBlocks },
    { slug: "aerospace", label: "航天", title: "航天", status: "draft", blocks: aerospaceBlocks },
    { slug: "naval", label: "船舶", title: "船舶", status: "draft", blocks: navalBlocks },
    { slug: "informatization", label: "信息化", title: "军工信息化", status: "draft", blocks: informatizationBlocks },
    { slug: "industry", label: "产业格局", title: "产业格局", status: "draft", blocks: industryBlocks },
  ],
};

assertWorkspaceInvariants(defenseResearch);
