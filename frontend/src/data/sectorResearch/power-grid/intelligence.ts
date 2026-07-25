import type { ContentBlock } from "../types.ts";

export const intelligenceBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "智能电网是电网数字化转型的核心方向，涵盖发电、输电、变电、配电、用电全环节。数字孪生、AI巡检、智能调度等技术加速落地，提升电网运行效率与新能源消纳能力。",
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-SGCC-PLAN"],
  },
  {
    type: "table",
    caption: "智能电网关键技术与应用场景",
    headers: ["技术领域", "核心能力", "应用场景", "代表厂商"],
    rows: [
      ["数字孪生电网", "电网全要素建模与仿真", "规划、调度、运维决策", "国电南瑞、朗新科技"],
      ["AI巡检", "图像识别、无人机/机器人巡检", "输电线路与变电站巡检", "国电南瑞、亿嘉和"],
      ["智能调度", "源网荷储协同优化调度", "电网实时运行控制", "国电南瑞、四方股份"],
      ["配电物联网", "智能终端与边缘计算", "配电网状态感知与故障定位", "国电南瑞、炬华科技"],
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-SIYUAN-FILING"],
  },
  {
    type: "bullets",
    items: [
      "电网调度自动化系统（EMS/DMS）是电网运行的「大脑」，国电南瑞占据主导地位。",
      "智能电表与用电信息采集系统实现用电侧数据回传与负荷管理。",
      "一二次设备融合与智能终端（DTU/FTU）推动配网自动化向纵深发展。",
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-SGCC-PLAN"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证事项：1) 电网投资年度规模与节奏；2) 柔性直流与数字孪生技术大规模商用进展；3) 分布式能源与虚拟电厂商业化闭环。",
    sourceIds: ["S-POWERGRID-SGCC-PLAN", "S-POWERGRID-NEA-14TH-FIVE"],
  },
];
