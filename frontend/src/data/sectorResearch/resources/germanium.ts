import type { ContentBlock } from "../types.ts";

export const germaniumBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "锗、铟、镓属稀散金属，多作为锌、铝等冶炼副产品回收。红外光学、光纤、显示 ITO、化合物半导体等下游使其具备战略属性；出口许可管理进一步强化「卡口」特征（官方口径/公司口径）。",
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-YUNNAN-GE-FILING", "S-RES-GOV-PORTAL"],
  },
  {
    type: "paragraph",
    text: "供给端与主金属（锌/铝）开工率绑定，难以像大宗矿山般独立快速扩产；需求端则受光纤建设、红外设备、显示面板与 GaN/GaAs 射频等拉动。政策管制改变贸易流向后，国内价格与出口结构可能阶段性背离（分析推断）。",
    sourceIds: ["S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "table",
    caption: "锗铟镓核心应用与代表厂商",
    headers: ["材料", "核心应用领域", "供给特征", "代表A股厂商"],
    rows: [
      ["锗", "红外光学、光纤、空间光伏等", "独立矿+冶炼副产", "云南锗业、株冶集团等"],
      ["铟", "ITO 靶材、焊料、化合物半导体", "锌冶炼副产为主", "株冶集团等"],
      ["镓", "GaN/GaAs、LED、射频", "铝冶炼等副产", "株冶集团等"],
    ],
    sourceIds: ["S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "compareTable",
    caption: "出口管制敏感金属的研究框架（内部分析）",
    headers: ["观察层", "关键问题", "可用信息源"],
    rows: [
      ["政策层", "许可范围、执行尺度、对端反制", "政府网/商务部等公开信息"],
      ["供给层", "主金属开工、回收产能、库存", "公司定期报告、行业统计"],
      ["需求层", "光纤/红外/面板/射频景气", "下游产业链公开数据"],
      ["价格层", "内盘与出口价差、贸易重定向", "现货报价（需独立核验）"],
    ],
    sourceIds: ["S-RES-GOV-PORTAL", "S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING"],
  },
  {
    type: "bullets",
    items: [
      "云南锗业：锗产业链相对完整，材料分级（红外/光纤等）是差异化点（公司口径）。",
      "株冶集团：锌冶炼体系下的稀散金属综合回收，锗铟镓产量与锌开工相关（公司口径）。",
      "镓与半导体周期联动强，但供给弹性低，价格易出现脉冲（分析推断）。",
      "下游若加速材料替代或回收，将削弱管制带来的长期溢价，需持续跟踪技术路径。",
    ],
    sourceIds: ["S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "risk",
    items: [
      "出口许可节奏导致订单与价格短期剧烈波动。",
      "主金属减产时副产供给同步收缩，放大短缺。",
      "红外/显示等下游资本开支不及预期。",
      "全球占比等二手数据口径混乱，避免把传闻当事实。",
    ],
    sourceIds: ["S-RES-GOV-PORTAL", "S-RES-YUNNAN-GE-FILING", "S-RES-ZUYE-FILING"],
  },
];
