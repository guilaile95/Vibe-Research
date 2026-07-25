import type { ContentBlock } from "../types.ts";

export const exchangeBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "数据交易所是流通组织者：提供产品登记、合规审查、撮合与交付服务。上海数据交易所等是公开市场的重要节点；具体成交规模以官方披露为准，避免二手夸张数字（官方口径）。",
    sourceIds: ["S-DATA-SH-EXCHANGE", "S-DATA-20-ARTICLES"],
  },
  {
    type: "paragraph",
    text: "国内已形成多地交易所并存格局，定位上区分金融/国际/制造业/西部枢纽等。真正决定活跃度的是可标准化的数据产品供给、买方付费场景与合规工具是否好用，而不是交易所数量（分析推断）。",
    sourceIds: ["S-DATA-SH-EXCHANGE", "S-DATA-STEEL-FILING", "S-DATA-20-ARTICLES"],
  },
  {
    type: "table",
    caption: "主要数据交易所定位对比（定性）",
    headers: ["交易所", "核心定位", "特色领域", "观察要点"],
    rows: [
      ["上海数据交易所", "要素市场重要节点", "金融/交通/医疗等", "产品登记与规则完善度"],
      ["北京国际大数据交易所", "国际与科研数据", "跨境/科研/隐私计算", "跨境与合规工具"],
      ["深圳数据交易所", "大湾区流通", "跨境/金融/制造", "粤港澳场景"],
      ["贵阳大数据交易所", "西部枢纽", "政务/农业/文旅", "公共数据供给"],
      ["广州数据交易所", "工业数据", "制造/供应链", "工业数据产品化"],
    ],
    sourceIds: ["S-DATA-SH-EXCHANGE", "S-DATA-20-ARTICLES", "S-DATA-GOV-PORTAL"],
  },
  {
    type: "bullets",
    items: [
      "产品形态：数据包、API、模型、指数与订阅服务等；标准化越高越易复购。",
      "上海钢联等行业数据商是「可交易数据产品」的重要供给方（公司口径）。",
      "数据资产入表提升企业治理数据的动力，但评估方法与审计仍在探索（政策进行中）。",
      "场内交易与场外协议并存；大量高价值交易仍可能发生在双边合同（分析推断）。",
    ],
    sourceIds: ["S-DATA-SH-EXCHANGE", "S-DATA-STEEL-FILING", "S-DATA-STEEL-IR", "S-DATA-20-ARTICLES"],
  },
  {
    type: "compareTable",
    caption: "场内交易所 vs 场外/直接授权",
    headers: ["维度", "场内交易所", "场外/直接授权运营"],
    rows: [
      ["合规展示", "统一审查与公示更强", "合同自制，透明度不一"],
      ["产品标准化", "倾向标准产品", "可高度定制"],
      ["费用", "佣金/会员等", "项目制或分成"],
      ["适合对象", "可复制数据产品", "高敏感公共数据、复杂联合建模"],
    ],
    sourceIds: ["S-DATA-SH-EXCHANGE", "S-DATA-EHUA-FILING", "S-DATA-20-ARTICLES"],
  },
  {
    type: "risk",
    items: [
      "交易额口径不透明，主题营销可能夸大活跃度。",
      "买方付费习惯未形成，供给多、成交少。",
      "多地重复建设导致流动性分散。",
      "合规审查趋严可能阶段性抑制上架速度。",
    ],
    sourceIds: ["S-DATA-SH-EXCHANGE", "S-DATA-CAC", "S-DATA-20-ARTICLES"],
  },
];
