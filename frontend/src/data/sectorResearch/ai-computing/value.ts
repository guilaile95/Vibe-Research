import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "单柜价值量与高密度趋势（公司口径）：浪潮信息与工业富联年报披露，高密度 GPU 服务器与液冷机柜系统集成了多卡算力、高功率电源与配电液冷，系统复杂性与价值量显著高于传统通用服务器。",
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING"],
  },
  {
    type: "paragraph",
    text: "在 AI 服务器与算力机柜成本构成中，算力芯片（GPU/DCU 与 HBM 显存）占据最核心份额，高速网络交换机、光模块、高多层 PCB / 铜互连以及液冷散热系统构成重要的配套价值量。",
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING"],
  },
  {
    type: "table",
    caption: "高性能 AI 服务器与智算集群核心模块划分（分析推断）",
    headers: ["模块环节", "核心功能与驱动因素", "代表 A 股厂商", "事实/口径等级"],
    rows: [
      ["算力芯片 (GPU/DCU+HBM)", "先进制程逻辑芯片、2.5D/3D 堆叠与 HBM 显存", "海光信息、寒武纪", "公司口径（年报披露）"],
      ["服务器整机与电源", "高功率服务器电源、主板贴片集成与系统散热工程", "浪潮信息、工业富联、中科曙光", "公司口径（年报披露）"],
      ["高速网络(交换机/光模块)", "800G/1.6T 交换机、光模块与无损网络拓扑", "紫光股份（新华三）、工业富联", "公司口径（年报披露）"],
      ["液冷散热系统", "冷板、CDU 分水器与浸没式冷却液循环", "中科曙光、浪潮信息", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-AICOMP-INSPUR-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-SUGON-FILING", "S-AICOMP-UNIS-FILING"],
  },
];
