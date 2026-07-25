import type { ContentBlock } from "../types.ts";

export const transmissionBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "输配电设备是电网工程的基础硬件层，分为一次设备（直接参与电能传输与分配）和二次设备（监测、控制与保护）。在新型电力系统建设下，输配电设备向智能化、模块化与高可靠性方向升级。",
    sourceIds: ["S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-SIYUAN-FILING"],
  },
  {
    type: "table",
    caption: "输配电一次设备与二次设备分类及代表厂商",
    headers: ["设备类别", "核心产品", "功能定位", "代表A股厂商"],
    rows: [
      ["开关设备", "GIS、断路器、负荷开关", "开断与隔离故障电流", "平高电气、思源电气"],
      ["变压器", "电力变压器、换流变压器", "电压变换与电能传输", "特变电工、思源电气"],
      ["电缆与附件", "高压电缆、海底电缆", "电能传输通道", "特变电工、远东股份"],
      ["继电保护", "线路保护、母线保护", "故障检测与快速隔离", "国电南瑞、许继电气"],
      ["自动化系统", "调度自动化、变电站自动化", "电网运行监控与优化", "国电南瑞、四方股份"],
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-PINGGAO-FILING", "S-POWERGRID-SIYUAN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "一二次设备融合：将传感器、智能终端集成到一次设备中，实现状态监测与智能运维。",
      "配电网升级：分布式光伏与充电桩大规模接入，推动配网自动化与智能台区改造。",
      "设备标准化：国网与南网推行标准化设计与集中招标，头部厂商规模效应显著。",
    ],
    sourceIds: ["S-POWERGRID-SGCC-PLAN", "S-POWERGRID-SIYUAN-FILING"],
  },
];
