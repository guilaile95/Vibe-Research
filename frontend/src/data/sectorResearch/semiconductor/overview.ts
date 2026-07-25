import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "半导体是全球科技产业的硬件基础。中国是全球主要半导体消费市场之一，但在设备、材料、电子设计自动化（EDA）与先进制程等环节仍高度依赖进口；政策与资本持续推动「国产替代」成为当前主线之一。",
    sourceIds: ["S-SEMI-GOV-POLICY", "S-SEMI-MIIT-POLICY"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "数据质量提示：下列「国产化率 / 自给率」多为行业公开讨论中的区间估算或内部分析，并非国发〔2020〕8号等政策文件给出的官方统计。政策文件主要明确支持方向与措施，不提供分环节精确百分比。引用时请区分「政策事实」与「估算推断」。",
    sourceIds: ["S-SEMI-GOV-POLICY", "S-SEMI-MIIT-POLICY"],
  },
  {
    type: "bullets",
    items: [
      "设备国产替代率（估算 / 内部分析）：约一成至一成半量级，是弹性与关注度较高的细分方向之一。",
      "材料国产化率（估算 / 内部分析）：约两成至两成半量级，大硅片与光刻胶仍处加速验证阶段。",
      "EDA / IP 国产化率（估算 / 内部分析）：普遍认为仍低于一成，生态与工具链壁垒是核心挑战。",
      "先进制程：7nm 及以下节点仍受极紫外（EUV）光刻机等出口管制约束，公开可验证的量产节奏存在较大不确定性。",
    ],
    sourceIds: [],
  },
  {
    type: "table",
    caption:
      "中国集成电路产业链自给率概览（区间估算 / 内部分析，非官方统计）",
    headers: ["产业链环节", "国产化率估算", "主要差距点", "政策支持力度（定性）"],
    rows: [
      ["IC 设计（逻辑）", "约 15%–20%（估算）", "CPU/GPU 与 EDA 工具链生态", "强（政策与资本市场支持）"],
      ["晶圆代工（成熟）", "约 15%–20%（估算）", "设备交付与产能爬坡节奏", "强（大基金等长期投入）"],
      ["半导体设备", "约 10%–15%（估算）", "刻蚀/薄膜/检测/离子注入等差距", "强（重点支持方向）"],
      ["半导体材料", "约 20%–25%（估算）", "大硅片、光刻胶纯度与稳定性", "中等偏强"],
      ["先进封装", "约 25%–30%（估算）", "2.5D/3D 封装良率与量产经验", "中等"],
    ],
    sourceIds: [],
  },
  {
    type: "paragraph",
    text: "设备与材料侧，国内代表厂商在年报与官网中披露了可核对的业务进展：北方华创覆盖刻蚀、薄膜沉积、清洗、热处理等多类前道设备；中微公司以 CCP 刻蚀与 MOCVD 等见长；安集科技聚焦 CMP 抛光液等湿电子化学品在先进节点的验证与导入。",
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-NAURA-SITE",
      "S-SEMI-AMEC-SITE",
    ],
  },
  {
    type: "compareTable",
    caption: "核心设备国产化替代对比（公司口径 + 内部差距评估）",
    headers: ["设备类别", "国内代表厂商", "全球龙头（参照）", "差距评估（内部分析）"],
    rows: [
      ["等离子体刻蚀", "中微公司 / 北方华创", "Lam Research / TEL", "仍有代际差距（估算）"],
      ["薄膜沉积", "北方华创等", "Applied Materials / Lam", "先进节点仍有明显差距（估算）"],
      ["CMP 相关材料", "安集科技（抛光液等）", "海外材料与设备巨头", "部分产品接近导入门槛（公司口径）"],
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
    type: "paragraph",
    text: "制造侧，中芯国际年报与官网披露成熟制程代工产能、资本开支与工艺平台布局；先进节点公开信息有限，不宜将「研发进展」直接等同于「大规模量产已确认」。",
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-SMIC-SITE"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证事项：1）国产先进制程在 2025–2026 年可公开验证的量产进展；2）EUV 等关键设备出口政策变化；3）国产 EDA 在先进节点的实际工程成功率。（待验证 / 内部跟踪）",
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-GOV-POLICY"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "反证与失效条件（分析推断）：若美日荷设备出口管制进一步收紧超出预期，或国产设备在关键节点的良率/产能持续低于预期，国产替代节奏可能显著延后。",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING"],
  },
  {
    type: "risk",
    items: [
      "出口管制升级风险：实体清单与物项管制范围可能继续扩大。",
      "先进制程突破不确定性：7nm 及以下攻关依赖长期工艺与生态积累。",
      "产能利用率周期波动：全球半导体下行周期可能压制成熟制程需求与资本开支。",
    ],
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-GOV-POLICY", "S-SEMI-MIIT-POLICY"],
  },
];
