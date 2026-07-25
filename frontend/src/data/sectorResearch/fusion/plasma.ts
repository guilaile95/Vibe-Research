import type { ContentBlock } from "../types.ts";

export const plasmaBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "等离子体是核聚变反应的介质，其约束性能与稳定性直接决定能否实现持续燃烧。等离子体物理研究涵盖宏观平衡与稳定性、输运与约束、加热与驱动、边界物理与材料等核心领域。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST"],
  },
  {
    type: "paragraph",
    text: "EAST装置近年来在长脉冲H模运行上取得多项突破：2023年实现403秒长脉冲高约束模等离子体运行，2024年实现1066秒长脉冲运行，验证了等离子体长脉冲稳态约束的工程可行性，为ITER与CFETR稳态运行奠定基础。",
    sourceIds: ["S-FUSION-EAST"],
  },
  {
    type: "table",
    caption: "等离子体加热与驱动技术",
    headers: ["技术", "原理", "功率范围", "主要应用", "事实/口径等级"],
    rows: [
      ["中性束注入（NBI）", "高能中性粒子穿透磁场沉积加热", "MW~数十MW", "ITER、EAST、HL-2M", "已确认事实"],
      ["电子回旋共振加热（ECRH）", "微波在电子回旋频率共振加热", "MW级", "EAST、ITER", "已确认事实"],
      ["离子回旋共振加热（ICRH）", "射频波在离子回旋频率共振加热", "MW级", "ITER、JET", "已确认事实"],
      ["低混杂波驱动（LHCD）", "非感应驱动等离子体电流", "MW级", "EAST、ITER（辅助）", "已确认事实"],
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST"],
  },
  {
    type: "bullets",
    items: [
      "H模约束改善：边界输运垒（ETB）使约束性能翻倍，是ITER稳态运行的基础。",
      "破裂预测与缓解：大破裂（Major Disruption）产生热流与电磁载荷，EAST装置发展基于AI的破裂预测算法。",
      "国光电气：国内等离子体设备（微波源、离子注入机等）核心供应商，在受控核聚变与半导体领域双轮驱动。",
    ],
    sourceIds: ["S-FUSION-EAST", "S-FUSION-GUOGUANG-2023", "S-FUSION-ITER"],
  },
];
