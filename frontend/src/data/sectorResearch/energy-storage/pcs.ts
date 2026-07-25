import type { ContentBlock } from "../types.ts";

export const pcsBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "储能PCS是储能系统与电网的接口：阳光电源储能变流器全球出货量领先，科士达、盛弘股份在工商业储能PCS领域占据重要份额（公司口径）。",
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING"],
  },
  {
    type: "paragraph",
    text: "储能变流器（PCS）实现电池直流电与交流电网的相互转换，是储能系统的核心电力电子设备。按功率等级分为大储PCS（250kW+）、工商业储能PCS（50-250kW）与户用PCS（5-50kW）。",
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-KSTAR-FILING"],
  },
  {
    type: "compareTable",
    caption: "储能PCS三大应用场景与代表厂商",
    headers: ["应用场景", "功率等级", "核心要求", "代表厂商"],
    rows: [
      ["大型储能", "250kW-6MW+", "电网级响应、多机并联、黑启动", "阳光电源、科华数据、上能电气"],
      ["工商业储能", "50-250kW", "峰谷套利、需量管理、安全", "科士达、盛弘股份、阳光电源"],
      ["户用储能", "5-50kW", "离并网切换、静音、美观", "科士达、盛弘股份、锦浪科技"],
    ],
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING"],
  },
  {
    type: "bullets",
    items: [
      "阳光电源：PowerTian系列大储PCS全球出货量领先，1500V/3450kW组串式PCS技术领先（公司口径）。",
      "科士达：储能PCS与数据中心协同发展，海外户储与大型储能项目双轮驱动（公司口径）。",
      "盛弘股份：储能PCS与电能质量设备协同发展，工商业储能项目快速增长（公司口径）。",
      "技术趋势：组串式PCS替代集中式，单机大容量+智能运维是演进方向。",
    ],
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-KSTAR-FILING", "S-ESA-SHENGHONG-FILING", "S-ESA-CNESA-DATA"],
  },
];
