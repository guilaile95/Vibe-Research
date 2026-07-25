import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { cpoSources } from "./cpo/sources.ts";
import { overviewBlocks } from "./cpo/overview.ts";
import { opticsBlocks } from "./cpo/optics.ts";
import { valueBlocks } from "./cpo/value.ts";
import { nextGenBlocks } from "./cpo/next-gen.ts";
import { industryBlocks } from "./cpo/industry.ts";
import { riskBlocks } from "./cpo/risk.ts";

export const cpoResearch: SectorResearchWorkspace = {
  key: "cpo",
  label: "光互联",
  fullName: "光互联与 CPO（Optical Interconnects & CPO）",
  tagline: "AI算力集群的高速血脉——800G/1.6T 光模块、硅光集成与 CPO 共封装",
  defaultTag: "overview",
  sources: cpoSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "optics", label: "光模块、硅光和 CPO 原理", title: "光模块、硅光和 CPO 原理", status: "draft", blocks: opticsBlocks },
    { slug: "value", label: "单端口和单集群价值量", title: "单端口和单集群价值量", status: "draft", blocks: valueBlocks },
    { slug: "next-gen", label: "1.6T / 3.2T / CPO", title: "1.6T / 3.2T / CPO", status: "draft", blocks: nextGenBlocks },
    { slug: "industry", label: "光芯片、器件、模块和代工格局", title: "光芯片、器件、模块和代工格局", status: "draft", blocks: industryBlocks },
    { slug: "risk", label: "供需、良率、价格与技术替代风险", title: "供需、良率、价格与技术替代风险", status: "draft", blocks: riskBlocks },
  ],
};

assertWorkspaceInvariants(cpoResearch);
