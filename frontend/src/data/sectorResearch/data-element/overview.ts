import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层制度：中发〔2022〕19号《数据二十条》明确数据产权、流通、收益分配、安全治理四项基础制度，提出数据资源持有权、数据加工使用权、数据产品经营权三权分置。上海数据交易所2024年交易额超30亿元。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-SH-EXCHANGE"],
  },
  {
    type: "paragraph",
    text: "数据要素板块涵盖数据确权、数据交易平台、公共数据授权运营、数据安全与数据基础设施五大方向。数据作为新型生产要素，其确权、定价、流通与价值释放是数字经济的核心命题。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING"],
  },
  {
    type: "bullets",
    items: [
      "数据确权：明确数据资源持有权、数据加工使用权、数据产品经营权三权分置，是数据流通的前提。",
      "数据交易：各地数据交易所（上海/北京/深圳/贵阳）推动数据产品登记、交易与合规流通。",
      "公共数据：公共数据授权运营试点推进，政务数据、医疗数据、交通数据等公共数据价值释放。",
      "数据安全：数据分类分级、隐私计算、联邦学习等技术保障数据流通安全。",
      "数据基础设施：数据湖、数据中心、数据金库等基础设施支撑数据要素化。",
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-SANGDA-FILING"],
  },
  {
    type: "table",
    caption: "数据要素五大核心方向与代表厂商",
    headers: ["方向", "核心能力", "关键壁垒", "代表A股厂商"],
    rows: [
      ["数据确权", "数据登记/确权/溯源", "牌照+公信力+技术", "人民网、易华录"],
      ["数据交易", "数据交易所/平台", "牌照+生态+合规", "上海数据交易所、贵阳大数据交易所"],
      ["公共数据", "政务/医疗/交通数据运营", "政府关系+数据资源", "易华录、云赛智联"],
      ["数据安全", "隐私计算/数据合规", "技术+资质+客户", "安恒信息、深信服"],
      ["数据基础设施", "数据湖/数据中心/云", "资金+技术+规模", "深桑达A、云赛智联、易华录"],
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-SANGDA-FILING", "S-DATA-SH-EXCHANGE"],
  },
];
