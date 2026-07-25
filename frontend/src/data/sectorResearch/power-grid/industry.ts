import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "电网设备行业呈现「国网/南网集中招标、头部厂商寡头竞争」格局。一次设备领域特变电工、平高电气、思源电气等具备全电压等级与工程业绩；二次设备领域国电南瑞凭借技术积累与系统能力占据领先位置（公司口径/产业观察）。",
    sourceIds: [
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-TEBIAN-FILING",
      "S-POWERGRID-PINGGAO-FILING",
    ],
  },
  {
    type: "bullets",
    items: [
      "国电南瑞：电网自动化与继电保护优势显著，柔性直流控制保护与二次设备布局完整（公司口径）。",
      "许继电气：直流输电换流阀与控制保护核心供应商之一，深度参与特高压直流工程（公司口径）。",
      "特变电工：特高压变压器与输变电总包能力突出，并延伸新能源与海外工程（公司口径）。",
      "思源电气：二次设备与 SVG/电力电子协同，受益配网与新能源并网（公司口径）。",
      "平高电气：特高压 GIS 等开关设备主力供应商之一，覆盖高电压等级开关序列（公司口径）。",
      "四方股份：继电保护与变电站/配网自动化，是二次设备重要参与者（公司口径）。",
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
    type: "table",
    caption: "电网与特高压核心厂商竞争力矩阵（定性）",
    headers: ["厂商", "核心赛道", "技术/资质护城河", "观察要点", "事实/口径等级"],
    rows: [
      ["国电南瑞", "二次设备+自动化", "电网级认证与系统集成", "在手订单、柔直与数字化项目", "公司口径"],
      ["许继电气", "直流输电+保护", "换流阀与控制保护业绩", "特高压直流招标份额", "公司口径"],
      ["特变电工", "变压器+电缆+总包", "高压绝缘与工程总包", "主变中标与海外订单", "公司口径"],
      ["思源电气", "二次+SVG/电力电子", "源网荷储相关产品组合", "新能源并网与配网订单", "公司口径"],
      ["平高电气", "GIS 开关设备", "高电压开关全系列与试验能力", "特高压 GIS 招标", "公司口径"],
      ["四方股份", "保护与自动化", "二次设备产品与工程经验", "主站/保护中标结构", "公司口径"],
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
    caption: "央企系设备商 vs 民企设备商（定性）",
    headers: ["维度", "央企/电网系背景厂商", "民企设备商"],
    rows: [
      ["典型代表", "国电南瑞、许继电气、平高电气等", "思源电气等"],
      ["优势", "主网大项目业绩、系统资质、品牌信任", "响应快、电力电子与细分产品灵活"],
      ["约束", "机制与考核相对稳健", "特高压超大项目进入门槛更高"],
      ["更适配场景", "特高压、主站、核心保护", "配网、SVG、部分二次与出口"],
    ],
    sourceIds: [
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-SIYUAN-FILING",
      "S-POWERGRID-PINGGAO-FILING",
    ],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "研究抓手（内部分析）：跟踪「特高压核准与招标 → 主变/GIS/换流阀中标」与「配网/新能源并网招标 → 二次与 SVG/PCS」两条线索，比单一关注年度投资口号更可验证。",
    sourceIds: ["S-POWERGRID-NDRC", "S-POWERGRID-NEA-14TH-FIVE"],
  },
  {
    type: "risk",
    items: [
      "宏观经济与财政约束影响电网年度投资与工程核准节奏。",
      "集中招标降价压力可能削弱中小厂商与同质化产品利润。",
      "原材料价格波动冲击变压器、电缆等一次设备盈利。",
      "新能源外送通道建设不及预期，拖累特高压设备交付（分析推断）。",
      "出口市场面临认证、融资与地缘政治不确定性。",
    ],
    sourceIds: [
      "S-POWERGRID-NEA-14TH-FIVE",
      "S-POWERGRID-NDRC",
      "S-POWERGRID-GUODIAN-NANRUI-FILING",
      "S-POWERGRID-TEBIAN-FILING",
    ],
  },
];
