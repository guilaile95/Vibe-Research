import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "半导体是全球科技产业的硬件基础。中国是全球最大半导体消费市场，但在设备、材料、EDA和先进制程环节仍高度依赖进口，国产替代是当前最大的产业主线。",
    sourceIds: ["S-SEMI-MIIT-POLICY", "S-SEMI-EMP2024"],
  },
  {
    type: "bullets",
    items: [
      "设备国产替代率：10-15%，增长最快的细分领域。",
      "材料国产化率：20-25%，大硅片与光刻胶在加速验证中。",
      "EDA/IP 国产化率：低于 10%，生态壁垒是核心挑战。",
      "先进制程：7nm 以下仍受 EUV 光刻机出口管制限制。",
    ],
    sourceIds: ["S-SEMI-EMP2024"],
  },
  {
    type: "table",
    caption: "中国集成电路产业链自给率概览（行业数据汇总 / 内部分析）",
    headers: ["产业链环节", "国产化率估算", "主要差距点", "政策支持力度"],
    rows: [
      ["IC 设计（Logic）", "15-20%", "CPU/GPU/EDA 工具链生态", "强，科创板优先支持"],
      ["晶圆代工（成熟）", "15-20%", "设备交付能力限制", "强，大基金重点投入"],
      ["半导体设备", "10-15%", "刻蚀/薄膜/检测/离子注入差距", "强，大基金二期重点"],
      ["半导体材料", "20-25%", "大硅片/光刻胶纯度", "中等"],
      ["先进封装", "25-30%", "2.5D/3D 封装良率与经验", "中等"],
    ],
    sourceIds: ["S-SEMI-EMP2024"],
  },
  {
    type: "compareTable",
    caption: "核心设备国产化替代对比（内部分析）",
    headers: ["设备类别", "国内代表厂商", "全球龙头", "差距评估"],
    rows: [
      ["等离子体刻蚀", "中微公司 / 北方华创", "Lam Research / TEL", "差距 2-3 代"],
      ["薄膜沉积", "北方华创", "Applied Materials / Lam", "差距 3 代"],
      ["CMP 平坦化", "安集科技（材料）", "Applied Materials / Ebara", "接近国际水平"],
    ],
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证事项：1) 国产先进制程 2025-2026 年实际量产进展；2) EUV 光刻机出口政策变化；3) 国产 EDA 工具在先进节点的实际成功率。（待验证）",
    sourceIds: ["S-SEMI-MIIT-POLICY"],
  },
  {
    type: "callout",
    tone: "warning",
    text: "反证与失效条件：如果美日荷设备出口管制进一步收紧超出预期，或国产设备良率持续低于预期，国产替代进程将被推迟。（分析推断）",
    sourceIds: ["S-SEMI-NAURA-FILING", "S-SEMI-AMEC-FILING"],
  },
  {
    type: "risk",
    items: [
      "出口管制升级风险：实体清单范围持续扩大。",
      "先进制程突破不确定性风险：7nm 以下攻关需要长期积累。",
      "产能利用率周期波动风险：全球半导体下行周期影响成熟制程需求。",
    ],
    sourceIds: ["S-SEMI-SMIC-FILING", "S-SEMI-EMP2024"],
  },
];
