import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "可控核聚变产业处于「科学验证→工程验证→示范堆→商用堆」的早期阶段。当前全球核聚变研究以国家主导的大科学工程（ITER/EAST/CFETR）为主体，民营资本近年加速涌入（CFS/TAE/Helion等），形成「国家队+民营」双轨格局。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR", "S-FUSION-IAEA"],
  },
  {
    type: "bullets",
    items: [
      "国家队：ITER（国际）、EAST/CFETR（中国）、JET/MAST-Upgrade（英国）、KSTAR（韩国）、JT-60SA（日本）等。",
      "民营公司：CFS（SPARC/ARC，美国）、TAE Technologies（场反位形，美国）、Helion（场反+脉冲，美国）、Tokamak Energy（球托卡马克，英国）等。",
      "A股布局：联创光电（高温超导）、西部超导（低温/高温超导）、安泰科技（第一壁/偏滤器）、国光电气（等离子体设备）、中国核建（工程配套）。",
    ],
    sourceIds: ["S-FUSION-ITER", "S-FUSION-EAST", "S-FUSION-CFETR", "S-FUSION-IAEA", "S-FUSION-LIANCHUANG-2023", "S-FUSION-WESTSUPERCON-2023", "S-FUSION-ANTAI-2023", "S-FUSION-GUOGUANG-2023", "S-FUSION-CNNC-2023"],
  },
  {
    type: "table",
    caption: "A股核聚变产业链公司布局",
    headers: ["公司", "细分方向", "核心产品/技术", "参与项目", "事实/口径等级"],
    rows: [
      ["联创光电（600363）", "高温超导", "超导感应加热器/磁储能/聚变磁体", "CFETR", "公司口径（2023年报）"],
      ["西部超导（688122）", "低温/高温超导", "NbTi/Nb3Sn/REBCO带材", "ITER/CFETR", "公司口径（2023年报）"],
      ["安泰科技（000969）", "第一壁/偏滤器材料", "钨/钼等难熔金属", "ITER/CFETR", "公司口径（2023年报）"],
      ["国光电气（688776）", "等离子体设备", "微波源/离子注入机", "EAST/CFETR", "公司口径（2023年报）"],
      ["中国核建（601611）", "工程配套", "核设施建造", "EAST/CFETR", "公司口径（2023年报）"],
    ],
    sourceIds: ["S-FUSION-LIANCHUANG-2023", "S-FUSION-WESTSUPERCON-2023", "S-FUSION-ANTAI-2023", "S-FUSION-GUOGUANG-2023", "S-FUSION-CNNC-2023"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "投资判断框架（分析推断）：核聚变产业当前处于「科学验证向工程验证过渡」的早期阶段，短期投资价值主要在超导材料、第一壁材料与等离子体设备等上游供应商；中长期价值取决于CFETR/SPARC等装置是否实现Q>1与Q>10里程碑。",
    sourceIds: ["S-FUSION-ITER", "S-FUSION-CFETR", "S-FUSION-WESTSUPERCON-2023", "S-FUSION-ANTAI-2023"],
  },
];
