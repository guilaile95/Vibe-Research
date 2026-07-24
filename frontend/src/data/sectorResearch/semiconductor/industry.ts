import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "Global semiconductor: US leads EDA/IP, Japan materials, Netherlands lithography, Korea/Taiwan memory and foundry.",
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
  {
    type: "bullets",
    items: ["Etching: NAURA/AMEC cover 7nm.", "Deposition: NAURA/Tokli 28nm+.", "Wafer: NSIG ramping 300mm.", "Foundry: SMIC/HuaHong mature nodes."],
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING", "S-SEMI-SMIC-FILING"],
  },
  {
    type: "risk",
    items: ["Geopolitical risk: US-China tech escalation.", "Talent shortage: R&D pipeline gap."],
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
];