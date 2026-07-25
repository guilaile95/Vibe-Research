import type { ContentBlock } from "../types.ts";

export const newEnergyBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "新能源大基地外送需求刚性：「十四五」规划明确建设9大清洁能源基地，通过特高压通道实现跨区消纳。新能源高比例接入对电网稳定性与调峰能力提出更高要求（能源局口径）。",
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-SGCC-PLAN"],
  },
  {
    type: "paragraph",
    text: "风电与光伏的波动性与间歇性，使得新能源接入成为电网升级的关键驱动力。SVG、储能变换器、虚拟同步机等电能质量与惯量支撑设备需求快速增长。",
    sourceIds: ["S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-GUODIAN-NANRUI-FILING"],
  },
  {
    type: "compareTable",
    caption: "新能源接入关键设备与功能对比",
    headers: ["设备类型", "核心功能", "应用场景", "代表厂商"],
    rows: [
      ["SVG/STATCOM", "无功补偿与电压稳定", "风电场/光伏电站并网", "思源电气、国电南瑞"],
      ["储能变流器(PCS)", "交直流转换与充放电控制", "发电侧/电网侧储能", "阳光电源、思源电气"],
      ["虚拟同步机(VSG)", "模拟同步发电机惯量响应", "高比例新能源电网", "国电南瑞、许继电气"],
      ["柔性直流组网", "多端直流与灵活功率控制", "海上风电并网、孤岛供电", "许继电气、国电南瑞"],
    ],
    sourceIds: ["S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING"],
  },
  {
    type: "bullets",
    items: [
      "分布式光伏大规模接入配电网，引发电压越限与逆功率问题，推动配网主动配电网改造。",
      "源网荷储一体化项目推动微电网与智能配用电系统需求增长。",
      "新能源强制配储政策驱动发电侧储能建设，配套PCS与EMS需求释放。",
    ],
    sourceIds: ["S-POWERGRID-SGCC-PLAN", "S-POWERGRID-NEA-14TH-FIVE"],
  },
];
