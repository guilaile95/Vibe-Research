import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层制度：《稀土管理条例》确立稀土开采、冶炼分离等环节监管与总量调控框架；自然资源部对战略性矿产实施保护性开采与总量管理。资源「卡口」属性来自不可替代用途 + 供给集中 + 贸易管制工具（官方口径）。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS", "S-RES-GOV-PORTAL"],
  },
  {
    type: "paragraph",
    text: "资源卡口板块覆盖稀土、锗铟镓、锂钴镍、钨钼等关键战略资源。其共性是：下游绑定新能源、半导体、国防与高端制造；供给端高度依赖资源禀赋与冶炼加工能力；政策与出口管制可显著改变价格与贸易流向。中国在多个品类的开采/冶炼加工环节具备全球影响力（分析推断需与官方统计交叉验证）。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-MNR-MINERALS", "S-RES-BEIRARE-FILING"],
  },
  {
    type: "bullets",
    items: [
      "稀土：轻稀土（北方体系）与重稀土（南方离子型）分工明确，永磁材料是新能源与军工关键下游。",
      "锗铟镓：多作为锌/铝冶炼副产回收，用于红外、光纤、显示与化合物半导体；出口管制强化战略属性。",
      "锂钴镍：动力与储能电池正极核心金属，资源全球化布局与加工产能集中并存。",
      "钨钼：硬质合金、特种钢与高温合金关键添加元素，与制造业与军工景气相关。",
      "研究重点不在口号式「资源安全」，而在配额/管制、价格中枢、冶炼加工利润与下游需求验证（内部分析）。",
    ],
    sourceIds: [
      "S-RES-BEIRARE-FILING",
      "S-RES-YUNNAN-GE-FILING",
      "S-RES-HUAYOU-FILING",
      "S-RES-XIAMEN-TUNGSTEN-FILING",
      "S-RES-GANFENG-FILING",
    ],
  },
  {
    type: "table",
    caption: "关键战略资源与产业位置（定性；全球占比需以官方统计更新）",
    headers: ["资源类别", "核心用途", "中国环节优势（定性）", "代表A股厂商"],
    rows: [
      ["稀土", "永磁/催化/抛光/军工", "开采+冶炼分离+材料加工完整", "北方稀土、中国稀土"],
      ["锗", "红外光学/光纤/光伏", "精炼与材料加工能力强", "云南锗业、株冶集团"],
      ["铟", "ITO 靶材/显示", "冶炼回收与加工", "株冶集团等"],
      ["镓", "化合物半导体/LED/射频", "副产回收规模优势", "株冶集团等"],
      ["锂", "动力/储能电池", "加工与材料环节优势突出", "天齐锂业、赣锋锂业"],
      ["钴/镍", "三元正极等", "冶炼加工与一体化材料", "华友钴业"],
      ["钨/钼", "硬质合金/特种钢", "资源与加工双优势（品类差异）", "厦门钨业等"],
    ],
    sourceIds: [
      "S-RES-MIIT-RARE",
      "S-RES-MNR-MINERALS",
      "S-RES-BEIRARE-FILING",
      "S-RES-YUNNAN-GE-FILING",
      "S-RES-ZUYE-FILING",
      "S-RES-HUAYOU-FILING",
      "S-RES-TIANQI-FILING",
      "S-RES-GANFENG-FILING",
    ],
  },
  {
    type: "compareTable",
    caption: "「资源型」vs「材料加工型」标的差异（内部分析）",
    headers: ["维度", "资源/采矿冶炼偏重", "材料加工/一体化偏重"],
    rows: [
      ["盈利驱动", "矿价、配额、品位与成本", "加工费、产品结构、客户认证"],
      ["波动性", "商品价格弹性高", "相对平滑但仍受原料传导"],
      ["政策敏感点", "总量调控、出口许可", "环保、能耗、下游补贴/需求"],
      ["研究优先指标", "产量指标、库存、FOB/国内价", "开工率、单吨毛利、长协占比"],
    ],
    sourceIds: ["S-RES-MNR-MINERALS", "S-RES-HUAYOU-FILING", "S-RES-BEIRARE-FILING"],
  },
  {
    type: "risk",
    items: [
      "商品价格大幅波动导致业绩与估值剧烈摇摆。",
      "出口管制与配额调整改变贸易流，亦可能引发下游替代加速。",
      "海外资源国政策、社区与物流风险影响原料保障。",
      "公开「全球占比」数据口径不一，引用时需标注统计来源年份（数据质量风险）。",
    ],
    sourceIds: ["S-RES-GOV-PORTAL", "S-RES-MNR-MINERALS", "S-RES-HUAYOU-FILING"],
  },
];
