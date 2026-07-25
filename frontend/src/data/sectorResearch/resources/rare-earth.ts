import type { ContentBlock } from "../types.ts";

export const rareEarthBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "稀土管理条例明确总量调控：国务院令第784号对稀土开采与冶炼分离实行总量调控指标管理，北方稀土与中国稀土主导稀土矿开采与冶炼分离（官方口径）。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-BEIRARE-FILING"],
  },
  {
    type: "paragraph",
    text: "稀土是17种金属元素的总称，分为轻稀土（镧铈镨钕等）与重稀土（钆铽镝钬等）两类。中国是全球稀土储量与产量第一大国，内蒙古白云鄂博矿（北方稀土）与南方离子型矿（中国稀土）是主要资源地。",
    sourceIds: ["S-RES-MIIT-RARE", "S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING"],
  },
  {
    type: "compareTable",
    caption: "轻稀土 vs 重稀土对比",
    headers: ["维度", "轻稀土", "重稀土"],
    rows: [
      ["主要元素", "镧、铈、镨、钕", "钆、铽、镝、钬、铒、铥、镱、镥、钇"],
      ["主要产地", "内蒙古白云鄂博、四川凉山", "江西、福建、广东离子型矿"],
      ["核心应用", "永磁、催化、抛光、储氢", "永磁（高温）、荧光、激光、军工"],
      ["战略价值", "高（钕铁硼永磁）", "极高（高温永磁/军工）"],
      ["代表厂商", "北方稀土、盛和资源", "中国稀土、广晟有色"],
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-MIIT-RARE"],
  },
  {
    type: "bullets",
    items: [
      "北方稀土：轻稀土龙头，依托白云鄂博矿，稀土冶炼分离与功能材料产能行业第一（公司口径）。",
      "中国稀土：南方离子型稀土矿主导，重稀土资源稀缺性强（公司口径）。",
      "稀土永磁：钕铁硼永磁是新能源电机与消费电子核心材料，金力永磁、中科三环等是代表厂商。",
      "出口管制：稀土产品出口需配额与许可证，是应对外部技术封锁的重要筹码。",
    ],
    sourceIds: ["S-RES-BEIRARE-FILING", "S-RES-CHINARARE-FILING", "S-RES-MIIT-RARE"],
  },
];
