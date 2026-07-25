import type { ContentBlock } from "../types.ts";

export const integrationBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "储能系统集成是将电池簇、PCS、BMS、EMS、热管理与消防系统整合为完整储能系统的工程能力。系统集成商需具备电力电子技术、项目管理能力与电网级安全认证。阳光电源、比亚迪、科华数据在系统集成领域具备领先优势。",
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-BYD-FILING"],
  },
  {
    type: "table",
    caption: "储能系统集成关键环节与核心能力",
    headers: ["环节", "核心设备", "关键指标", "能力要求"],
    rows: [
      ["电池簇", "电芯/模组/Pack", "循环寿命、一致性、成本", "电芯选型与成组技术"],
      ["储能PCS", "变流器/控制柜", "转换效率、电网适应性", "电力电子与控制算法"],
      ["BMS", "电池管理系统", "采样精度、均衡控制、故障诊断", "电池建模与算法"],
      ["EMS", "能量管理系统", "调度策略、收益优化", "电网调度与电力市场"],
      ["热管理", "空调/液冷/风冷", "温控精度、能耗", "热力学与流体设计"],
      ["消防", "气体/水消防", "响应速度、灭火有效性", "安全认证与标准"],
    ],
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-CATL-FILING", "S-ESA-BYD-FILING"],
  },
  {
    type: "bullets",
    items: [
      "阳光电源：PowerTian系列储能系统全球出货量领先，集成PCS、电池与EMS一体化交付（公司口径）。",
      "比亚迪：Cube系列储能系统搭载刀片电池，系统级安全认证与项目交付能力（公司口径）。",
      "科士达：储能系统与数据中心协同发展，海外户储与大型储能项目双轮驱动（公司口径）。",
      "独立储能/共享储能模式：2024年独立储能电站收益模式逐步清晰，容量租赁+现货市场+容量补偿。",
    ],
    sourceIds: ["S-ESA-SUNGROW-FILING", "S-ESA-BYD-FILING", "S-ESA-KSTAR-FILING", "S-ESA-CNESA-DATA"],
  },
];
