import type { ContentBlock } from "../types.ts";

export const clinicalBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "warning",
    text: "创新药临床试验是验证靶点与药物价值的核心环节。典型时间线：IND到NDA约需6-10年；成功率（从I期到获批）约7-10%。国内创新药临床推进速度近年显著提升，部分适应症通过单臂试验或真实世界数据加速获批。",
    sourceIds: ["S-DRUG-CDE-GUIDANCE", "S-DRUG-CLINICALTRIALS"],
  },
  {
    type: "paragraph",
    text: "国内创新药临床推进呈现「中美双报」趋势：本土企业同步向NMPA与FDA递交IND，利用国内患者入组优势加速临床进度，同时通过ASCO/ESMO/EHA等国际学术会议披露海外临床数据，为后续出海授权（out-license）与海外注册奠定基础。",
    sourceIds: ["S-DRUG-ASCO-LIBRARY", "S-DRUG-BEIGENE-2023-FILING"],
  },
  {
    type: "table",
    caption: "代表公司核心管线临床进展（2023-2024年披露）",
    headers: ["公司", "核心药物", "适应症", "临床阶段/注册状态", "事实/口径等级"],
    rows: [
      ["恒瑞医药", "卡瑞利珠单抗（PD-1）", "肝癌/食管癌/肺癌联合", "国内已上市，海外临床推进", "公司口径"],
      ["恒瑞医药", "SHR-A1811（HER2 ADC）", "乳腺癌/肺癌", "国内III期/海外I期", "公司口径"],
      ["百济神州", "泽布替尼（BTK）", "CLL/SLL、WM、MCL", "全球已上市（FDA/NMPA）", "已确认事实"],
      ["百济神州", "替雷利珠单抗（PD-1）", "食管癌/肺癌/肝癌", "全球多中心III期", "已确认事实"],
      ["荣昌生物", "RC48（HER2 ADC）", "尿路上皮癌/胃癌", "国内已上市，海外II/III期", "公司口径"],
      ["荣昌生物", "RC18（泰它西普，BAFF/APRIL）", "SLE/RA/ IgA肾病", "国内已上市，海外III期", "公司口径"],
    ],
    sourceIds: ["S-DRUG-HENGRUI-ANNUAL-2023", "S-DRUG-BEIGENE-2023-FILING", "S-DRONG-RCHANG-2023-FILING", "S-DRUG-FDA-ORANGE-BOOK"],
  },
  {
    type: "bullets",
    items: [
      "CDE「突破性治疗」与「优先审评」通道：针对严重疾病且临床优势明显的药物，可缩短审评时间，国内多家创新药企已获认定。",
      "FDA孤儿药认定：针对罕见病适应症的药物可享受税收抵免、市场独占期等激励，国内出海企业积极申请。",
      "ASCO口头报告：中国创新药在ASCO的口头报告数量逐年增加，反映国内临床数据质量与全球认可度提升。",
    ],
    sourceIds: ["S-DRUG-CDE-GUIDANCE", "S-DRUG-FDA-ORANGE-BOOK", "S-DRUG-ASCO-LIBRARY"],
  },
];
