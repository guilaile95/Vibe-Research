import type { ContentBlock } from "../types.ts";

export const breakthroughBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "中国半导体产业在先进制程、先进封装（2.5D / 3D Chiplet）与关键设备三个方向持续投入。成熟制程代工方面，中芯国际等公开披露产能与资本开支安排；设备侧，中微、北方华创等披露高端工艺应用与出货进展。政策层面明确支持集成电路高质量发展，但「全面自给」并非政策文本给出的已实现结论。",
    sourceIds: [
      "S-SEMI-SMIC-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-NAURA-FILING",
      "S-SEMI-GOV-POLICY",
      "S-SEMI-MIIT-POLICY",
      "S-SEMI-SMIC-SITE",
    ],
  },
  {
    type: "callout",
    tone: "info",
    text: "行业展望（行业预测 / 内部分析，无官方统一时间表）：成熟制程（如 28nm 附近）产能与工艺相对更完整；更先进节点的量产节奏在公开信息中分歧较大。极紫外（EUV）光刻机仍是物理与供应链层面的关键瓶颈之一。下列表述均为预测性讨论，非公司或监管机构的正式定稿。",
    sourceIds: [],
  },
  {
    type: "bullets",
    items: [
      "先进制程：公开可交叉验证的大规模量产信息有限，宜跟踪客户导入与财报资本开支，而非单一媒体节点宣称。（内部分析）",
      "关键设备：刻蚀、薄膜等在部分工艺步骤已有国产机台导入披露，但「全流程可替代」尚不成立。（公司口径 + 内部分析）",
      "先进封装：Chiplet / 2.5D 路线可能部分缓解先进制程压力，但标准、良率与生态仍在演化中。",
    ],
    sourceIds: [
      "S-SEMI-SMIC-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-NAURA-FILING",
    ],
  },
  {
    type: "callout",
    tone: "warning",
    text: "反证条件（分析推断）：若先进制程研发显著延期（例如关键节点验证连续多年未达预期），或 Chiplet 生态出现严重标准碎片化，整体竞争力提升节奏将被削弱。",
    sourceIds: ["S-SEMI-GOV-POLICY", "S-SEMI-SMIC-FILING"],
  },
  {
    type: "risk",
    items: [
      "EUV 突破风险：电子束等替代光刻路线与 EUV 在吞吐量、成熟度上存在数量级差距（行业共识性讨论，非单一公司承诺）。",
      "Chiplet 标准分化风险：不同阵营接口与封装标准分化可能影响互操作与规模化。",
      "出口管制与供应链中断风险可能打断关键设备与材料的验证节奏。",
    ],
    sourceIds: ["S-SEMI-GOV-POLICY", "S-SEMI-MIIT-POLICY", "S-SEMI-SMIC-FILING"],
  },
];
