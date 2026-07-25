import type { ContentBlock } from "../types.ts";

export const publicDataBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "公共数据授权运营是高价值供给的重要来源：政务、医疗、交通、气象等数据经由授权、治理与产品化后对外服务。易华录、云赛智联等参与智慧城市与数据基础设施的厂商，更贴近这一场景（公司口径）。",
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-20-ARTICLES"],
  },
  {
    type: "table",
    caption: "公共数据类型与运营模式（定性）",
    headers: ["公共数据类型", "潜在价值场景", "常见模式", "相关主体示例"],
    rows: [
      ["政务数据", "治理、风控、便民服务", "授权运营/特许", "易华录、云赛智联等"],
      ["医疗健康", "科研、保险、公卫", "脱敏+隐私计算", "医疗 IT 与数据平台商"],
      ["交通出行", "出行、物流、车路", "平台运营/采购", "城市交通数据平台"],
      ["气象地理", "农业、能源、保险", "产品化授权", "遥感/气象数据商"],
      ["行业公共信息", "价格指数、市场监测", "数据服务订阅", "上海钢联等"],
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-STEEL-FILING", "S-DATA-20-ARTICLES"],
  },
  {
    type: "bullets",
    items: [
      "授权机制：政府明确数据范围与权责，运营方负责治理、安全与产品化，收益按约定分配。",
      "易华录：数据湖等基础设施 + 运营服务，强调城市级数据汇聚（公司口径）。",
      "云赛智联：智慧城市与数字化项目经验，区域公共数据场景可延伸（公司口径）。",
      "医疗等高敏感数据必须满足分类分级与隐私保护，否则无法形成合法产品。",
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-CAC", "S-DATA-20-ARTICLES"],
  },
  {
    type: "compareTable",
    caption: "公共数据 vs 企业数据商业化路径",
    headers: ["维度", "公共数据", "企业数据"],
    rows: [
      ["供给决策", "政府授权与开放目录", "企业战略与合规评估"],
      ["壁垒", "关系+属地资源+安全能力", "独特业务数据与客户网络"],
      ["变现", "运营分成、服务费、产品订阅", "数据服务、API、联合建模"],
      ["主要风险", "政策反复、开放节奏", "商业秘密与竞争敏感"],
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-EHUA-FILING", "S-DATA-STEEL-FILING"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "待验证：全国统一的公共数据授权运营规则、收益分配指引与审计要求仍在完善；地方试点经验能否复制决定板块能否从主题走向订单。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-GOV-PORTAL", "S-DATA-SH-EXCHANGE"],
  },
  {
    type: "risk",
    items: [
      "开放目录更新慢，可运营数据少于宣传。",
      "收益分成谈判久、回款依赖财政与项目制。",
      "安全事件导致授权被收回。",
      "重复建设数据平台造成资产闲置（分析推断）。",
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-CAC", "S-DATA-20-ARTICLES"],
  },
];
