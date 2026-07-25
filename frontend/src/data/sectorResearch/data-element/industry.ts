import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "数据要素板块呈现「基础设施+确权服务+数据运营」三层格局。深桑达A/易华录在数据基础设施领域领先，人民网在数据确权具备公信力优势，云赛智联/上海钢联等则在垂直数据运营领域形成壁垒。",
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-SANGDA-FILING"],
  },
  {
    type: "bullets",
    items: [
      "易华录：数据湖+数据银行模式覆盖全国多城市，政务数据基础设施与数据要素运营双轮驱动（公司口径）。",
      "人民网：人民数保、人民数据、人民网数据要素业务，数据确权与内容安全具备公信力（公司口径）。",
      "上海钢联：大宗商品数据服务龙头，数据产品上架交易所，数据资产化先行（公司口径）。",
      "云赛智联：智慧城市+数据中心基础设施，公共数据授权运营在上海推进（公司口径）。",
      "深桑达A：中国电子云+数据金库+数据元件体系，支撑数据安全与数据要素化（公司口径）。",
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING", "S-DATA-STEEL-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-SANGDA-FILING"],
  },
  {
    type: "table",
    caption: "数据要素核心厂商竞争力矩阵",
    headers: ["厂商", "核心赛道", "护城河", "商业化进展", "事实/口径等级"],
    rows: [
      ["易华录", "数据湖+数据银行", "政府关系+数据资源", "数据湖运营+数据银行", "公司口径（年报披露）"],
      ["人民网", "数据确权+内容安全", "党报公信力+牌照", "人民数保运营", "公司口径（年报披露）"],
      ["上海钢联", "大宗商品数据", "行业数据+用户规模", "数据产品交易", "公司口径（年报披露）"],
      ["云赛智联", "智慧城市+数据中心", "上海区域+政府关系", "公共数据运营", "公司口径（年报披露）"],
      ["深桑达A", "数据基础设施", "中国电子云+数据金库", "数据元件+数据安全", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-DATA-EHUA-FILING", "S-DATA-PEOPLE-FILING", "S-DATA-STEEL-FILING", "S-DATA-YUNSAI-FILING", "S-DATA-SANGDA-FILING"],
  },
  {
    type: "risk",
    items: [
      "政策落地风险：数据要素基础制度细则出台进度可能低于预期。",
      "数据定价风险：数据资产定价机制不成熟，价值评估缺乏统一标准。",
      "隐私合规风险：数据流通中的隐私保护与合规要求趋严。",
      "公共数据开放风险：政务/医疗等高价值公共数据开放节奏存在不确定性。",
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-SH-EXCHANGE"],
  },
];
