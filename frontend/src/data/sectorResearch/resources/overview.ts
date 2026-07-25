import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层制度：国务院令第784号《稀土管理条例》明确稀土开采、冶炼分离总量调控指标管理，实行稀土产品追溯制度。自然资源部将稀土、锗、镓、铟、钨、钼等列为战略性矿产，实施保护性开采。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS"],
  },
  {
    type: "paragraph",
    text: "资源卡口板块涵盖稀土、锗铟镓、锂钴镍、钨钼等关键战略资源。这些资源在新能源、半导体、国防军工等领域具有不可替代性，且中国在全球供应链中占据主导地位，是应对外部技术封锁的重要筹码。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS", "S-RES-BEIRARE-FILING"],
  },
  {
    type: "bullets",
    items: [
      "稀土：中国稀土储量与产量全球第一，北方稀土/中国稀土主导开采与冶炼分离，稀土永磁材料是新能源与军工核心材料。",
      "锗铟镓：锗用于红外光学与光纤通信，铟用于ITO靶材与显示面板，镓用于半导体与LED，中国产量全球主导。",
      "锂钴镍：锂是动力电池核心材料，钴用于高能量密度电池，镍用于高镍三元正极，华友钴业等布局全球资源。",
      "钨钼：钨用于硬质合金与军工，钼用于特种钢与高温合金，中国储量与产量全球领先。",
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-YUNNAN-GE-FILING", "S-RES-HUAYOU-FILING", "S-RES-ZUYE-FILING"],
  },
  {
    type: "table",
    caption: "关键战略资源与中国主导地位",
    headers: ["资源类别", "核心用途", "中国全球占比", "代表A股厂商"],
    rows: [
      ["稀土", "永磁/催化/抛光/军工", "储量~40%，产量~70%", "北方稀土、中国稀土、金力永磁"],
      ["锗", "红外光学/光纤/光伏", "产量~60%", "云南锗业、株冶集团、驰宏锌锗"],
      ["铟", "ITO靶材/显示面板", "产量~50%", "株冶集团、锡业股份"],
      ["镓", "半导体/LED/5G", "产量~90%", "株冶集团、三安光电"],
      ["锂", "动力电池/储能", "储量~15%，加工~70%", "天齐锂业、赣锋锂业"],
      ["钴", "高能量密度电池", "冶炼~70%", "华友钴业、寒锐钴业"],
      ["镍", "高镍三元正极", "冶炼~60%", "华友钴业、盛屯矿业"],
      ["钨", "硬质合金/军工", "储量~60%，产量~80%", "厦门钨业、章源钨业"],
      ["钼", "特种钢/高温合金", "储量~50%，产量~40%", "金钼股份、洛阳钼业"],
    ],
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS", "S-RES-BEIRARE-FILING", "S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-HUAYOU-FILING"],
  },
];
