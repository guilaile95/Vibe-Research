import type { ContentBlock } from "../types.ts";

export const breakthroughBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "中国半导体产业在先进制程、先进封装（2.5D/3D Chiplet）和关键设备三个方向加速追赶。成熟制程已实现基本自给。",
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-AMEC-FILING", "S-SEMI-MIIT-POLICY"],
  },
  {
    type: "callout",
    tone: "info",
    text: "行业展望（行业预测 / 内部分析）：28nm 制程成熟，14nm 进入有限量产，7nm 以下仍处于研发攻关阶段。EUV 光刻机仍是最大的物理瓶颈。",
    sourceIds: [],
  },
  {
    type: "callout",
    tone: "warning",
    text: "反证条件（分析推断）：如果先进制程研发超预期延长（3 年以上）或 Chiplet 生态发生碎片化，整体竞争力将被削弱。",
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
  {
    type: "risk",
    items: [
      "EUV 突破风险：电子束等替代路线与 EUV 吞吐量存在数量级差距。",
      "Chiplet 标准分化风险：中美阵营标准分化可能影响兼容性。",
    ],
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
];
