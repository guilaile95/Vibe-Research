import type { ContentBlock } from "../types.ts";

export const intelligenceBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "智能电网覆盖发—输—变—配—用全环节，目标是提升可观可测可控水平与新能源消纳能力。数字孪生、AI 巡检、智能调度与配电物联网是当前产业化较快的方向（公司口径/产业公开信息）。",
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NANRUI-IR"],
  },
  {
    type: "table",
    caption: "智能电网关键技术与应用场景",
    headers: ["技术领域", "核心能力", "应用场景", "代表厂商"],
    rows: [
      ["数字孪生电网", "全要素建模与仿真推演", "规划、调度、运维决策", "国电南瑞等"],
      ["AI 巡检", "图像识别、无人机/机器人巡检", "线路与变电站巡检", "国电南瑞等系统集成商"],
      ["智能调度", "源网荷储协同优化", "实时运行与日前/日内调度", "国电南瑞、四方股份"],
      ["配电物联网", "智能终端与边缘计算", "状态感知、故障定位、自愈", "国电南瑞、思源电气等"],
    ],
    sourceIds: [
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-SIYUAN-FILING",
      "S-POWERGRID-SIFANG-FILING",
    ],
  },
  {
    type: "bullets",
    items: [
      "EMS/DMS 等调度自动化系统是电网运行的「中枢」，对安全等级与工程业绩要求极高。",
      "用电信息采集与智能电表支撑负荷管理、需求响应与电力现货/零售交易数据基础。",
      "一二次融合与 DTU/FTU 推动配网自动化由试点走向规模化改造。",
      "AI 能力更多以「嵌入现有主站/终端」方式落地，而非独立颠覆式替换（分析推断）。",
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-NDRC", "S-POWERGRID-SIFANG-FILING"],
  },
  {
    type: "compareTable",
    caption: "主站软件 vs 终端硬件智能化路径",
    headers: ["维度", "主站/平台侧", "终端/边缘侧"],
    rows: [
      ["产品形态", "调度主站、云平台、数字孪生", "FTU/DTU、智能开关、巡检机器人"],
      ["壁垒", "算法、安全认证、存量系统替换成本", "可靠性、通信协议、规模制造"],
      ["采购特征", "系统集成项目、周期长", "集中招标+批量交付"],
      ["代表能力", "国电南瑞等自动化龙头", "二次设备与一次融合厂商"],
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-NANRUI-IR"],
  },
  {
    type: "callout",
    tone: "info",
    text: "待验证事项：1) 电网数字化投资在总投资中的占比与年度节奏；2) 数字孪生从试点到省级主站规模化的进度；3) 虚拟电厂与需求侧响应的商业闭环是否稳定。",
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-NDRC"],
  },
  {
    type: "risk",
    items: [
      "信息安全与等保要求提高系统交付与运维成本。",
      "存量系统烟囱化导致互联互通与数据治理难度大。",
      "AI 巡检准确率与极端天气场景泛化能力仍需工程验证（分析推断）。",
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-NEA-14TH-FIVE"],
  },
];
