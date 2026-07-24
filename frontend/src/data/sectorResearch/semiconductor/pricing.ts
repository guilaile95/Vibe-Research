import type { ContentBlock } from "../types.ts";

export const pricingBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "Pricing power comes from technology irreplaceability, verification barriers, and policy. The cycle: breakthrough-qualification-share-scale.",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING", "S-SEMI-MIIT-POLICY"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "Falsification: if global downturn reduces capex, domestic pricing advantage may temporarily lose substitution premium logic.",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING"],
  },
  {
    type: "risk",
    items: ["Capacity oversupply risk in mature nodes", "Technology iteration risk", "Tariff and trade barrier risk"],
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-SMIC-FILING"],
  },
];
