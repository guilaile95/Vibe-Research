import type { ContentBlock } from "../types.ts";

export const publicDataBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "公共数据授权运营是数据要素化的重要突破口。政务数据、医疗数据、交通数据、气象数据等高价值公共数据，通过授权运营方式向社会开放，释放数据价值。易华录、云赛智联等在公共数据领域具备先发优势。",
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-YUNSAI-FILING"],
  },
  {
    type: "table",
    caption: "公共数据类型与授权运营模式",
    headers: ["公共数据类型", "数据价值", "运营模式", "代表企业"],
    rows: [
      ["政务数据", "高（治理/风控/征信）", "政府授权/特许经营", "易华录、太极股份"],
      ["医疗数据", "极高（医药研发/保险）", "脱敏授权/隐私计算", "卫宁健康、易华录"],
      ["交通数据", "高（导航/物流/自动驾驶）", "平台运营/服务采购", "易华录、四维图新"],
      ["气象/地理数据", "中（农业/能源/保险）", "授权使用/产品化", "航天宏图、中科星图"],
      ["金融数据", "极高（信贷/保险/投资）", "合规交易/数据服务", "上海钢联、同花顺"],
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-STEEL-FILING"],
  },
  {
    type: "bullets",
    items: [
      "易华录：数据湖+数据银行模式覆盖全国多个城市，政务数据湖基础设施与数据要素运营双轮驱动（公司口径）。",
      "云赛智联：智慧城市+数据中心基础设施，公共数据授权运营在上海等区域推进（公司口径）。",
      "授权运营机制：政府授予特许经营权，企业负责数据采集、治理、产品化与运营。",
      "医疗数据：临床数据脱敏后用于医药研发与保险定价，隐私计算技术保障数据安全。",
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-20-ARTICLES"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "待验证事项：1) 公共数据授权运营全国统一规则出台进度；2) 数据资产入表政策实施细则；3) 数据定价机制与价值评估方法。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-SH-EXCHANGE"],
  },
];
