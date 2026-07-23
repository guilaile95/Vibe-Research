import type { SectorResearchWorkspace } from "./types.ts";
import { assertWorkspaceInvariants } from "./types.ts";
import { hbmSources } from "./hbm/sources.ts";
import { overviewBlocks } from "./hbm/overview.ts";
import { dramTsvBlocks } from "./hbm/dram-tsv.ts";
import { valueBlocks } from "./hbm/value.ts";
import { nextGenBlocks } from "./hbm/next-gen.ts";
import { industryBlocks } from "./hbm/industry.ts";
import { pricingBlocks } from "./hbm/pricing.ts";

export const hbmResearch: SectorResearchWorkspace = {
  key: "hbm",
  label: "HBM",
  fullName: "HBM（高带宽内存）",
  tagline: "突破‘内存墙’的显存利器——TSV硅通孔、垂直堆叠与先进封装",
  defaultTag: "overview",
  sources: hbmSources,
  tags: [
    { slug: "overview", label: "总览", title: "总览", status: "draft", blocks: overviewBlocks },
    { slug: "dram-tsv", label: "DRAM 堆叠与 TSV 原理", title: "DRAM 堆叠与 TSV 原理", status: "draft", blocks: dramTsvBlocks },
    { slug: "value", label: "单颗 GPU 和系统价值量", title: "单颗 GPU 和系统价值量", status: "draft", blocks: valueBlocks },
    { slug: "next-gen", label: "HBM4 / HBM4E 与下一代堆叠", title: "HBM4 / HBM4E 与下一代堆叠", status: "draft", blocks: nextGenBlocks },
    { slug: "industry", label: "DRAM、封装、设备与材料格局", title: "DRAM、封装、设备与材料格局", status: "draft", blocks: industryBlocks },
    { slug: "pricing", label: "产能分配、合约价与定价权", title: "产能分配、合约价与定价权", status: "draft", blocks: pricingBlocks },
  ],
};

assertWorkspaceInvariants(hbmResearch);
