import type { ContentBlock } from "../types.ts";

export const processBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "Wafer fabrication involves lithography, etching, deposition, ion implantation, and CMP. Core equipment includes etchers, deposition tools, and inspection systems.",
    sourceIds: ["S-SEMI-AMEC-FILING", "S-SEMI-NAURA-FILING"],
  },
  {
    type: "bullets",
    items: ["Lithography: circuit pattern transfer; EUV for sub-7nm.", "Etching: CCP/ICP for high aspect ratio 3D NAND.", "Deposition: CVD/PVD/ALD for thin films.", "CMP: planarization for copper interconnects."],
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-ANJI-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "Pending verification: domestic etching at 3nm; ALD stability in high-k production.",
    sourceIds: ["S-SEMI-AMEC-FILING", "S-SEMI-NAURA-FILING"],
  },
  {
    type: "risk",
    items: ["EUV restricted by Netherlands controls.", "Verification cycle 12-24 months.", "US component dependency risk."],
    sourceIds: ["S-SEMI-AMEC-FILING", "S-SEMI-NAURA-FILING"],
  },
];