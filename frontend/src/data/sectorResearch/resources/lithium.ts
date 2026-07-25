import type { ContentBlock } from "../types.ts";

export const lithiumBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "锂钴镍是动力与储能电池关键金属：资源端全球化（南美盐湖、澳洲锂辉石、刚果钴、印尼镍），加工与材料端中国产能集中。华友钴业、天齐锂业、赣锋锂业等是一体化或资源型代表（公司口径）。",
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-TIANQI-FILING", "S-RES-GANFENG-FILING", "S-RES-MNR-MINERALS"],
  },
  {
    type: "paragraph",
    text: "锂用于磷酸铁锂与三元正极；钴提升三元稳定性与能量密度但有成本与 ESG 约束；镍支撑高镍三元能量密度。价格周期由「矿山资本开支滞后 + 电池需求增速」共同决定，2022–2024 年锂价大幅回落即是供需错配的典型样本（分析推断）。",
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-GANFENG-FILING", "S-RES-TIANQI-FILING"],
  },
  {
    type: "compareTable",
    caption: "锂 / 钴 / 镍资源格局对比（定性）",
    headers: ["维度", "锂", "钴", "镍"],
    rows: [
      ["核心应用", "LFP/三元正极、储能", "高能量密度三元、高温合金等", "高镍三元、不锈钢（分流）"],
      ["资源地理", "南美盐湖、澳洲硬岩、中国盐湖/锂云母", "刚果（金）高度集中", "印尼红土镍等"],
      ["中国优势环节", "冶炼加工与材料", "冶炼加工与前驱体", "高冰镍/MHP 加工与材料"],
      ["代表A股", "天齐锂业、赣锋锂业", "华友钴业、寒锐钴业等", "华友钴业等"],
      ["关键风险", "价格周期、矿端放量", "地缘与 ESG", "印尼政策与不锈钢需求分流"],
    ],
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-HUAYOU-IR", "S-RES-TIANQI-FILING", "S-RES-GANFENG-FILING"],
  },
  {
    type: "table",
    caption: "一体化路径与利润池位置（内部分析）",
    headers: ["路径", "典型做法", "利润更敏感点", "代表"],
    rows: [
      ["资源为王", "控股优质矿山/盐湖", "矿价与现金成本", "天齐锂业等"],
      ["加工+材料", "锂盐/前驱体/正极延伸", "加工费与产品溢价", "赣锋锂业、华友钴业"],
      ["海外冶炼基地", "印尼等资源国建厂", "政策、能源成本、物流", "华友钴业等"],
    ],
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-GANFENG-FILING", "S-RES-TIANQI-FILING"],
  },
  {
    type: "bullets",
    items: [
      "华友钴业：钴镍锂新能源材料与资源一体化，印尼与非洲布局是公司口径重点。",
      "天齐锂业：优质锂资源权益是核心资产，业绩与锂价高度相关（公司口径）。",
      "赣锋锂业：锂盐加工与多资源路线并行，并向下游客电池等延伸（公司口径，参见年报）。",
      "研究应区分「吨价」与「单吨利润」：低价期成本曲线位置比名义产能更重要（内部分析）。",
    ],
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-TIANQI-FILING", "S-RES-GANFENG-FILING"],
  },
  {
    type: "risk",
    items: [
      "锂价中枢下移时高成本矿山与锂云母产能出清压力上升。",
      "钴面临化学体系去钴化与回收利用带来的长期需求不确定性。",
      "镍同时受不锈钢周期与电池需求拉动，价格信号易被混淆。",
      "海外项目建设与政策变更导致资本开支超支与投产延期。",
    ],
    sourceIds: ["S-RES-HUAYOU-FILING", "S-RES-MNR-MINERALS", "S-RES-GANFENG-FILING"],
  },
];
