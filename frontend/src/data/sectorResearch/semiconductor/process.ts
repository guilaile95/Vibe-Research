import type { ContentBlock } from "../types.ts";

export const processBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "晶圆制造（前道）核心工序包括光刻、刻蚀、薄膜沉积、离子注入与化学机械平坦化（CMP）等。设备侧，刻蚀机、薄膜沉积设备与检测/量测系统构成资本开支重点；材料侧，抛光液、特种气体与湿电子化学品随产能持续消耗。",
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-NAURA-SITE",
      "S-SEMI-AMEC-SITE",
    ],
  },
  {
    type: "bullets",
    items: [
      "光刻：将电路图形转移到晶圆；极紫外（EUV）光刻是先进节点的关键瓶颈之一，受出口管制约束。",
      "刻蚀：电容耦合（CCP）/ 电感耦合（ICP）等等离子体刻蚀用于高深宽比结构；中微、北方华创均有相关产品披露。",
      "薄膜沉积：化学气相沉积（CVD）、物理气相沉积（PVD）、原子层沉积（ALD）用于多层薄膜堆叠。",
      "CMP：铜互连等平坦化工艺依赖抛光液与垫等材料；安集科技年报披露先进节点验证进展。",
    ],
    sourceIds: [
      "S-SEMI-NAURA-FILING",
      "S-SEMI-AMEC-FILING",
      "S-SEMI-ANJI-FILING",
      "S-SEMI-AMEC-SITE",
      "S-SEMI-NAURA-SITE",
    ],
  },
  {
    type: "table",
    caption: "前道关键工序与国内披露映射（公司口径）",
    headers: ["工序", "关键设备 / 材料", "国内代表披露", "备注"],
    rows: [
      ["刻蚀", "CCP / ICP 刻蚀机", "中微公司、北方华创", "逻辑 / 存储工艺应用披露"],
      ["薄膜沉积", "CVD / PVD / ALD", "北方华创等", "产品线覆盖前道薄膜"],
      ["CMP", "抛光液等湿化学品", "安集科技", "14nm 以下验证与导入"],
      ["代工整合", "全流程工艺平台", "中芯国际", "成熟制程量产为主"],
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
    text: "待验证：国产刻蚀在更先进节点的稳定量产表现、ALD 在高介电常数（High-k）产线的长期可靠性，均需客户侧与后续财报交叉验证，不宜由单次年报外推。",
    sourceIds: ["S-SEMI-AMEC-FILING", "S-SEMI-NAURA-FILING"],
  },
  {
    type: "risk",
    items: [
      "EUV 等高端光刻设备仍受出口管制，替代路线在吞吐量与成熟度上存在差距。",
      "设备与材料导入晶圆厂的验证周期通常长达 12–24 个月甚至更久。",
      "关键子系统、零部件与软件仍可能依赖进口，构成整机交付风险。",
    ],
    sourceIds: ["S-SEMI-AMEC-FILING", "S-SEMI-NAURA-FILING", "S-SEMI-SMIC-FILING"],
  },
];
