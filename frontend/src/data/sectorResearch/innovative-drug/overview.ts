import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "中国创新药产业正经历从「仿制跟随」向「全球同步/首创」的结构性转型。NMPA加入ICH后，国内创新药审评标准与国际接轨；CDE持续发布ADC、双抗、细胞与基因治疗等前沿技术指导原则，推动本土企业向FIC/BIC靶点布局。",
    sourceIds: ["S-DRUG-NMPA-MAIN", "S-DRUG-CDE-GUIDANCE"],
  },
  {
    type: "paragraph",
    text: "创新药产业链按「靶点发现→临床前→IND→临床I/II/III期→NDA/BLA→商业化」长周期展开，核心环节包括：大分子/小分子药物发现、CRO/CDMO服务、临床试验与注册申报、商业化生产与出海授权（out-license）。",
    sourceIds: ["S-DRUG-WUXI-ANNUAL-2023", "S-DRUG-ASYMCHEM-2023-FILING"],
  },
  {
    type: "bullets",
    items: [
      "代表公司：恒瑞医药（600276）——国内肿瘤创新药龙头，PD-1/AR抑制剂/ADC管线丰富。",
      "百济神州（688235）——泽布替尼全球销售额突破十亿美元，替雷利珠单抗海外注册推进。",
      "药明康德（603259）——CRDMO一体化平台，覆盖化学/生物学/细胞基因治疗。",
      "荣昌生物（688331）——ADC平台（RC48）获Seagen 26亿美元授权，出海标杆。",
      "凯莱英（002821）——小分子CDMO龙头，布局化学大分子与连续反应技术。",
      "金斯瑞（01548）——生物药CDMO（蓬勃生物）+ 细胞疗法（传奇生物CAR-T）。",
    ],
    sourceIds: ["S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRUG-WUXI-ANNUAL-2023", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
  {
    type: "table",
    caption: "创新药产业链核心环节与代表A股/港股公司",
    headers: ["环节", "核心能力", "代表公司", "事实/口径等级"],
    rows: [
      ["创新药研发（Pharma）", "靶点发现、临床推进、商业化", "恒瑞医药、百济神州、荣昌生物", "公司口径（年报披露）"],
      ["CRO/CDMO（CXO）", "药物发现、临床前、工艺开发、生产", "药明康德、凯莱英、金斯瑞", "公司口径（年报披露）"],
      ["ADC/双抗平台", "偶联技术、linker-payload、双抗工程", "荣昌生物、恒瑞医药、百济神州", "公司口径（年报披露）"],
      ["细胞与基因治疗", "CAR-T/CAR-NK/基因编辑", "金斯瑞（传奇生物）", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRUG-WUXI-ANNUAL-2023", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-ASYMCHEM-2023-FILING", "S-DRUG-GENSCRIPT-ANNUAL-2023"],
  },
];
