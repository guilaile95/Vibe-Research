import type { ContentBlock } from "../types.ts";

export const aiDrugBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "AI制药进入价值兑现期：药明康德DEL/AI筛选平台赋能全球Biotech，AI显著缩短药物发现周期、降低成本（公司口径）。",
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-FDA-ASCO"],
  },
  {
    type: "paragraph",
    text: "AI制药利用深度学习、生成式AI、强化学习等技术，在靶点发现、分子设计、虚拟筛选、ADMET预测、临床试验优化等环节赋能药物研发。传统药物研发周期10-15年、成本26亿美元，AI有望显著缩短周期与降低成本。",
    sourceIds: ["S-PHARMA-WUXI-FILING"],
  },
  {
    type: "table",
    caption: "AI制药核心能力矩阵",
    headers: ["AI赋能环节", "技术手段", "典型效果", "代表企业"],
    rows: [
      ["靶点发现", "知识图谱/NLP/多组学分析", "缩短50%发现周期", "药明康德、Insilico Medicine"],
      ["分子设计", "生成式AI/强化学习/扩散模型", "新分子生成效率提升10x", "晶泰科技、药明康德"],
      ["虚拟筛选", "分子对接/深度打分函数", "筛选成本降低90%", "药明康德、Schrödinger"],
      ["ADMET预测", "图神经网络/Transformer", "预测准确率提升20-30%", "药明康德、BenevolentAI"],
      ["临床试验优化", "患者招募/终点预测/适应性设计", "招募周期缩短30%", "泰格医药、Medidata"],
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-TIGER-FILING"],
  },
  {
    type: "bullets",
    items: [
      "药明康德：DEL/AI筛选平台赋能全球客户，AI分子设计与DEL高通量筛选协同（公司口径）。",
      "晶泰科技：AI药物晶体预测+自动化实验平台，AI驱动药物固相研发。",
      "里程碑：全球已有20+款AI设计药物进入临床试验阶段（机构预测）。",
      "数据壁垒：高质量生物活性数据是AI制药模型训练的核心壁垒。",
    ],
    sourceIds: ["S-PHARMA-WUXI-FILING", "S-PHARMA-FDA-ASCO"],
  },
];
