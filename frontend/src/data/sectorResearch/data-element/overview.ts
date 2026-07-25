import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层制度：《数据二十条》提出数据产权、流通交易、收益分配、安全治理四项基础制度，并明确数据资源持有权、加工使用权、产品经营权分置方向。数据要素从「政策概念」进入「制度 + 场景落地」阶段（官方口径）。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-GOV-PORTAL"],
  },
  {
    type: "paragraph",
    text: "数据要素板块可拆为确权登记、交易流通、公共数据授权运营、安全合规与数据基础设施五条线。与传统软件不同，其商业化取决于制度细则、公共数据开放节奏与可复用数据产品，而非单纯技术演示（分析推断）。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING", "S-DATA-SH-EXCHANGE"],
  },
  {
    type: "bullets",
    items: [
      "确权：三权分置解决「谁持有、谁加工、谁经营」；登记与存证是流通前提。",
      "交易：地方数据交易所提供登记、合规、撮合；成交活跃度与产品标准化程度仍不均衡。",
      "公共数据：政务/医疗/交通等高价值数据通过授权运营释放，是当前最可规模化的供给源之一。",
      "安全：分类分级、隐私计算、出境评估与等保密评构成合规底座。",
      "基建：数据湖/数据中心/行业云与「数据元件」等形态支撑汇聚、治理与服务化。",
    ],
    sourceIds: [
      "S-DATA-20-ARTICLES",
      "S-DATA-EHUA-FILING",
      "S-DATA-PEOPLE-FILING",
      "S-DATA-YUNSAI-FILING",
      "S-DATA-SANGDA-FILING",
      "S-DATA-CAC",
    ],
  },
  {
    type: "table",
    caption: "数据要素五大方向与代表厂商",
    headers: ["方向", "核心能力", "关键壁垒", "代表A股/主体"],
    rows: [
      ["数据确权", "登记/确权/溯源", "公信力+制度接口+技术", "人民网、易华录"],
      ["数据交易", "登记/合规/撮合", "规则+生态+产品供给", "上海数据交易所等"],
      ["公共数据", "授权运营/治理/产品化", "政府关系+数据资源", "易华录、云赛智联"],
      ["数据安全", "隐私计算/合规治理", "资质+技术+客户信任", "深桑达A 等（及网安厂商）"],
      ["数据基础设施", "湖/云/金库/元件", "资金+集成+信创", "深桑达A、云赛智联、易华录"],
    ],
    sourceIds: [
      "S-DATA-EHUA-FILING",
      "S-DATA-PEOPLE-FILING",
      "S-DATA-YUNSAI-FILING",
      "S-DATA-SANGDA-FILING",
      "S-DATA-SH-EXCHANGE",
    ],
  },
  {
    type: "compareTable",
    caption: "数据要素 vs 传统软件/IT 服务（内部分析）",
    headers: ["维度", "传统软件/集成", "数据要素相关业务"],
    rows: [
      ["收入确认", "项目制/订阅为主", "授权运营分成、数据服务、交易佣金等更复杂"],
      ["关键约束", "交付与回款", "合规、权属、场景付费意愿"],
      ["可复制性", "方案可复制", "强依赖本地数据资源与制度"],
      ["验证指标", "订单/人效", "可交易产品数、复购、入表与合规通过"],
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-EHUA-FILING", "S-DATA-STEEL-FILING"],
  },
  {
    type: "risk",
    items: [
      "制度细则与地方试点节奏慢于市场预期，主题交易易退潮。",
      "数据定价与资产入表标准不统一，财务与商业模式难对标。",
      "隐私与安全事件会直接中断流通业务。",
      "交易所披露的交易额口径可能含框架协议，需审慎引用（数据质量风险）。",
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-SH-EXCHANGE", "S-DATA-CAC"],
  },
];
