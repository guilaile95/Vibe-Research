import type { ContentBlock } from "../types.ts";

export const targetBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "靶点是创新药研发的起点与成败关键。当前国内热门靶点集中在肿瘤免疫（PD-1/PD-L1、CTLA-4）、细胞凋亡（BCL-2、MCL-1）、表观遗传（EZH2）、HER2/CLDN18.2/TROP2（ADC）、KRAS（G12C/G12D）以及自身免疫与代谢类（IL-17、IL-4R、GLP-1/GIPR）等。",
    sourceIds: ["S-DRUG-CDE-GUIDANCE", "S-DRUG-FDA-ORANGE-BOOK"],
  },
  {
    type: "paragraph",
    text: "近年来，国内创新药靶点布局呈现两个趋势：一是「去同质化」，从PD-1拥挤靶点向ADC、双抗、放射性药物（RDC）和基因治疗等新技术路径迁移；二是「全球同步」，部分本土企业进入全球首创（FIC）赛道，通过ASCO等国际会议披露早期海外临床数据。",
    sourceIds: ["S-DRUG-ASCO-LIBRARY", "S-DRUG-BEIGENE-2023-FILING"],
  },
  {
    type: "table",
    caption: "主要创新药靶点及对应已上市/临床后期药物",
    headers: ["靶点/通路", "已上市代表药物", "国内代表公司", "最新适应症拓展", "事实/口径等级"],
    rows: [
      ["PD-1/PD-L1", "帕博利珠单抗（K药）/纳武利尤单抗（O药）", "恒瑞医药（卡瑞利珠）、百济神州（替雷利珠）", "一线肺癌/肝癌/食管癌联合治疗", "已确认事实/公司口径"],
      ["HER2（ADC）", "曲妥珠单抗-deruxtecan（T-DXd）", "荣昌生物（RC48）、恒瑞医药（SHR-A1811）", "乳腺癌/尿路上皮癌/胃癌", "公司口径/已确认事实"],
      ["CLDN18.2", "佐妥昔单抗（Zolbetuximab，2024 FDA批准）", "恒瑞医药、信达生物", "胃/胃食管结合部腺癌", "已确认事实"],
      ["KRAS G12C", "Sotorasib/Adagrasib（FDA批准）", "益方生物、加科思", "NSCLC", "已确认事实"],
      ["GLP-1/GIPR", "司美格鲁肽/替尔泊肽", "信诺医药/恒瑞医药口服小分子", "T2DM/减重/MAFLD", "已确认事实/公司口径"],
    ],
    sourceIds: ["S-DRUG-FDA-ORANGE-BOOK", "S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-ASCO-LIBRARY"],
  },
  {
    type: "bullets",
    items: [
      "ADC（抗体偶联药物）：当前创新药出海主流技术路径，核心是抗体+linker+payload（拓扑异构酶抑制剂、MMAE等）。国内已有荣昌RC48获FDA突破性疗法认定。",
      "双特异性抗体（BsAb）：PD-1/VEGF、HER2双抗等多种分子设计，国内多家公司布局早期临床。",
      "放射性药物（RDC）：新兴赛道，利用靶向载体搭载同位素实现诊疗一体化（诊疗同位素偶联），处于临床前到早期临床阶段。",
    ],
    sourceIds: ["S-DRONG-RCHANG-2023-FILING", "S-DRUG-CDE-GUIDANCE"],
  },
];
