import type { ContentBlock } from "../types.ts";

export const newEnergyBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "新能源高比例接入是电网升级的硬约束：风光出力波动要求更强的电压支撑、调峰与惯量能力；大基地外送依赖特高压通道，分布式则倒逼配网主动化改造（官方口径/产业共识）。",
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NDRC"],
  },
  {
    type: "paragraph",
    text: "风电与光伏的间歇性使 SVG/STATCOM、储能变流器（PCS）、柔性直流与虚拟同步等设备成为并网刚需。政策端强制配储、市场化辅助服务与源网荷储一体化，共同打开发电侧与电网侧设备市场（分析推断）。",
    sourceIds: ["S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING"],
  },
  {
    type: "compareTable",
    caption: "新能源接入关键设备与功能对比",
    headers: ["设备类型", "核心功能", "应用场景", "代表厂商"],
    rows: [
      ["SVG/STATCOM", "无功补偿与电压稳定", "风电场/光伏电站并网点", "思源电气、国电南瑞"],
      ["储能变流器(PCS)", "交直流转换与充放电控制", "发电侧/电网侧/工商业储能", "阳光电源等（跨板块）、思源电气"],
      ["虚拟同步(VSG)相关", "模拟同步机惯量/阻尼", "高比例新能源电网", "国电南瑞、许继电气"],
      ["柔性直流", "多端直流与灵活功率控制", "海上风电并网、孤岛/多端互联", "许继电气、国电南瑞"],
    ],
    sourceIds: [
      "S-POWERGRID-SIYUAN-FILING",
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-XUJI-FILING",
      "S-POWERGRID-SIYUAN-IR",
    ],
  },
  {
    type: "bullets",
    items: [
      "分布式光伏大规模接入易引发电压越限与逆功率，推动配网自动化、有载调压与智能台区改造。",
      "源网荷储一体化与微电网提升本地消纳，带动边缘 EMS、保护与计量升级。",
      "新能源配储政策与容量电价/辅助服务机制影响储能与 PCS 的经济性与建设节奏（分析推断）。",
      "海上风电柔直送出是技术与价值量双高场景，认证与工程经验门槛显著高于陆上常规并网。",
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NDRC", "S-POWERGRID-SIYUAN-FILING"],
  },
  {
    type: "table",
    caption: "发电侧 / 电网侧 / 用户侧接入需求差异（定性）",
    headers: ["侧别", "主要痛点", "典型设备/系统", "商业模式特征"],
    rows: [
      ["发电侧", "并网电压/谐波、配储要求", "SVG、PCS、升压站设备", "与电站投资同步，业主招标"],
      ["电网侧", "调峰调频、阻塞、安全稳定", "独立储能、柔直、控制保护", "电网投资与辅助服务驱动"],
      ["用户侧", "电费管理、备电、需量控制", "工商业储能、智能配电", "项目分散，更重 ROI"],
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-GUODIAN-NANRUI-FILING"],
  },
  {
    type: "risk",
    items: [
      "新能源装机与外送通道建设不同步，导致弃风弃光或设备需求错配。",
      "配储与辅助服务规则变化可能改变储能与电能质量设备的投资回报。",
      "并网技术标准升级提高认证成本，中小设备商面临出清压力（分析推断）。",
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-SIYUAN-FILING"],
  },
];
