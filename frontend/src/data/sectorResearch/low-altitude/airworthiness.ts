import type { ContentBlock } from "../types.ts";

/**
 * 适航、量产和商业运营 Tag 内容块（低空经济研究工作台）。
 */
export const airworthinessBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "适航认证是低空经济从概念走向商业化的核心门票。eVTOL 在中国需取得 CAAC 颁发的型号合格证（TC）、生产许可证（PC）和单机适航证（AC）。全球范围看，欧美中三地适航标准的互认程度和节奏差异将直接决定 eVTOL 制造商的出海能力和供应链布局。",
    sourceIds: ["S-LOWALT-CAAC-CCAR21", "S-LOWALT-POLICY-FRAMEWORK"],
  },
  {
    type: "bullets",
    items: [
      "TC（型号合格证）：确认型号设计符合适航标准；是适航认证中最耗时、成本最高的环节，通常耗时 3–7 年。",
      "PC（生产许可证）：确认制造企业具备批量生产符合批准型号设计产品的能力。",
      "AC（单机适航证）：确认单架航空器符合经批准的型号设计，可投入运营。",
      "运营许可/运行批准：运营商需取得 CCAR-135/136/91 部运行合格证后才能投入商业载客/作业运营。",
    ],
    sourceIds: ["S-LOWALT-CAAC-CCAR21", "S-LOWALT-CAAC-CCAR91-135"],
  },
  {
    type: "paragraph",
    text: "全球 eVTOL 适航进展概览（截至 2024–2025 年）：EASA 和 FAA 均已建立 eVTOL 专用适航框架（SC-VTOL / 21.17(b)），CAAC 也在 2024 年发布了《电动垂直起降航空器型号合格审定程序》。亿航智能 EH216-S 于 2023 年取得 CAAC TC，是全球首个取得 eVTOL TC 的型号；国内其他主要 eVTOL 项目（如沃飞长空、峰飞航空、时的科技等）尚在适航取证过程中，具体阶段节点尚无统一公开披露。（分析推断）",
    sourceIds: ["S-LOWALT-CAAC-CCAR21", "S-LOWALT-EASA-FAA-STD", "S-LOWALT-POLICY-FRAMEWORK"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证：除亿航 EH216-S 已取得 CAAC TC 为已确认事实外，国内其他 eVTOL 项目的具体适航阶段（已受理/已审定/已通过部分 CRI/即将 TC）在公开渠道中披露不完整。各制造商官网和公告中的表述差异大，需交叉验证。万丰奥威年报中提及 eVTOL 研发进展但未披露适航阶段的具体时间表。",
    sourceIds: ["S-LOWALT-WANFENG-FILING", "S-LOWALT-CAAC-CCAR21"],
  },
  {
    type: "paragraph",
    text: "量产路径与产能规划：eVTOL 的量产面临与传统航空业类似的产能爬坡挑战——供应链认证（宇航级/航空级标准）、装配线投入、熟练技能技工培训和良率控制。与传统航空不同的是，eVTOL 产业链引入更多汽车供应链经验（电池、电机、电控），有望压缩部分学习曲线。但具体产能目标与良率数据目前尚无公开资料确认。（分析推断）",
    sourceIds: ["S-LOWALT-EASA-FAA-STD", "S-LOWALT-AVICHIGHTECH-FILING"],
  },
  {
    type: "table",
    caption: "eVTOL 量产挑战对比：航空级 vs 汽车级供应链标准",
    headers: ["维度", "航空级供应链", "汽车级供应链", "eVTOL 实际需求"],
    rows: [
      ["质量认证周期", "长（2–5 年）", "短（6–18 个月）", "介于中间（待确认）"],
      ["批量规模", "小批量（数十到几百/年）", "大批量（百万/年）", "千–万量级/年（中期预测）"],
      ["单件成本容忍度", "高", "极低", "中等（需要显著降本）"],
      ["适航/安全标准", "极高（DO-178C/DO-254）", "高（ASPICE/ISO 26262）", "基于航空级可能部分采用汽车级"],
      ["培训和维护网络", "低频专业维修", "密集型网点", "需要新型分布式维护体系"],
    ],
    sourceIds: ["S-LOWALT-EASA-FAA-STD"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "适航节奏风险（分析推断）：eVTOL 适航进度是当前板块最大的不确定因素。乐观情景下海内外个别项目 2025–2026 年陆续取证、2027–2028 年有限商业运营；悲观情景下认证延期导致该时间表整体后移 2–3 年。两种情景差异来自适航当局人力资源配置、新技术标准的成熟度以及供应链对制造标准的适应速度。目前尚无公开资料确认任一情景的概率分布。",
    sourceIds: ["S-LOWALT-CAAC-CCAR21", "S-LOWALT-POLICY-FRAMEWORK"],
  },
  {
    type: "paragraph",
    text: "商业运营条件：除适航取证外，eVTOL 商业运营还需满足（1）运营基地获得起降场使用许可；（2）运营商取得 CCAR-135/136 运行合格证；（3）空管部门完成低空航线划设与动态空域分配；（4）保险产品覆盖；（5）公众接受度。上述条件中任一滞后都会拖累商业运营的启动节奏。",
    sourceIds: [
      "S-LOWALT-CITIC-FILING",
      "S-LOWALT-LAISI-FILING",
      "S-LOWALT-CAAC-CCAR91-135",
    ],
  },
  {
    type: "risk",
    items: [
      "认证延迟：CAAC 对全新机型审定的人力与经验有限，多个项目同步申报可能导致审定时长超预期。",
      "标准迭代风险：适航标准在审定过程中可能因技术路线修正而增加补充要求（如特定条件下的失效概率评估）。",
      "量产良率风险：小批量手工装配过渡到中大批量制造时，良率波动可能显著拖累交付计划。",
      "运营许可滞后：即使取得 TC/PC，运营商取得运行合格证的进度也可能慢于预期。",
      "国际认证互认有限：CAAC vs EASA vs FAA 之间的互认程度有限，国产 eVTOL 出海面临二次认证成本。",
    ],
    sourceIds: ["S-LOWALT-CAAC-CCAR21", "S-LOWALT-EASA-FAA-STD"],
  },
];
