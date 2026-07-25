import type { ContentBlock } from "../types.ts";

export const pricingBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "warning",
    text: "反证与失效条件区：如果海外原厂 HBM3e 产能大幅扩张导致供需关系扭转、合约价快速回落，或者非 HBM 显存技术（如 LPDDR5X CAMM 模块或 CXL 内存池）在推理端取得低成本替代突破，将削弱高溢价逻辑。",
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-SHANNON-FILING"],
  },
  {
    type: "paragraph",
    text: "仍待验证事项区：1) 2025年 HBM4 规范定稿与混合键合（Hybrid Bonding）良率表现；2) 本土材料厂商 GMC 塑封料在 HBM 场景中的实际量产导入进展。",
    sourceIds: ["S-HBM-HUAHAI-FILING", "S-HBM-YAKU-FILING"],
  },
  {
    type: "risk",
    items: [
      "原厂产能分配与配额风险：HBM 分销业务高度依赖海力士等原厂的产能分配与配额政策。",
      "晶圆良率与抛光损耗风险：HBM 12层堆叠导致整体综合良率呈指数级下降，任何单层缺陷均导致整颗堆叠报废。",
      "技术概念混淆风险：部分概念股仅具备普通 DRAM 封测能力，并不具备 HBM 垂直 TSV 堆叠与先进封装资质。",
    ],
    sourceIds: ["S-HBM-JEDEC-STANDARD", "S-HBM-SHANNON-FILING", "S-HBM-TAIJI-FILING"],
  },
];
