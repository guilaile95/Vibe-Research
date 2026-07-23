import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "COBO 行业标准定义：CPO（Co-Packaged Optics，共封装光学）是将交换芯片（Switch ASIC）与硅光引擎（Optical Engine）共同封装在同一个高密度基板上的物理架构，旨在将功耗降低30%以上，解决 51.2T/102.4T 交换机端口的功耗瓶颈。",
    sourceIds: ["S-CPO-OIF-CPO"],
  },
  {
    type: "paragraph",
    text: "在 AI 智算集群中，光互联正经历从传统可插拔光模块（Pluggable Transceivers）向 LPO（线性驱动可插拔）与 CPO（共封装光学）的并行演进。中际旭创、新易盛、天孚通信等本土厂商在 800G/1.6T 时代占据全球重要份额。",
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING"],
  },
  {
    type: "bullets",
    items: [
      "光模块龙头：中际旭创、新易盛在 800G 传统与硅光模块大批量交付上具备领先地位（公司口径）。",
      "光器件平台：天孚通信在 CPO 光引擎组件、FA 光纤阵列与精密无源器件上实现深度绑定（公司口径）。",
      "光芯片突破：源杰科技推进 100G EML 及大功率 CW 激光器芯片自研（公司口径）。",
      "硅光与CPO研发：华工科技、光迅科技具备硅光芯片与 800G/1.6T 模块出货能力（公司口径）。",
    ],
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING", "S-CPO-YUANJIE-FILING", "S-CPO-ACCELINK-FILING", "S-CPO-HGTECH-FILING"],
  },
  {
    type: "table",
    caption: "光互联核心环节与代表 A 股厂商映射表",
    headers: ["环节", "核心产品/技术", "关键指标/门槛", "代表 A 股厂商", "事实/口径等级"],
    rows: [
      ["高速光模块", "800G / 1.6T OSFP/QSFP-DD 光模块", "DSP功耗控制、眼图张开度、高良率组装", "中际旭创、新易盛、华工科技", "公司口径（大批量出货）"],
      ["光引擎与无源器件", "CPO光引擎、FA光纤阵列、微型透镜", "亚微米级对准精度、高插拔耐久度", "天孚通信", "公司口径（量产送样）"],
      ["高速光芯片", "100G/200G EML、CW 大功率激光器", "高温稳定性、单模输出功率、芯片良率", "源杰科技、光迅科技", "公司口径（送样研发）"],
      ["硅光集成方案", "硅光调制器芯片与集成光路", "插损(Insertion Loss)控制、CMOS工艺兼容", "中际旭创、华工科技、光迅科技", "公司口径（产品交付）"],
    ],
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING", "S-CPO-YUANJIE-FILING", "S-CPO-ACCELINK-FILING", "S-CPO-HGTECH-FILING"],
  },
];
