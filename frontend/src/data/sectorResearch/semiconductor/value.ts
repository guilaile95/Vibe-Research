import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "Global semiconductor equipment market:  in 2023, China ~30%. Highest substitution elasticity in equipment and materials.",
    sourceIds: ["S-SEMI-MIIT-POLICY", "S-SEMI-NAURA-FILING"],
  },
  {
    type: "bullets",
    items: ["Equipment: , 10-15% domestic, high potential.", "Materials: , 20-25% domestic, medium-high.", "EDA/IP: , <10% domestic, ecosystem barrier.", "Advanced packaging: , 25-30%, closest to global."],
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
  {
    type: "callout",
    tone: "info",
    text: "Pending: order growth sustainability and EDA revenue validation.",
    sourceIds: ["S-SEMI-NAURA-FILING"],
  },
  {
    type: "risk",
    items: ["Capex cyclicality risk.", "Substitution valuation premium risk."],
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
];