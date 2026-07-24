import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "Semiconductor is the hardware foundation. China relies heavily on imports for equipment, materials, EDA, and advanced process.",
    sourceIds: ["S-SEMI-MIIT-POLICY", "S-SEMI-EMP2024"],
  },
  {
    type: "bullets",
    items: ["Equipment domestic rate: 10-15%", "Materials domestic rate: 20-25%", "EDA/IP domestic rate: <10%", "Advanced process sub-7nm restricted"],
    sourceIds: ["S-SEMI-EMP2024"],
  },
  {
    type: "callout",
    tone: "info",
    text: "Pending verification: 1) domestic advanced process; 2) EUV policy; 3) EDA success rate.",
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "Falsification: if export controls tighten or yields stay below expectations, timeline delayed.",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING"],
  },
  {
    type: "risk",
    items: ["Export control escalation risk", "Advanced process uncertainty", "Capacity utilization cyclicality"],
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-EMP2024"],
  },
];
