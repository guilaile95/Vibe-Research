import type { ContentBlock } from "../types.ts";

export const industryAiBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "垂直行业AI是应用落地价值最高的领域：科大讯飞在政务/教育/医疗/汽车四大行业、同花顺在金融投顾、拓尔思在政务/金融/媒体均形成行业Know-How壁垒（公司口径）。",
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING"],
  },
  {
    type: "paragraph",
    text: "垂直AI应用以行业数据、业务理解与领域知识为核心壁垒，通用大模型需通过RAG、微调、知识图谱等技术适配垂直场景。金融、医疗、政务、教育、法律等场景AI应用价值量最大。",
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-TRS-FILING"],
  },
  {
    type: "table",
    caption: "垂直行业AI应用场景与代表厂商",
    headers: ["行业", "核心AI应用", "价值驱动", "代表A股厂商"],
    rows: [
      ["金融", "智能投顾/风控/客服/研报", "降本增效+精准营销", "同花顺、恒生电子、拓尔思"],
      ["医疗", "辅助诊断/病历质控/药物发现", "诊断效率+医疗资源下沉", "科大讯飞、卫宁健康"],
      ["政务", "一网通办/公文写作/舆情分析", "政务服务效能+治理现代化", "科大讯飞、拓尔思、太极股份"],
      ["教育", "个性化学习/智能批改/作文评测", "因材施教+教育公平", "科大讯飞、好未来"],
      ["法律/媒体", "合同审核/新闻写作/内容审核", "效率提升+合规风控", "拓尔思、人民网"],
    ],
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING"],
  },
  {
    type: "bullets",
    items: [
      "科大讯飞：星火大模型在政务/教育/医疗/汽车四大行业落地，AI开放平台开发者生态规模领先（公司口径）。",
      "同花顺：问财AI大模型赋能iFind金融终端，AI投顾与智能客服提升用户粘性（公司口径）。",
      "拓尔思：天渊大模型在政务/金融/媒体行业垂直落地，数据要素业务协同（公司口径）。",
    ],
    sourceIds: ["S-AIAPP-IFLYTEK-FILING", "S-AIAPP-THS-FILING", "S-AIAPP-TRS-FILING"],
  },
];
