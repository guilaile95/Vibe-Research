import type { ContentBlock } from "../types.ts";

export const cxoBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "CXO是生物医药研发外包的核心载体：药明康德提供化学/生物学/测试一体化平台，泰格医药在临床CRO领域领先，AI赋能显著提升研发效率（公司口径）。",
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING"],
  },
  {
    type: "paragraph",
    text: "CXO（医药外包）涵盖药物发现CRO、临床前CRO、临床CRO与CDMO四大环节。药明康德实现从药物发现到商业化生产的一站式服务，泰格医药在临床CRO领域具备规模优势。",
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING"],
  },
  {
    type: "table",
    caption: "CXO四大环节与代表企业",
    headers: ["环节", "核心服务", "关键能力", "代表A股厂商"],
    rows: [
      ["药物发现CRO", "靶点验证/苗头化合物/先导化合物", "化合物库/筛选平台/AI能力", "药明康德、康龙化成"],
      ["临床前CRO", "药效/药代/安全性评价", "动物模型/GLP资质/技术平台", "药明康德、昭衍新药"],
      ["临床CRO", "临床试验设计/执行/数据管理", "临床中心网络/数据能力", "泰格医药、药明康德"],
      ["CDMO/CMO", "工艺开发/中试/商业化生产", "产能/工艺/合规", "药明康德、凯莱英"],
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING"],
  },
  {
    type: "bullets",
    items: [
      "药明康德：化学/生物学/测试一体化平台，AI赋能药物发现，全球化产能布局（公司口径）。",
      "泰格医药：临床CRO龙头，数据管理与统计分析业务AI赋能效率提升（公司口径）。",
      "行业趋势：全球Biotech研发外包比例持续提升，中国CXO受益于工程师红利与成本优势。",
      "地缘风险：美国《生物安全法案》可能限制联邦资金流向部分中国CXO企业。",
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING", "S-PHARMA-FDA-ASCO"],
  },
  {
    type: "risk",
    items: [
      "地缘政治风险：海外政策限制可能影响中国CXO企业承接海外订单。",
      "产能过剩风险：CDMO产能集中释放可能导致价格竞争。",
      "创新药投融资风险：Biotech融资收缩影响CRO/CDMO订单节奏。",
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING"],
  },
];
