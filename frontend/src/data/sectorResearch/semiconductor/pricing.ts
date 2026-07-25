import type { ContentBlock } from "../types.ts";

export const pricingBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "半导体环节的定价权更多来自「技术不可替代性 + 验证壁垒 + 政策与安全偏好」，而非单纯产能规模。典型路径可概括为：技术突破 → 客户验证（qualification）→ 份额提升 → 规模效应。政策为国产设备与材料提供需求侧与融资侧支持，但并不直接决定单台设备售价。",
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-GOV-POLICY",
      "S-SEMI-MIIT-POLICY",
    ],
  },
  {
    type: "bullets",
    items: [
      "设备：一旦通过关键节点验证，切换成本高，议价能力相对材料更强，但订单仍受晶圆厂资本开支周期约束。（公司口径 + 内部分析）",
      "材料：耗材属性带来持续采购，但价格更易受配方竞争与客户双源策略压制。（公司口径 + 内部分析）",
      "代工：成熟制程价格更接近周期品；先进节点若供给受限，定价弹性更高，但公开可验证样本有限。",
    ],
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-SMIC-FILING",
    ],
  },
  {
    type: "callout",
    tone: "warning",
    text: "反证条件（分析推断）：若全球半导体下行导致晶圆厂资本开支显著收缩，国产设备即使具备替代逻辑，也可能阶段性失去「替代溢价」的兑现窗口；成熟制程扩产过快时，代工价格竞争可能加剧。",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING", "S-SEMI-SMIC-FILING"],
  },
  {
    type: "risk",
    items: [
      "成熟制程产能过剩与价格战风险。",
      "技术迭代风险：下一代工艺窗口变化可能削弱已验证机台的长期优势。",
      "关税、出口管制与贸易摩擦改变成本曲线与交付能力。",
    ],
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-SMIC-FILING", "S-SEMI-GOV-POLICY"],
  },
];
