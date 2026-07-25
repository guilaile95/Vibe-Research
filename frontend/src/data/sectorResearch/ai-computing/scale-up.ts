import type { ContentBlock } from "../types.ts";

export const scaleUpBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "域内与域外拓扑选择：NVLink 机柜主要用于 72 卡 GPU 域内超高速内存共享，而 800G 光模块主要用于跨机柜 Spine-Leaf 拓扑构建集群。",
    sourceIds: ["S-AICOMP-FII-FILING"],
  },
  {
    type: "paragraph",
    text: "Scale-up（域内扩展）旨在通过超高带宽背板与铜缆/光纤总线将数十颗GPU组合为单块‘逻辑巨大芯片’；而 Scale-out（域外横向扩展）通过 Spine-Leaf 网络将数以万计的算力节点连接成集群。",
    sourceIds: ["S-AICOMP-UNIS-FILING", "S-AICOMP-FII-FILING"],
  },
  {
    type: "compareTable",
    caption: "Scale-up 域内扩展 vs Scale-out 域外扩展对比",
    headers: ["维度", "Scale-up (机柜/域内)", "Scale-out (集群/域外)", "核心物理媒介"],
    rows: [
      ["通信范围", "单机柜/72卡域内", "千卡/万卡集群间", "背板铜缆 vs 光纤+光模块"],
      ["单通道带宽", "900GB/s - 1.8TB/s (双向)", "400Gbps - 800Gbps (端口)", "NVLink/专用总线 vs RoCEv2/IB"],
      ["技术痛点", "信号衰减、背板高密度冲压与铜缆弯折", "网络拥塞、多级交换机跳数延时", "高速铜背板 vs 800G/1.6T 光模块"],
    ],
    sourceIds: ["S-AICOMP-UNIS-FILING", "S-AICOMP-FII-FILING", "S-AICOMP-INSPUR-FILING"],
  },
];
