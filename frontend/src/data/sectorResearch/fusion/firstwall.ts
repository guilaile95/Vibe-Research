import type { ContentBlock } from "../types.ts";

export const firstwallBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "warning",
    text: "第一壁（First Wall）与偏滤器（Divertor）是直接面向等离子体的核心部件，承受极端热流（稳态10 MW/m²、瞬态20 MW/m²以上）、高通量14.1 MeV中子辐照与等离子体冲刷，是核聚变工程化的关键瓶颈之一。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-CFETR", "S-FUSION-ANTAI-2023"],
  },
  {
    type: "paragraph",
    text: "第一壁与偏滤器材料需同时满足高熔点、高热导率、低溅射率、抗中子辐照肿胀与氚滞留低等严苛要求。当前主流方案采用钨（W）作为等离子体面向材料（PFM），搭配铜铬锆（CuCrZr）热沉与不锈钢结构。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-ANTAI-2023"],
  },
  {
    type: "table",
    caption: "第一壁/偏滤器关键材料与工程挑战",
    headers: ["材料", "功能", "关键性能指标", "工程挑战", "事实/口径等级"],
    rows: [
      ["钨（W）", "等离子体面向材料（PFM）", "高熔点（3422℃）、低溅射率", "脆性、中子活化、再结晶脆化", "已确认事实"],
      ["CuCrZr合金", "热沉材料（Heat Sink）", "高热导率（>320 W/mK）、高强度", "中子辐照软化、热疲劳", "已确认事实"],
      ["ODS钢（氧化物弥散强化）", "结构材料", "抗辐照、耐高温", "加工性差、焊接技术", "已确认事实"],
      ["SiC/SiC陶瓷基复合材料", "潜在先进包层材料", "低氚滞留、耐高温", "密封性、辐照稳定性", "已确认事实"],
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-CFETR"],
  },
  {
    type: "bullets",
    items: [
      "安泰科技：国内钨/钼等难熔金属偏滤器与第一壁材料核心供应商，参与ITER与CFETR配套。",
      "ITER偏滤器：使用约1000块钨偏滤器靶板，需承受20 MW/m²瞬态热流（ELM/破裂）。",
      "氚增殖包层（TBM）：CFETR与ITER均设计氚增殖包层测试模块，验证氚自持（TBR>1）。",
    ],
    sourceIds: ["S-FUSION-ANTAI-2023", "S-FUSION-ITER", "S-FUSION-CFETR"],
  },
  {
    type: "risk",
    items: [
      "材料寿命：14.1 MeV中子辐照导致材料肿胀、脆化，第一壁/偏滤器需定期更换，影响电站可用率。",
      "氚自持：氚增殖包层需实现TBR>1，目前尚无工程验证。",
      "极端工况：等离子体破裂（Disruption）产生热流与电磁载荷，对第一壁结构完整性构成威胁。",
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-CFETR"],
  },
];
