import type { ContentBlock } from "../types.ts";

export const pricingBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "人形机器人的量产降本依赖于通用零部件标准化与规模化生产。在降本路径中，行星滚柱丝杠国产化与谐波减速器规模化将直接决定关节执行器的最终定价权分布。",
    sourceIds: ["S-HUMANOID-SANHUA-FILING", "S-HUMANOID-TOPPU-FILING"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "反证与失效条件区：如果海外头部客户自研执行器总成并完全转向垂直一体化生产，或者灵巧手技术路线发生重大变更（如气动/腱驱动全面替代微型电机驱动），将直接削弱第三方执行器与空心杯电机供应商的订单预期。",
    sourceIds: ["S-HUMANOID-MIIT-ACTION-PLAN", "S-HUMANOID-SANHUA-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "仍待验证事项区：1) 2025-2026年海外头部厂商C-Sample/量产定点通知书的正式落子；2) 行星滚柱丝杠国产化替代后的良率与成本降幅；3) 工业制造场景（如汽车工厂搬运/巡检）中的实际 ROI 商业化闭环。",
    sourceIds: ["S-HUMANOID-TOPPU-FILING"],
  },
  {
    type: "risk",
    items: [
      "量产进度不及预期风险：人形机器人从样机到10万台级大批量生产仍需解决寿命、一致性与成本问题。",
      "客户集中度过高风险：供应链深度绑定单一海外领头客户，若客户产品迭代延迟或供应商重新竞标将带来经营波动。",
      "技术路线更迭风险：如电驱动路线被液压或直接驱动电机（DD）局部替代，可能影响减速器与丝杠的需求量。",
    ],
    sourceIds: ["S-HUMANOID-MIIT-ACTION-PLAN", "S-HUMANOID-SANHUA-FILING", "S-HUMANOID-GREENHARMONIC-FILING"],
  },
];
