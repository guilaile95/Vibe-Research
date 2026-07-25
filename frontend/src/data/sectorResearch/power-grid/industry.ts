import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "电网设备行业呈现「国网/南网集中招标、头部厂商寡头竞争」格局。一次设备领域特变电工、平高电气、思源电气占据主导；二次设备领域国电南瑞凭借技术积累与国网背景占据绝对领先。",
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-PINGGAO-FILING"],
  },
  {
    type: "bullets",
    items: [
      "国电南瑞：电网自动化与继电保护领域市占率第一，柔性直流控制保护系统技术领先（公司口径）。",
      "许继电气：直流输电换流阀与控制保护系统核心供应商，特高压工程主要中标方（公司口径）。",
      "特变电工：特高压变压器龙头，海外输变电总包业务持续拓展（公司口径）。",
      "思源电气：电网二次设备与SVG/储能变换器同步增长，在手订单饱满（公司口径）。",
      "平高电气：特高压GIS开关设备主力供应商，产品线覆盖72.5-1100kV全电压等级（公司口径）。",
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-PINGGAO-FILING"],
  },
  {
    type: "table",
    caption: "电网与特高压核心厂商竞争力矩阵",
    headers: ["厂商", "核心赛道", "技术护城河", "在手订单/中标增速", "事实/口径等级"],
    rows: [
      ["国电南瑞", "二次设备+自动化", "电网级安全认证与国网背景", "双位数增长", "公司口径（年报披露）"],
      ["许继电气", "直流输电+保护", "换流阀与控制保护技术", "双位数增长", "公司口径（年报披露）"],
      ["特变电工", "变压器+电缆", "高压绝缘与总包能力", "双位数增长", "公司口径（年报披露）"],
      ["思源电气", "二次设备+SVG", "源网荷储全产品线", "双位数增长", "公司口径（年报披露）"],
      ["平高电气", "GIS开关设备", "高压开关全系列覆盖", "双位数增长", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-POWERGRID-GUODIAN-NANRUI-FILING", "S-POWERGRID-XUJI-FILING", "S-POWERGRID-TEBIAN-FILING", "S-POWERGRID-SIYUAN-FILING", "S-POWERGRID-PINGGAO-FILING"],
  },
  {
    type: "risk",
    items: [
      "电网投资节奏风险：宏观经济波动可能影响电网年度投资规模与工程核准节奏。",
      "集中招标降价压力：国网南网集中招标模式下，价格竞争可能压缩厂商利润率。",
      "原材料价格波动：铜、钢、硅钢等原材料价格波动影响变压器与电缆业务的盈利能力。",
      "新能源外送通道建设不及预期：若风光大基地外送通道核准或建设进度滞后，影响设备交付节奏。",
    ],
    sourceIds: ["S-POWERGRID-NEA-14TH-FIVE", "S-POWERGRID-SGCC-PLAN", "S-POWERGRID-GUODIAN-NANRUI-FILING"],
  },
];
