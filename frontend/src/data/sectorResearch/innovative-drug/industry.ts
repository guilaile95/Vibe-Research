import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "中国创新药产业按「创新药企（Biopharma/Biotech）→ CXO服务→ 上游设备/耗材/试剂→ 商业化渠道（医院/药店/DTP）」形成完整产业链。当前格局呈现「Biotech估值重塑+Biopharma转型加速+CXO全球化」的多层次分化。",
    sourceIds: ["S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRUG-WUXI-ANNUAL-2023"],
  },
  {
    type: "bullets",
    items: [
      "头部Biopharma（恒瑞/百济）：拥有多个已上市创新药、成熟商业化团队，研发管线覆盖ADC/双抗/小分子/细胞治疗。",
      "Biotech（荣昌/传奇/信达）：依托单一平台技术（如ADC/CAR-T/双抗）实现差异化竞争，多数已产生产品收入或对外授权里程碑。",
      "CXO（药明/凯莱英/金斯瑞）：承接全球Biopharma与Biotech的研发与生产外包，营收与全球新药研发投入高度相关。",
      "上游（耗材/试剂/设备）：一次性生物反应器、层析介质、培养基、测序与基因合成等，国产替代空间大。",
    ],
    sourceIds: ["S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRUG-WUXI-ANNUAL-2023", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "table",
    caption: "创新药产业分层与代表公司",
    headers: ["分层", "定位", "核心能力", "代表公司", "事实/口径等级"],
    rows: [
      ["Biopharma（头部药企）", "成熟商业化+多适应症布局", "研发/商业化/合规体系", "恒瑞医药、百济神州", "公司口径（年报）"],
      ["Biotech（平台型Biotech）", "差异化平台技术+出海授权", "平台+临床推进", "荣昌生物、传奇生物", "公司口径（年报）"],
      ["CXO（一体化平台）", "研发与生产外包服务", "多客户管线+产能", "药明康德、凯莱英、金斯瑞", "公司口径（年报）"],
      ["上游（耗材/试剂/设备）", "国产化替代", "制造与成本控制", "纳微科技、楚天科技、东富龙", "公开信息"],
    ],
    sourceIds: ["S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRUG-WUXI-ANNUAL-2023", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "callout",
    tone: "info",
    text: "市场格局判断（分析推断）：创新药产业格局尚未收敛，头部Biopharma与Biotech分化明显。Biotech更依赖平台技术与授权收入，Biopharma更依赖已上市产品商业化能力。CXO行业受全球新药研发投入周期影响，短期承压但长期受益于产业链转移。",
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023", "S-DRUG-ASYMCHEM-2023-FILING"],
  },
];
