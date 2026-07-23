import type { ContentBlock } from "../types.ts";

export const nextGenBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "HBM4 跨代变革：底座 Base Die 从传统 DRAM 工艺切换为台积电等晶圆厂先进制程逻辑晶圆，开启代工与存储深度共封模式。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "paragraph",
    text: "下一代 HBM4 将迎来重大架构革新：接口位宽从 1024-bit 翻倍至 2048-bit，且基础逻辑层（Base Die）将转向由台积电等晶圆代工厂采用 3nm/4nm 先进制程定制制造，标志着存储与代工生态的深度融合。",
    sourceIds: ["S-HBM-JEDEC-STANDARD"],
  },
  {
    type: "compareTable",
    caption: "HBM3e 与 HBM4 关键技术变革对比",
    headers: ["技术指标", "HBM3e", "HBM4", "对产业链的影响"],
    rows: [
      ["Base Die 工序", "标准 DRAM 工艺制造", "逻辑晶圆代工 (3nm/4nm/5nm)", "代工厂 (Foundry) 直接介入 HBM 基础层制造"],
      ["总线接口位宽", "1024-bit", "2048-bit", "Interposer 中介层布线密度翻倍，PCB/载板层数要求提升"],
      ["堆叠键合技术", "微凸块 (Microbump)", "无凸块混合键合 (Direct Hybrid Bonding)", "抛弃凸块、间距降至<1μm，对清洗与键合设备提出极高要求"],
    ],
    sourceIds: ["S-HBM-JCET-FILING"],
  },
];
