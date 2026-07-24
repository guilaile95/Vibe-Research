import type { ContentBlock } from "../types.ts";

export const riskBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "warning",
    text: "反证与失效条件区：如果全铜缆总线（如NVL72型机柜铜背板）在短距离 Scale-up 传输中进一步扩大替代范围，挤压短距光模块使用量；或者 CPO 技术门槛过高导致良率低迷与维护成本过昂，商业化时点被长期推迟。",
    sourceIds: ["S-CPO-OIF-CPO", "S-CPO-INNOTIGHT-FILING"],
  },
  {
    type: "paragraph",
    text: "仍待验证事项区：1) 2025年 1.6T 光模块在北美云巨头智算中心中的实际部署节奏；2) 硅光方案在 1.6T 时代的成本与良率优势相比传统 EML 方案是否确立。",
    sourceIds: ["S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING"],
  },
  {
    type: "risk",
    items: [
      "上游光芯片断供与进口依赖风险：部分高端 200G EML 光芯片及高性能 DSP 仍高度依赖海外单点供应商。",
      "技术路线竞争风险：LPO 与传统可插拔方案若在 1.6T 时代维持高性价比，可能延缓 CPO 产业链爆发时间。",
      "产品价格降幅超预期风险：光模块行业历来存在年降压力，若产能过剩可能压缩盈利空间。",
    ],
    sourceIds: ["S-CPO-OIF-CPO", "S-CPO-INNOTIGHT-FILING", "S-CPO-YUANJIE-FILING"],
  },
];
