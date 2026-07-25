import type { ContentBlock } from "../types.ts";

export const electrochemicalBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "电化学储能是新型储能主力：宁德时代天恒储能系统实现5年零衰减，比亚迪Cube系统搭载刀片电池技术，循环寿命与安全性能行业领先（公司口径）。",
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-BYD-FILING"],
  },
  {
    type: "paragraph",
    text: "电化学储能以锂离子电池为主流技术路线，储能时长2-4小时。电池循环寿命、安全性能与系统成本是核心竞争要素。宁德时代与比亚迪在储能电池电芯领域占据领先地位。",
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-BYD-FILING", "S-ESA-CNESA-DATA"],
  },
  {
    type: "compareTable",
    caption: "电化学储能主流技术路线对比",
    headers: ["技术路线", "能量密度", "循环寿命", "安全性", "主要应用"],
    rows: [
      ["磷酸铁锂(LFP)", "中等", "6000+次", "高", "大型储能/工商业储能"],
      ["三元锂(NCM)", "高", "3000-5000次", "中等", "高端户储/特殊场景"],
      ["钠离子电池", "中低", "3000-5000次", "高", "低成本储能/两轮车"],
      ["液流电池(全钒)", "低", "10000+次", "极高", "4-8小时长时储能"],
      ["铅碳电池", "低", "2000-3000次", "中等", "备电/低速场景"],
    ],
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-BYD-FILING", "S-ESA-CNESA-DATA"],
  },
  {
    type: "bullets",
    items: [
      "宁德时代：天恒储能系统实现首5年零衰减、6MWh级储能柜，LFP+大容量电芯技术领先（公司口径）。",
      "比亚迪：刀片电池储能系统Cube系列，高集成度与高安全性能（公司口径）。",
      "行业趋势：314Ah+大容量储能电芯普及，20英尺5MWh+集装箱储能成为主流配置。",
      "海外市场：欧美户储+大储需求旺盛，海外项目利润率高于国内。",
    ],
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-BYD-FILING", "S-ESA-CNESA-DATA"],
  },
];
