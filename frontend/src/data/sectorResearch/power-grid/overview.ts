import type { ContentBlock } from "../types.ts";

export const overviewBlocks: ContentBlock[] = [
  {
    type: "callout",
    tone: "info",
    text: "政策顶层方向：「十四五」现代能源体系与新型电力系统建设要求加快电网智能化改造、跨区输电通道与新能源大基地外送能力建设。电网投资由国网/南网等主体主导，设备侧招标节奏决定厂商订单释放（官方口径/产业公开信息）。",
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NDRC"],
  },
  {
    type: "paragraph",
    text: "电网与特高压板块覆盖输变电一次设备（变压器、开关、电缆）、二次设备（继电保护、调度/变电站自动化）以及柔性直流等核心装备。需求主线可拆为三条：跨区特高压外送、配网升级与新能源并网、数字化/智能化运维。三者叠加使行业从「周期投资」转向「结构升级 + 周期」双驱动（分析推断）。",
    sourceIds: [
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-NEA-14TH-FIVE",
    ],
  },
  {
    type: "bullets",
    items: [
      "特高压交流/直流：以 1000kV 交流与 ±800kV/±1100kV 直流为主，承担西电东送、北电南送与风光大基地外送。",
      "一次设备：GIS/断路器、电力变压器、换流变压器、组合电器、高压电缆等，技术门槛在绝缘、短路开断与长期可靠性。",
      "二次设备：继电保护、EMS/DMS、变电站自动化、配网 DTU/FTU；头部厂商具备电网级安全认证与工程经验。",
      "新能源接入配套：SVG/STATCOM、储能 PCS、柔性直流与虚拟同步等，用于电压稳定、惯量支撑与并网质量治理。",
      "智能化：一二次融合、智能巡检、数字孪生与源网荷储协同调度，提升运行效率与消纳能力（公司口径/产业趋势）。",
    ],
    sourceIds: [
      "S-POWERGRID-XUJI-FILING",
      "S-POWERGRID-SIYUAN-FILING",
      "S-POWERGRID-PINGGAO-FILING",
      "S-POWERGRID-NANRUI-IR",
    ],
  },
  {
    type: "table",
    caption: "电网与特高压核心子领域与代表厂商映射",
    headers: ["子领域", "核心产品", "技术门槛与瓶颈", "代表A股厂商", "事实/口径等级"],
    rows: [
      [
        "特高压一次设备",
        "GIS、变压器、组合电器",
        "绝缘设计、开断能力、长期可靠性",
        "平高电气、特变电工、思源电气",
        "公司口径（中标/披露）",
      ],
      [
        "特高压二次/控制保护",
        "继电保护、自动化、直流控制保护",
        "电网级安全认证、实时性、协议兼容",
        "国电南瑞、许继电气、四方股份",
        "公司口径",
      ],
      [
        "直流输电",
        "换流阀、换流变、控制保护",
        "大功率电力电子、高压绝缘、控制算法",
        "许继电气、国电南瑞、特变电工",
        "公司口径",
      ],
      [
        "配网与电能质量",
        "智能开关、DTU/FTU、SVG",
        "一二次融合、边缘计算、并网标准",
        "思源电气、国电南瑞、四方股份",
        "公司口径",
      ],
    ],
    sourceIds: [
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-XUJI-FILING",
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-SIYUAN-FILING",
      "S-POWERGRID-PINGGAO-FILING",
      "S-POWERGRID-SIFANG-FILING",
    ],
  },
  {
    type: "compareTable",
    caption: "主网特高压 vs 配网智能化 — 投资与受益结构对比（定性）",
    headers: ["维度", "主网/特高压", "配网智能化与新能源接入"],
    rows: [
      ["需求驱动", "大基地外送、跨区互济、通道核准", "分布式光伏/充电桩、台区改造、电能质量"],
      ["招标主体", "国网/南网总部及省级公司集中招标", "省级/地市公司 + 新能源业主"],
      ["单笔金额", "单工程设备金额大、节奏强", "项目分散、频次高"],
      ["核心受益环节", "GIS/变压器/换流阀/控制保护", "二次设备、SVG、PCS、智能终端"],
      ["周期特征", "核准—招标—交付链条较长", "与新能源装机及配网改造更同步"],
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NDRC", "S-POWERGRID-SIYUAN-FILING"],
  },
  {
    type: "risk",
    items: [
      "电网投资与工程核准节奏受宏观与财政约束，年度招标量可能波动。",
      "集中招标模式下价格竞争可能压制一次/二次设备毛利率。",
      "铜、取向硅钢等原材料价格波动直接影响变压器与电缆盈利。",
      "风光大基地外送通道若核准或建设滞后，将延后特高压设备交付节奏（分析推断）。",
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-GUODIAN-NANRUI-FILING"],
  },
];
