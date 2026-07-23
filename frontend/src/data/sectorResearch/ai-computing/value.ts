import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "单柜价值量爆发：相比传统 19 英寸风冷机柜，采用 NVL72 架构的高密度水冷机柜集成了高频铜背板、72 颗 GPU 及配电液冷，单柜价值量大幅提升。",
    sourceIds: ["S-AICOMP-FII-FILING"],
  },
  {
    type: "paragraph",
    text: "在AI服务器与单机柜价值量分布中，芯片（GPU/HBM）占据最主导份额，但网络（交换机与光模块）、PCB/高多层铜中板以及液冷散热在单柜BOM中的绝对金额均出现倍数增长。",
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING"],
  },
  {
    type: "table",
    caption: "典型高性能 AI 服务器 / 机柜 BOM 价值量划分",
    headers: ["模块", "BOM 价值占比", "驱动因素", "主要供应商/环节"],
    rows: [
      ["算力芯片 (GPU/DCU+HBM)", "70% ~ 75%", "晶圆先进制程、2.5D/3D堆叠与HBM3e显存", "海外芯片巨头、海光信息、寒武纪"],
      ["服务器整机集成与电源", "8% ~ 12%", "高功率服务器电源(钛金级)、主板贴片与系统测试", "浪潮信息、工业富联、中科曙光"],
      ["高速网络(交换机/光模块)", "8% ~ 10%", "800G/1.6T 光模块、无损交换机芯片", "紫光股份（新华三）、工业富联"],
      ["高端PCB与铜互连", "3% ~ 5%", "20层以上高多层HDI、M7/M9高频高速材料、铜缆总线", "已引用的PCB板块供应链"],
      ["液冷散热系统", "2% ~ 4%", "冷板、分水器(CDU)、快换接头与绝缘冷却液", "中科曙光、浪潮信息"],
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-SUGON-FILING", "S-AICOMP-UNIS-FILING"],
  },
];
