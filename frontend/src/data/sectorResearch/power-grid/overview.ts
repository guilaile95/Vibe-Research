import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层目标：《\u201c十四五\u201d现代能源体系规划》明确加快电网基础设施智能化改造和智能微电网建设，提高电力系统互补互济和智能调节能力。国家电网2024年度电网投资规模超6000亿元，特高压与智能化改造投入显著提升。",
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-SGCC-PLAN"],
  },
  {
    type: "paragraph",
    text: "电网与特高压板块涵盖输变电一次设备（变压器、开关、电缆）、二次设备（继电保护、自动化系统）以及柔性直流输电核心装备。在新型电力系统建设背景下，新能源大基地外送、分布式智能电网与储能接入共同驱动输配电设备需求结构性增长。",
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-TEBIAN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "特高压交流/直流：以±800kV/±1100kV直流与1000kV交流为主，承担西电东送、北电南送跨区域大容量输电功能。",
      "输配电设备：涵盖GIS开关、变压器、组合电器、互感器等一次设备，以及电网调度自动化、变电站自动化等二次设备。",
      "新能源接入：风电/光伏大基地通过特高压外送通道并网，配电网需加装SVG、储能变换器等电能质量治理装置。",
      "智能化升级：一二次设备融合、智能巡检机器人、数字孪生电网等技术加速落地。",
    ],
    sourceIds: ["S-POWERGRID-XUJI-FILING", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-PINGGAO-FILING"],
  },
  {
    type: "table",
    caption: "电网与特高压板块核心子领域与代表厂商映射表",
    headers: ["子领域", "核心产品", "技术门槛与瓶颈", "代表A股厂商", "事实/口径等级"],
    rows: [
      ["特高压一次设备", "GIS开关、变压器、组合电器", "绝缘设计、短路开断能力、长期可靠性", "平高电气、特变电工、思源电气", "公司口径（中标/交付）"],
      ["特高压二次设备", "继电保护、自动化系统", "电网级安全认证、实时性、协议兼容", "国电南瑞、许继电气", "公司口径（中标/交付）"],
      ["直流输电", "换流阀、控制保护系统", "大功率半导体、高压绝缘、控制算法", "许继电气、国电南瑞", "公司口径（中标/交付）"],
      ["配网智能化", "智能开关、DTU/FTU、配电自动化", "一二次融合、通信协议、边缘计算", "思源电气、国电南瑞", "公司口径（在手订单）"],
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-PINGGAO-FILING"],
  },
];
