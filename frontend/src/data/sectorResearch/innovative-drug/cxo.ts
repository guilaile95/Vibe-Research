import type { ContentBlock } from "../types.ts";

export const cxoBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "CXO（Contract Research/Development/Manufacturing Organization）是创新药产业链的专业化分工载体。典型模式包括：CRO（研究外包）、CDMO（开发与生产外包）、CSO（销售外包）。国内CXO行业依托工程师红利与产能成本优势，深度嵌入全球创新药供应链。",
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "paragraph",
    text: "CXO商业模式的核心价值在于「多客户管线驱动+产能扩张前置」：头部CXO企业承接全球Pharma与Biotech的临床前/临床/商业化项目，通过化学/生物学/CMC等一体化平台实现「跟随分子走向上市」的漏斗式成长。",
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023"],
  },
  {
    type: "table",
    caption: "国内主要CXO公司与业务板块",
    headers: ["公司", "核心业务板块", "覆盖阶段", "代表性客户/项目", "事实/口径等级"],
    rows: [
      ["药明康德（603259）", "化学/生物学/DT/细胞与基因治疗/测试", "发现→临床前→临床→商业化", "全球TOP20 Biopharma", "公司口径（2023年报）"],
      ["凯莱英（002821）", "小分子CDMO/化学大分子/制剂/临床/连续反应技术", "临床→商业化", "全球Biopharma与Biotech", "公司口径（2023年报）"],
      ["金斯瑞（01548）", "蓬勃生物（生物药CDMO）+百斯杰（工业酶）+基因合成", "发现→商业化", "全球Biopharma", "公司口径（2023年报）"],
      ["康龙化成", "化学/生物学/DT/CDMO一体化", "发现→临床前→临床", "全球Biopharma", "公开信息"],
      ["药明生物", "生物药CDMO（大分子/ADC/疫苗）", "临床→商业化", "全球Biopharma与Biotech", "公开信息"],
    ],
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "bullets",
    items: [
      "一体化平台（CRDMO/CTDMO）：客户可在药物发现→开发→生产的全生命周期中与同一家CXO合作，形成漏斗式成长与客户粘性。",
      "产能扩张：国内头部CXO持续在欧洲（爱尔兰/德国/英国）与美国布局产能，应对地缘政治风险与全球客户需求。",
      "技术前沿：ADC/双抗/细胞基因治疗（CGT）等新分子类型带来增量CDMO需求，对厂房、质量体系与技术人员提出更高要求。",
    ],
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "risk",
    items: [
      "地缘政治风险：《生物安全法案》等政策可能影响国内CXO承接美国Biopharma项目。",
      "产能过剩风险：部分领域（如小分子化学药）CDMO产能扩张快于需求，竞争加剧可能压价。",
      "客户集中度：头部Biopharma客户管线调整或并购对CXO项目连续性有影响。",
    ],
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023"],
  },
];
