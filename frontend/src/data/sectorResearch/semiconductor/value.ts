import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "半导体设备与材料是晶圆厂资本开支（Capex）中的核心开支项。公开产业讨论中，中国在全球设备市场的采购份额常被提及为较高水平，但具体百分比随年份与统计口径变化；本页不以单一政策文件支撑市场份额数字，而强调「设备 + 材料」是国产替代弹性相对更高的价值量环节。",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING", "S-SEMI-ANJI-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "价值量分层（区间估算 / 内部分析，非官方统计）：设备国产化约一成至一成半、材料约两成至两成半、EDA/IP 普遍认为仍低于一成、先进封装约两成半至三成。上述区间用于结构理解，不作为投资定价依据。",
    sourceIds: [],
  },
  {
    type: "bullets",
    items: [
      "设备：北方华创、中微等年报披露多品类设备研发与出货增长，价值量弹性高，但验证周期长。（公司口径）",
      "材料：安集等 CMP 抛光液与湿电子化学品在先进节点验证推进，单片耗材属性带来持续消耗逻辑。（公司口径）",
      "EDA / IP：生态壁垒高，国产化率估算仍低，短期难以用「份额」线性外推。",
      "先进封装：相对更接近全球工艺讨论，但仍需区分「能力披露」与「大规模份额」。",
    ],
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-NAURA-SITE",
      "S-SEMI-AMEC-SITE",
    ],
  },
  {
    type: "table",
    caption: "设备 / 材料价值量关注点（定性，公司口径 + 内部分析）",
    headers: ["环节", "价值量特征", "国内代表披露主体", "观察要点"],
    rows: [
      ["前道刻蚀 / 薄膜", "单台价值高、验证壁垒高", "北方华创、中微公司", "出货结构、先进节点验证"],
      ["CMP 与湿化学品", "耗材属性、随产能消耗", "安集科技", "14nm 及以下导入进度"],
      ["晶圆代工 Capex", "拉动设备与材料总需求", "中芯国际等", "资本开支与产能利用率"],
    ],
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-SMIC-FILING",
    ],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证：设备订单增长的可持续性、材料在关键节点的复购率，以及国产 EDA 工具链的实际收入与客户粘性，均需后续财报与客户验证交叉确认。",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-ANJI-FILING"],
  },
  {
    type: "risk",
    items: [
      "晶圆厂资本开支周期性：下行期设备订单与估值溢价可能同步回落。",
      "国产替代估值溢价风险：市场预期若快于验证进度，可能出现预期差。",
      "关键零部件与子系统仍可能受出口管制影响，制约整机交付节奏。",
    ],
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-GOV-POLICY"],
  },
];
