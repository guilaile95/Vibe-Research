import type { ContentBlock } from "../types.ts";

export const attributionBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "数据确权是数据要素化的首要前提：《数据二十条》提出数据资源持有权、数据加工使用权、数据产品经营权三权分置，为数据确权奠定制度基础（官方口径）。",
    sourceIds: ["S-DATA-20-ARTICLES"],
  },
  {
    type: "paragraph",
    text: "数据确权解决「数据是谁的、谁能用、收益归谁」三个核心问题。三权分置制度下，数据资源持有权归数据持有者，数据加工使用权归数据处理者，数据产品经营权归数据产品开发者。",
    sourceIds: ["S-DATA-20-ARTICLES"],
  },
  {
    type: "compareTable",
    caption: "数据确权三种权利对比",
    headers: ["权利类型", "权利主体", "核心权能", "典型场景"],
    rows: [
      ["数据资源持有权", "数据持有者", "持有/管理/授权", "企业运营数据、政务数据"],
      ["数据加工使用权", "数据处理者", "加工/使用/获得收益", "数据产品开发、数据分析"],
      ["数据产品经营权", "数据产品开发者", "经营/交易/收益分配", "数据产品上架交易"],
    ],
    sourceIds: ["S-DATA-20-ARTICLES"],
  },
  {
    type: "bullets",
    items: [
      "人民网：人民数保平台提供数据确权、登记与版权服务，依托党报公信力（公司口径）。",
      "易华录：数据湖+数据银行模式，提供数据存储、治理与确权登记服务（公司口径）。",
      "技术路径：区块链存证+数字水印+隐私计算等技术支撑数据确权与溯源。",
      "地方实践：北京、上海、深圳等地建立数据确权登记机构，推动区域数据确权落地。",
    ],
    sourceIds: ["S-DATA-PEOPLE-FILING", "S-DATA-EHUA-FILING", "S-DATA-SH-EXCHANGE"],
  },
];
