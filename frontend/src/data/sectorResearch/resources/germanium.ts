import type { ContentBlock } from "../types.ts";

export const germaniumBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "锗铟镓是半导体与光电产业关键材料：中国锗产量全球占比超60%，镓产量占比超90%，对镓锗实施出口管制是应对外部技术封锁的重要手段（官方口径）。",
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-YUNNAN-GE-FILING"],
  },
  {
    type: "paragraph",
    text: "锗、铟、镓是稀散金属，主要作为锌、铝等大宗金属冶炼的副产品回收。这三种材料在红外光学、光纤通信、显示面板、半导体等领域具有不可替代性。",
    sourceIds: ["S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING"],
  },
  {
    type: "table",
    caption: "锗铟镓核心应用与代表厂商",
    headers: ["材料", "核心应用领域", "中国全球占比", "代表A股厂商"],
    rows: [
      ["锗", "红外光学、光纤通信、光伏（空间太阳电池）", "产量~60%", "云南锗业、株冶集团、驰宏锌锗"],
      ["铟", "ITO靶材（显示面板）、焊料、化合物半导体", "产量~50%", "株冶集团、锡业股份、锌业股份"],
      ["镓", "半导体（GaN/GaAs）、LED、5G射频", "产量~90%", "株冶集团、三安光电、乾照光电"],
    ],
    sourceIds: ["S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "bullets",
    items: [
      "云南锗业：国内锗龙头，锗矿开采、锗材料（红外级/光纤级/光伏级）全产业链布局（公司口径）。",
      "株冶集团：锌冶炼副产锗铟镓综合回收，锗铟镓产量国内领先（公司口径）。",
      "出口管制：2023年起对镓、锗实施出口许可证管理，是应对外部技术封锁的重要筹码。",
      "下游需求：红外热成像（军用/民用）、光纤通信、显示面板、5G基站驱动需求增长。",
    ],
    sourceIds: ["S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-MNR-MINERALS"],
  },
];
