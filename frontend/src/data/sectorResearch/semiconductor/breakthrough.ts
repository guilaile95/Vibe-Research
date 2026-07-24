import type { ContentBlock } from "../types.ts";

export const breakthroughBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "China accelerates in three dimensions: advanced process, 2.5D/3D Chiplet packaging, and critical equipment substitution.",
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-EMP2024"],
  },
  {
    type: "callout",
    tone: "info",
    text: "Industry outlook: 28nm mature, 14nm limited, sub-7nm in R&D. EUV remains bottleneck.",
    sourceIds: [],
  },
  {
    type: "callout",
    tone: "warning",
    text: "Falsification: if R&D exceeds 3 years or Chiplet ecosystem fragments, competitiveness weakens.",
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
  {
    type: "risk",
    items: ["EUV breakthrough risk: e-beam throughput gap.", "Chiplet standard US-China fragmentation risk."],
    sourceIds: ["S-SEMI-EMP2024"],
  },
];