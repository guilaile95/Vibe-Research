import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层框架：NMPA发布《人工智能医疗器械注册审查指导原则》，明确AI辅助诊断/治疗器械审评要求。FDA加速审批通道（突破性疗法/优先审评）推动创新药快速上市。",
    sourceIds: ["S-PHARMA-NMPA-PILOT", "S-PHARMA-FDA-ASCO"],
  },
  {
    type: "paragraph",
    text: "生物医药/AI制药板块涵盖AI制药、基因治疗、CXO（医药外包）、医疗器械与生物技术五大方向。AI赋能药物发现、基因治疗创新突破、医疗器械AI化与CXO一体化是该板块四大核心趋势。",
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-BGI-FILING", "S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "bullets",
    items: [
      "AI制药：利用AI进行靶点发现、分子设计、临床试验优化，显著缩短药物研发周期、降低成本。",
      "基因治疗：AAV载体、CRISPR基因编辑与CAR-T细胞治疗等技术取得重大突破，多款产品获批上市。",
      "CXO（医药外包）：药明康德/泰格医药等提供从药物发现到临床试验的一站式外包服务，受益于研发外包趋势。",
      "医疗器械：迈瑞医疗/联影医疗等国产高端医疗器械厂商实现AI辅助诊断与智慧医疗布局。",
      "创新药：国产创新药通过FDA/EMA审批实现出海，Biotech向Big Pharma进化。",
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING", "S-PHARMA-BGI-FILING", "S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
  {
    type: "table",
    caption: "生物医药/AI制药五大核心赛道与代表厂商",
    headers: ["赛道", "核心能力", "关键壁垒", "代表A股厂商"],
    rows: [
      ["AI制药", "AI靶点发现/分子设计/临床试验优化", "数据+算法+验证能力", "药明康德、晶泰科技"],
      ["基因治疗", "基因编辑/细胞治疗/AAV载体", "技术+临床+CMC", "华大基因、博雅辑因"],
      ["CXO", "药物发现/临床前/临床试验外包", "平台+客户+合规", "药明康德、泰格医药"],
      ["医疗器械", "高端影像/体外诊断/AI辅助", "技术+注册+渠道", "迈瑞医疗、联影医疗"],
      ["创新药", "新药研发/临床/商业化", "管线+临床数据", "恒瑞医药、百济神州"],
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING", "S-PHARMA-BGI-FILING", "S-PHARMA-MINDRAY-FILING", "S-PHARMA-UNITED-FILING"],
  },
];
