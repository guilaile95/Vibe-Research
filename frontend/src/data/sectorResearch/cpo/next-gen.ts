import type { ContentBlock } from "../types.ts";

export const nextGenBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "端口速率演进：从单通道 100G 向 200G PAM4 跨越，1.6T 成为了 2024-2025 年算力网络数据中心建设的新焦点。",
    sourceIds: ["S-CPO-INNOTIGHT-FILING"],
  },
  {
    type: "paragraph",
    text: "光互联正从单通道 100G 向单通道 200G 跨越，带动 1.6T 光模块成为下一代算力网络竞争焦点。在 3.2T 节点，CPO 被视为解决板间高密度光电转换与功耗极限的必然趋势。",
    sourceIds: ["S-CPO-COBO-WHITEPAPER", "S-CPO-INNOTIGHT-FILING"],
  },
  {
    type: "compareTable",
    caption: "光模块代景演进（400G -> 800G -> 1.6T -> 3.2T CPO）",
    headers: ["速率代际", "单通道 SerDes", "典型物理接口", "主要封装形态", "商业化落地时间"],
    rows: [
      ["400G", "50G PAM4", "8 通道 * 50G", "OSFP / QSFP-DD", "已大规模普及"],
      ["800G", "100G PAM4", "8 通道 * 100G", "OSFP / QSFP-DD", "2023-2024年大规模量产"],
      ["1.6T", "200G PAM4", "8 通道 * 200G", "OSFP-1600", "2024-2025年上量交付"],
      ["3.2T (CPO)", "200G / 400G", "基板级多通道集成", "CPO 共封装架构", "预估 2026+ 随着 1024卡机柜引入"],
    ],
    sourceIds: ["S-CPO-COBO-WHITEPAPER", "S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING"],
  },
];
