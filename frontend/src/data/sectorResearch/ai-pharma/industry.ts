import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "生物医药/AI制药板块呈现「AI制药+基因治疗+CXO+医疗器械+创新药」五大赛道。药明康德/泰格医药在CXO领域领先，华大基因在基因治疗具备优势，迈瑞医疗/联影医疗在医疗器械AI化领先。",
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING", "S-PHARMA-BGI-FILING", "S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "bullets",
    items: [
      "药明康德：化学/生物学/测试一体化平台，AI赋能药物发现，全球化产能布局（公司口径）。",
      "泰格医药：临床CRO龙头，数据管理与统计分析业务AI赋能效率提升（公司口径）。",
      "华大基因：基因测序龙头，AI赋能基因数据分析、精准医学与基因治疗（公司口径）。",
      "迈瑞医疗：生命信息/体外诊断/医学影像三大业务，AI辅助诊断+智慧医疗（公司口径）。",
      "联影医疗：高端医学影像设备国产替代龙头，AI影像产品获NMPA批准（公司口径）。",
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING", "S-PHARMA-BGI-FILING", "S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "table",
    caption: "生物医药/AI制药核心厂商竞争力矩阵",
    headers: ["厂商", "核心赛道", "护城河", "商业化进展", "事实/口径等级"],
    rows: [
      ["药明康德", "CXO+AI制药", "一体化平台+全球客户", "AI赋能药物发现", "公司口径（年报披露）"],
      ["泰格医药", "临床CRO", "临床网络+数据能力", "AI赋能临床试验", "公司口径（年报披露）"],
      ["华大基因", "基因治疗+测序", "测序平台+数据积累", "AI赋能基因分析", "公司口径（年报披露）"],
      ["迈瑞医疗", "医疗器械", "产品矩阵+渠道", "AI辅助诊断+智慧医疗", "公司口径（年报披露）"],
      ["联影医疗", "医学影像", "高端设备+AI影像", "AI产品NMPA获批", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING", "S-PHARMA-BGI-FILING", "S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "risk",
    items: [
      "地缘政治风险：美国《生物安全法案》可能限制联邦资金流向部分中国CXO企业。",
      "创新药研发风险：创新药临床试验失败率高，研发投入存在不确定性。",
      "集采降价风险：医疗器械与高值耗材集采降价压力持续。",
      "AI监管风险：AI医疗器械审评标准趋严，获批周期可能延长。",
    ],
    sourceIds: ["S-PHARMA-NMPA-PILOT", "S-PHARMA-FDA-ASCO", "S-PHARMA-WUXI-FILING"],
  },
];
