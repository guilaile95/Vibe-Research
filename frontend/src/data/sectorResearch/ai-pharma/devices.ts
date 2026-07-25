import type { ContentBlock } from "../types.ts";

export const devicesBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "国产高端医疗器械AI化加速：迈瑞医疗在生命信息/体外诊断/医学影像三大业务布局AI辅助诊断，联影医疗AI影像产品获NMPA批准（公司口径）。",
    sourceIds: ["S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING", "S-PHARMA-NMPA-PILOT"],
  },
  {
    type: "paragraph",
    text: "医疗器械板块涵盖医学影像、体外诊断、生命信息监护、微创介入与高值耗材五大细分。迈瑞医疗与联影医疗在高端医学影像与AI辅助诊断领域实现国产替代与AI化升级。",
    sourceIds: ["S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "compareTable",
    caption: "医疗器械细分赛道与代表厂商",
    headers: ["细分赛道", "核心产品", "AI赋能方向", "代表A股厂商"],
    rows: [
      ["医学影像", "CT/MRI/超声/X光", "AI辅助诊断/图像重建", "联影医疗、迈瑞医疗"],
      ["体外诊断", "生化/免疫/分子/POCT", "AI结果解读/质控", "迈瑞医疗、安图生物"],
      ["生命信息监护", "监护仪/麻醉机/呼吸机", "AI预警/多参数分析", "迈瑞医疗"],
      ["微创介入", "内窥镜/手术机器人", "AI导航/术中识别", "迈瑞医疗、微创机器人"],
      ["高值耗材", "骨科/心血管/神经介入", "AI术前规划", "微创医疗、乐普医疗"],
    ],
    sourceIds: ["S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "bullets",
    items: [
      "迈瑞医疗：生命信息/体外诊断/医学影像三大业务，AI辅助诊断+智慧医疗布局（公司口径）。",
      "联影医疗：高端医学影像设备国产替代龙头，AI影像产品获NMPA批准（公司口径）。",
      "AI医疗器械：NMPA已批准100+款AI医疗器械，肺结节/眼底/冠脉是获批热点。",
      "国产替代：高端CT/MRI/超声等设备国产替代率持续提升，海外出口增长显著。",
    ],
    sourceIds: ["S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING", "S-PHARMA-NMPA-PILOT"],
  },
];
