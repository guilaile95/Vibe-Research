import type { ContentBlock } from "../types.ts";

export const magneticBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "磁约束（Magnetic Confinement）是当前核聚变研究的主流路线，利用强磁场将高温等离子体约束在真空室中，避免与容器壁接触。托卡马克（Tokamak）是最成熟的磁约束构型，其磁场由环向场（TF）、极向场（PF）与中心螺线管（CS）线圈共同产生。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR"],
  },
  {
    type: "paragraph",
    text: "托卡马克的核心物理是「环形磁场+极向磁场」组合形成的螺旋磁力线，使带电粒子沿磁力线做螺旋运动，实现径向约束。等离子体电流（由感应或非感应驱动）产生极向场，与环向场叠加形成嵌套磁面。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST"],
  },
  {
    type: "table",
    caption: "托卡马克磁约束系统关键子系统",
    headers: ["子系统", "功能", "关键参数", "技术挑战", "事实/口径等级"],
    rows: [
      ["环向场线圈（TF）", "产生主环向磁场约束等离子体", "磁场强度5-12T（ITER 5.3T）", "超导材料、机械支撑、接头电阻", "已确认事实"],
      ["极向场线圈（PF）", "控制等离子体形状与位置", "快速响应、高精度", "电源系统、控制算法", "已确认事实"],
      ["中心螺线管（CS）", "感应驱动等离子体电流", "磁通变化>100Wb", "非感应驱动替代（ECRH/NBI）", "已确认事实"],
      ["等离子体加热", "将等离子体加热至>1亿℃", "ECRH/NBI/ICRH", "加热效率与沉积控制", "已确认事实"],
      ["等离子体控制", "实时反馈控制等离子体位形", "毫秒级响应", "MHD不稳定性、破裂预测", "已确认事实"],
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR"],
  },
  {
    type: "bullets",
    items: [
      "H模（高约束模）：1982年ASDEX装置发现，通过边界输运垒（ETB）实现约束性能翻倍，是当前主流运行模式。",
      "ITER设计参数：等离子体大半径6.2m、小半径2.0m、等离子体电流15MA、聚变功率500MW、Q>10。",
      "CFETR目标：连接ITER与商用堆，聚变功率GW级，氚增殖包层与氚自持验证。",
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR"],
  },
];
