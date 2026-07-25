import type { ContentBlock } from "../types.ts";

export const nextGenBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "HBM4 跨代演进展望（行业预测 / 内部分析）：部分行业讨论与产业路线图分析推测，下一代 HBM4 可能将接口位宽由 1024-bit 扩展至 2048-bit，基础逻辑层（Base Die）或有机会引入先进制程晶圆代工与无凸块混合键合（Hybrid Bonding）技术。标准尚未正式定稿，以下内容为基于现有公开信息的合理推测，不具确定性，且具体参数尚未经官方确认。",
    sourceIds: [],
  },
  {
    type: "paragraph",
    text: "在 HBM4 架构预期路线图中，产业界分析认为基础逻辑层（Base Die）有望从传统 DRAM 制程转向逻辑晶圆代工制造。该趋势若成立，将推动存储原厂与晶圆代工厂在 2.5D/3D Chiplet 领域的深度共封合作（内部分析）。",
    sourceIds: [],
  },
  {
    type: "compareTable",
    caption: "HBM3e 与 HBM4 关键技术演进展望表（行业预期 / 内部分析）",
    headers: ["技术指标", "HBM3e (现行标准)", "HBM4 (行业预测)", "对产业链影响（分析推断）"],
    rows: [
      ["Base Die 工序", "标准 DRAM 工艺制造", "逻辑晶圆代工（规划中）", "晶圆代工厂与存储原厂联合共封"],
      ["总线接口位宽", "1024-bit 规范", "2048-bit 提案", "中介层布线密度与载板要求提升"],
      ["堆叠键合技术", "微凸块 (Microbump) / MR-MUF", "无凸块混合键合（验证中）", "对高精度键合设备提出更高要求"],
    ],
    sourceIds: [],
  },
];
