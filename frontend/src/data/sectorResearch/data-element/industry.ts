import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "产业格局可概括为三层：基础设施（湖/云/安全）、确权与合规服务、数据运营与行业数据产品。深桑达A、易华录偏基建与城市数据；人民网偏确权与公信力；上海钢联等偏垂直数据产品；云赛智联偏区域智慧城市与数字化（公司口径）。",
    sourceIds: [
      "S-DATA-EHUA-FILING",
      "S-DATA-PEOPLE-FILING",
      "S-DATA-YUNSAI-FILING",
      "S-DATA-SANGDA-FILING",
      "S-DATA-STEEL-FILING",
    ],
  },
  {
    type: "bullets",
    items: [
      "易华录：数据湖与数据要素运营相关布局（公司口径）。",
      "人民网：数据与内容安全相关业务，强调公信力（公司口径）。",
      "上海钢联：大宗商品数据服务与产品化能力（公司口径）。",
      "云赛智联：智慧城市与数据中心等数字化能力（公司口径）。",
      "深桑达A：中国电子云与数据基础设施/安全方向（公司口径）。",
      "交易所与地方大数据集团：规则制定与公共资源入口，本身不一定是上市公司。",
    ],
    sourceIds: [
      "S-DATA-EHUA-FILING",
      "S-DATA-PEOPLE-FILING",
      "S-DATA-STEEL-FILING",
      "S-DATA-YUNSAI-FILING",
      "S-DATA-SANGDA-FILING",
      "S-DATA-SH-EXCHANGE",
    ],
  },
  {
    type: "table",
    caption: "数据要素相关厂商竞争力矩阵（定性）",
    headers: ["厂商", "核心赛道", "护城河", "商业化观察", "口径"],
    rows: [
      ["易华录", "数据湖/运营", "城市项目与数据汇聚", "运营收入占比与回款", "公司口径"],
      ["人民网", "确权/内容与数据服务", "公信力与品牌", "数据业务披露质量", "公司口径"],
      ["上海钢联", "行业数据产品", "数据与用户网络", "订阅与增值服务", "公司口径"],
      ["云赛智联", "智慧城市/数字化", "区域与集成能力", "公共数据相关项目", "公司口径"],
      ["深桑达A", "云与数据安全基建", "电子体系与安全", "云+数据订单结构", "公司口径"],
    ],
    sourceIds: [
      "S-DATA-EHUA-FILING",
      "S-DATA-PEOPLE-FILING",
      "S-DATA-STEEL-FILING",
      "S-DATA-YUNSAI-FILING",
      "S-DATA-SANGDA-FILING",
    ],
  },
  {
    type: "compareTable",
    caption: "更可持续的商业模式 dual（内部分析）",
    headers: ["模式", "优点", "弱点", "验证信号"],
    rows: [
      ["项目制基建", "订单可见、符合政企采购", "回款与折旧压力", "新签/应收账款"],
      ["数据产品订阅", "可复购、边际成本低", "冷启动难", "续费率、ARPU"],
      ["授权运营分成", "绑定公共数据资源", "规则与谈判不确定", "分成落地与审计"],
      ["交易佣金", "轻资产", "取决于流动性", "活跃产品与成交质量"],
    ],
    sourceIds: ["S-DATA-STEEL-FILING", "S-DATA-EHUA-FILING", "S-DATA-SH-EXCHANGE", "S-DATA-20-ARTICLES"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "内部分析：优先跟踪「已入表/已上架/已复购」的数据产品，而不是「签约战略合作」新闻数量。",
    sourceIds: ["S-DATA-STEEL-FILING", "S-DATA-SH-EXCHANGE", "S-DATA-20-ARTICLES"],
  },
  {
    type: "risk",
    items: [
      "政策细则慢于预期，主题估值回撤。",
      "数据定价与入表标准不统一，财务不可比。",
      "隐私合规趋严抬高成本。",
      "公共数据开放不及预期。",
      "政企项目回款与商誉/资产减值风险。",
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-SH-EXCHANGE", "S-DATA-CAC", "S-DATA-EHUA-FILING"],
  },
];
