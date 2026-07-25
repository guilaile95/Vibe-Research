import type { ContentBlock } from "../types.ts";

export const attributionBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "确权是流通前提：《数据二十条》提出数据资源持有权、加工使用权、产品经营权分置，为登记、授权与收益分配提供制度方向（官方口径）。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-GOV-PORTAL"],
  },
  {
    type: "paragraph",
    text: "实践中确权要回答三问：数据由谁持有管理、谁有权加工使用、开发出的数据产品由谁经营并分配收益。公共数据、企业数据与个人相关数据的规则强度不同，不能套用同一商业模板（分析推断）。",
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-CAC"],
  },
  {
    type: "compareTable",
    caption: "三权分置对照",
    headers: ["权利类型", "权利主体（方向）", "核心权能", "典型场景"],
    rows: [
      ["数据资源持有权", "数据持有者", "持有、管理、授权", "政务数据、企业运营数据"],
      ["数据加工使用权", "数据处理者", "加工、分析、获得合法收益", "治理、建模、产品开发"],
      ["数据产品经营权", "数据产品开发者", "经营、交易、收益分配", "上架交易所/对外服务"],
    ],
    sourceIds: ["S-DATA-20-ARTICLES"],
  },
  {
    type: "bullets",
    items: [
      "人民网：依托媒体公信力推进数据相关登记/服务业务（公司口径，细节见定期报告）。",
      "易华录：数据湖汇聚 + 治理/运营服务，与确权登记场景结合（公司口径）。",
      "技术支撑：区块链存证、水印、访问控制与审计日志提高可追溯性，但不能替代法律制度。",
      "地方登记机构与交易所规则仍在磨合，跨区域互认是中期课题（分析推断）。",
    ],
    sourceIds: ["S-DATA-PEOPLE-FILING", "S-DATA-EHUA-FILING", "S-DATA-SH-EXCHANGE", "S-DATA-PEOPLE-IR"],
  },
  {
    type: "table",
    caption: "确权落地常见卡点",
    headers: ["卡点", "表现", "可能解法"],
    rows: [
      ["权属不清", "多主体采集、历史系统混乱", "数据目录+权责清单+合同"],
      ["个人信息夹杂", "无法直接产品化", "脱敏、最小必要、隐私计算"],
      ["收益难分", "贡献度量缺失", "约定分成+计量审计"],
      ["跨域互认", "登记结果难通用", "标准与互联互通"],
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-CAC", "S-DATA-SH-EXCHANGE"],
  },
  {
    type: "risk",
    items: [
      "只有登记仪式、没有使用与付费，确权业务难闭环。",
      "权属争议与侵权风险上升，保险与合规成本增加。",
      "过度强调链上存证而忽视治理质量，形成技术泡沫（分析推断）。",
    ],
    sourceIds: ["S-DATA-20-ARTICLES", "S-DATA-PEOPLE-FILING", "S-DATA-CAC"],
  },
];
