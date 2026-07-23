import type { ContentBlock } from "../types.ts";

export const pricingBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "warning",
    text: "反证与失效条件区：如果全球云巨头Capex（资本开支）增速出现实质性放缓，或者推理端模型剪枝/量化突破导致对集群算力总需求下降，将引发算力服务器与交换机订单的下修周期。",
    sourceIds: ["S-AICOMP-MIIT-WHITE-PAPER", "S-AICOMP-INSPUR-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "仍待验证事项区：1) 本土算力芯片在大模型万卡并行训练中的实际 MFU（模型算力利用率）指标；2) 先进制程晶圆代工与 CoWoS 封测产能对国产芯片出货的约束上限。",
    sourceIds: ["S-AICOMP-HYGON-FILING", "S-AICOMP-CAMBRICON-FILING"],
  },
  {
    type: "risk",
    items: [
      "供应链制裁与禁售风险：先进算力芯片及制造设备的出口限制可能影响整机交付与智算中心建设进度。",
      "毛利率压缩风险：AI服务器代工与整机组装环节若竞争加剧，芯片成本传导能力受限制将影响盈利能力。",
      "液冷运维与漏液风险：冷板/浸没式液冷在长期运行中的可靠性与维护成本仍待进一步大规模验证。",
    ],
    sourceIds: ["S-AICOMP-MIIT-WHITE-PAPER", "S-AICOMP-INSPUR-FILING", "S-AICOMP-SUGON-FILING"],
  },
];
