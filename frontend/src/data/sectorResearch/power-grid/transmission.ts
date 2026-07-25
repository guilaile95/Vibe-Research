import type { ContentBlock } from "../types.ts";

export const transmissionBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "输配电设备是电网工程的硬件基础层：一次设备直接参与电能传输与分配，二次设备负责监测、控制与保护。新型电力系统下，设备向智能化、模块化、一二次融合与高可靠性升级。",
    sourceIds: ["S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-NANRUI-IR"],
  },
  {
    type: "table",
    caption: "输配电一次设备与二次设备分类及代表厂商",
    headers: ["设备类别", "核心产品", "功能定位", "代表A股厂商"],
    rows: [
      ["开关设备", "GIS、断路器、负荷开关", "开断与隔离故障电流", "平高电气、思源电气"],
      ["变压器", "电力变压器、换流变压器", "电压变换与电能传输", "特变电工、思源电气"],
      ["电缆与附件", "高压电缆、海底电缆", "电能传输通道", "特变电工等"],
      ["继电保护", "线路/母线/主变保护", "故障检测与快速隔离", "国电南瑞、许继电气、四方股份"],
      ["自动化系统", "调度自动化、变电站自动化", "运行监控与优化", "国电南瑞、四方股份"],
    ],
    sourceIds: [
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-XUJI-FILING",
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-PINGGAO-FILING",
      "S-POWERGRID-SIYUAN-FILING",
      "S-POWERGRID-SIFANG-FILING",
    ],
  },
  {
    type: "bullets",
    items: [
      "一二次设备融合：传感器与智能终端嵌入一次设备，支撑状态监测与智能运维。",
      "配电网升级：分布式光伏与充电桩接入推动主动配电网、智能台区与故障自愈改造。",
      "标准化与集中招标：国网/南网标准化设计强化头部厂商规模与认证优势，中小厂商承压（分析推断）。",
      "海外市场：部分输变电企业通过总包与装备出口平滑国内招标波动（公司口径）。",
    ],
    sourceIds: ["S-POWERGRID-NDRC", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-TEBIAN-IR"],
  },
  {
    type: "compareTable",
    caption: "一次设备 vs 二次设备竞争要素（定性）",
    headers: ["维度", "一次设备", "二次设备"],
    rows: [
      ["核心壁垒", "制造工艺、材料、试验能力、工程业绩", "算法/软件、安全认证、协议与系统集成"],
      ["资本开支", "较高（厂房、试验站、材料）", "相对较低，研发与工程人员密集"],
      ["客户黏性", "招标+业绩门槛", "系统替换成本高、长期运维绑定"],
      ["代表厂商", "特变电工、平高电气、思源电气", "国电南瑞、许继电气、四方股份"],
    ],
    sourceIds: [
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-PINGGAO-FILING",
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-SIFANG-FILING",
    ],
  },
  {
    type: "callout",
    tone: "warning",
    text: "数据质量提示：具体中标份额、毛利率与在手订单金额须以各公司最新年报/半年报及电网招标公告为准；本页不做未经交叉验证的份额排序断言。",
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-TEBIAN-FILING"],
  },
  {
    type: "risk",
    items: [
      "招标降价与低价中标策略压缩设备商利润。",
      "铜、钢、绝缘材料成本波动对一次设备影响更大。",
      "配网项目碎片化导致回款与交付管理复杂度上升。",
    ],
    sourceIds: ["S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-TEBIAN-FILING"],
  },
];
