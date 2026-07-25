import type { ContentBlock } from "../types.ts";

export const opticsBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "光电共封演进路径：传统可插拔模块满足 800G/1.6T 需求，LPO 降功耗，CPO 为 3.2T 以上节点提供物理终极方案。",
    sourceIds: ["S-CPO-OIF-CPO"],
  },
  {
    type: "paragraph",
    text: "光互联的技术演进围绕‘降低每Bit传输功耗与延时’展开。传统光模块依赖 DSP（数字信号处理器）再定时，而 LPO 去除 DSP 改用电芯片均衡，CPO 则进一步将光引擎与交换芯片贴合。",
    sourceIds: ["S-CPO-OIF-CPO", "S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING"],
  },
  {
    type: "compareTable",
    caption: "传统可插拔光模块 vs LPO vs CPO 技术路线对比",
    headers: ["方案路线", "物理形态", "功耗与延时", "热插拔与维护性", "成熟度与商业化进度"],
    rows: [
      ["传统可插拔 (DSP)", "独立模块插在交换机面板", "基准 (约25-30W/1.6T)", "极佳 (支持热插拔与独立更换)", "商业化成熟 (800G 主力出货)"],
      ["LPO (线性驱动)", "独立模块，去除 DSP 芯片", "功耗降低 40%，延时极低", "良好 (保持可插拔形态)", "小规模试部署 (需交换芯片匹配)"],
      ["CPO (共封装光学)", "硅光引擎与交换芯片共封装", "功耗降低 >30%，传输损耗极小", "较差 (需外置激光器ELSFP实现热插拔)", "研发与前期测试阶段 (预估1.6T/3.2T阶段)"],
    ],
    sourceIds: ["S-CPO-OIF-CPO", "S-CPO-INNOTIGHT-FILING", "S-CPO-EOPTOLINK-FILING"],
  },
  {
    type: "bullets",
    items: [
      "硅光技术（Silicon Photonics）：利用标准 CMOS 晶圆工艺制造光波导与调制器，显著降低多通道光芯片成本与体积。",
      "外置激光器（ELSFP）：由于 CPO 内部发热剧烈，III-V 族激光器易高温衰退，因此必须采用外置模块化光源设计。",
    ],
    sourceIds: ["S-CPO-OIF-CPO", "S-CPO-YUANJIE-FILING"],
  },
];
