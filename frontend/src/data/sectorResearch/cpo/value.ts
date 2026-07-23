import type { ContentBlock } from "../types.ts";

export const valueBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "光模块 BOM 分布：芯片成本（DSP与光芯片）占比超过半数，高可靠性耦合与封测为主要价值壁垒。",
    sourceIds: ["S-CPO-INNOTIGHT-FILING"],
  },
  {
    type: "paragraph",
    text: "在 800G/1.6T 光模块内部，光芯片（EML/硅光）与 DSP 电子芯片占据单模块 BOM 成本的 60% 以上；光包封、FA光纤阵列及精密无源元件占比约为 15%~20%。",
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-TFC-FILING"],
  },
  {
    type: "table",
    caption: "800G / 1.6T 光模块单模块 BOM 成本结构拆解",
    headers: ["BOM 组成", "价值占比", "核心性能驱动因素", "代表供应商"],
    rows: [
      ["DSP / 电芯片", "30% ~ 35%", "5nm/4nm 先进制程 DSP、SerDes 速率", "海外主芯片商"],
      ["光芯片 (EML/CW光源)", "25% ~ 30%", "200G 单通道 EML、CW 大功率光源", "源杰科技、光迅科技"],
      ["无源器件与光引擎组装", "15% ~ 20%", "高精度微透镜、FA光纤阵列、隔离器", "天孚通信"],
      ["PCB与结构件", "8% ~ 10%", "高频多层PCB、散热外壳与精密连接器", "相关PCB/结构件厂商"],
      ["封装测试与人工", "10% ~ 12%", "自动化贴片、耦合与高低温老化测试", "中际旭创、新易盛"],
    ],
    sourceIds: ["S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING", "S-CPO-TFC-FILING", "S-CPO-YUANJIE-FILING"],
  },
];
