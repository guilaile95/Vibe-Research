import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "储能板块呈现「电池龙头+PCS领先+系统集成多层次竞争」格局。宁德时代/比亚迪在电池电芯领域领先，阳光电源/科士达/盛弘在PCS领域占据主导，系统集成呈现多层次竞争。",
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-SUNGROW-FILING", "S-ESA-BYD-FILING"],
  },
  {
    type: "bullets",
    items: [
      "宁德时代：储能电池系统收入占比持续提升，天恒储能系统实现5年零衰减，全球储能电池市占率第一（公司口径）。",
      "阳光电源：储能变流器全球出货量领先，PowerTian储能系统海外大储项目中标（公司口径）。",
      "比亚迪：刀片电池储能系统Cube系列发布，海内外项目交付，海外收入增长（公司口径）。",
      "科士达：储能PCS与数据中心协同发展，海外户储与大型储能双轮驱动（公司口径）。",
      "盛弘股份：储能PCS与电能质量设备协同，工商业储能项目快速增长（公司口径）。",
    ],
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-SUNGROW-FILING", "S-ESA-BYD-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING"],
  },
  {
    type: "table",
    caption: "储能核心厂商竞争力矩阵",
    headers: ["厂商", "核心赛道", "护城河", "商业化进展", "事实/口径等级"],
    rows: [
      ["宁德时代", "储能电池", "电芯技术+规模优势", "天恒系统放量", "公司口径（年报披露）"],
      ["阳光电源", "储能PCS+系统集成", "电力电子+全球渠道", "海外大储中标", "公司口径（年报披露）"],
      ["比亚迪", "储能电池+系统", "刀片电池+系统能力", "Cube系列交付", "公司口径（年报披露）"],
      ["科士达", "PCS+系统集成", "数据中心+海外渠道", "户储+大储突破", "公司口径（年报披露）"],
      ["盛弘股份", "PCS+储能系统", "电能质量+工商业储能", "项目增长", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-ESA-CATL-FILING", "S-ESA-SUNGROW-FILING", "S-ESA-BYD-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING"],
  },
  {
    type: "risk",
    items: [
      "价格战风险：储能设备价格战激烈，电芯与PCS价格下行压缩厂商利润率。",
      "海外贸易风险：海外储能市场可能面临贸易壁垒与本地化政策限制。",
      "项目收益风险：独立储能项目收益受电力市场改革进度影响存在不确定性。",
      "产能过剩风险：电池与PCS产能快速扩张可能导致阶段性产能过剩。",
    ],
    sourceIds: ["S-ESA-NEA-NE-PLAN", "S-ESA-CNESA-DATA", "S-ESA-CATL-FILING"],
  },
];
