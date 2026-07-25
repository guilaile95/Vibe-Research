import type { ContentBlock } from "../types.ts";

export const tungstenBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "钨、钼是硬质合金与特种钢/高温合金的关键元素。中国在钨资源与加工、钼采选冶炼等环节具备全球影响力。需求与制造业切削工具、矿山开采、能源装备及部分军工材料相关；供给端受总量调控、环保与出口管理影响（官方口径/产业特征）。",
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-XIAMEN-TUNGSTEN-FILING", "S-RES-GOV-PORTAL"],
  },
  {
    type: "table",
    caption: "钨钼及相关战略小金属应用映射",
    headers: ["材料", "核心应用领域", "产业特征", "代表A股厂商"],
    rows: [
      ["钨", "硬质合金、电子、军工", "资源集中、加工链条长", "厦门钨业、中钨高新、章源钨业等"],
      ["钼", "合金钢、催化剂、高温合金", "与钢厂需求联动", "金钼股份、洛阳钼业等"],
      ["锑", "阻燃、铅酸电池、军工等", "供给扰动对价格敏感", "湖南黄金等"],
    ],
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-XIAMEN-TUNGSTEN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "厦门钨业：钨钼 + 稀土 + 锂电材料多元布局，硬质合金与钨丝等是传统优势（公司口径）。",
      "硬质合金需求与制造业 PMI、汽车/模具/矿山机械开工相关，是钨价的重要验证指标（分析推断）。",
      "钼价常随不锈钢与合金钢需求波动，能源与化工催化剂构成额外需求层。",
      "战略小金属交易盘体量小，价格易被情绪与贸易政策放大，需区分库存扰动与真实短缺。",
    ],
    sourceIds: ["S-RES-XIAMEN-TUNGSTEN-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "compareTable",
    caption: "钨 vs 钼研究侧重点",
    headers: ["维度", "钨", "钼"],
    rows: [
      ["需求锚", "硬质合金刀具/矿用合金", "合金钢、不锈钢、催化剂"],
      ["供给政策", "保护性开采/总量管理敏感", "矿山与冶炼环保约束"],
      ["价格特征", "小金属属性、波动大", "与钢厂补库周期相关"],
      ["一体化价值", "矿—冶—硬质合金延伸", "采选—钼化工/金属"],
    ],
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-XIAMEN-TUNGSTEN-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证事项：1) 钨钼出口与配额/许可政策是否进一步收紧；2) 制造业复苏斜率对硬质合金的实际拉动；3) 军工高温合金与特种材料订单是否形成可持续增量（非短期主题）。",
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-GOV-PORTAL", "S-RES-XIAMEN-TUNGSTEN-FILING"],
  },
  {
    type: "risk",
    items: [
      "制造业资本开支疲软压制硬质合金需求。",
      "环保与安全检查导致矿山/冶炼阶段性停产，价格脉冲后快速回落。",
      "出口政策变化引发贸易商囤货，扭曲现货信号。",
      "多元业务公司（如钨+锂电）估值切换造成股价噪音，需分拆业务跟踪。",
    ],
    sourceIds: ["S-RES-XIAMEN-TUNGSTEN-FILING", "S-RES-MNR-MINERALS"],
  },
];
