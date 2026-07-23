import type { ContentBlock } from "../types";

/** 定价权地图 Tag 内容块。 */
export const pricingPowerBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "定价权地图按三档划分——有定价权 / 半有定价权 / 无定价权——用于判断 PCB 产业链各环节在涨价周期中能否保留利润、紧缺结束后是否回吐、以及上下游成本能否转嫁。判断标准：(1) 涨价时能否保留利润；(2) 紧缺结束后是否回吐；(3) 上下游是否可以转嫁。以下为分析框架，非机构或公司官方披露。（分析推断）",
  },
  {
    type: "table",
    caption: "PCB 产业链定价权档位（分析推断；金额与涨价幅度尚无公开资料确认）",
    headers: ["环节", "定价权档位", "判断依据", "代表企业"],
    rows: [
      [
        "高端 CCL / 特种材料",
        "有定价权（推断）",
        "认证壁垒高、客户黏性强；紧缺结束后因认证周期长不易完全回吐；材料成本可部分向下转嫁",
        "生益科技（S-SHENGYI-HIGHSPEED / S-SHENGYI-RF / S-SHENGYI-IC）；日/美/台高端牌号手册未读"],
      [
        "一线板厂（高端 HDI / 载板 / 高速板）",
        "有定价权（推断）",
        "绑定大客户长单与技术认证；回吐相对有限",
        "其他一线板厂公告未读"],
      [
        "二线板厂（通用多层板）",
        "半有定价权（推断）",
        "涨价时部分保留但竞争侵蚀；紧缺结束后易回吐",
        "景旺电子（S-KINWONG-HLC / S-KINWONG-COMPUTING）等；具体档位依产品结构而异"],
      [
        "低端单双面 PCB",
        "无定价权（推断）",
        "同质化严重，涨价即丢单；上下游均难转嫁",
        "中小板厂（非上市主体为主）"]],
    sourceIds: ["S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC", "S-KINWONG-HLC", "S-KINWONG-COMPUTING"],
  },
  {
    type: "callout",
    tone: "info",
    text: "判断标准说明：(1) 保留利润 = 涨价幅度 > 成本涨幅；(2) 回吐 = 紧缺结束后价格回落至涨价前水平；(3) 转嫁 = 向上游压价或向下游提价的能力。三档划分基于分析框架，非公司官方口径；涨价幅度与时滞尚无公开资料确认。",
  },
  {
    type: "bullets",
    items: [
      "高端材料牌号扩产与认证进度（含生益科技等新增产能释放节奏）",
      "材料涨价函落地情况（CCL / 玻纤布 / 树脂厂商公开涨价函与实际成交价差）",
      "板厂毛利率季度变化（需读取年报/中报正文后更新）",
      "下一代中板（Midplane）量产节奏（客户验证与良率节点）",
      "后续应用 a-stock-data / 巨潮拉取具体公告与研报正文后再升级 sourceIds"],
    sourceIds: ["S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC", "S-KINWONG-HLC", "S-KINWONG-COMPUTING"],
  },
  {
    type: "risk",
    items: [
      "价格传导滞后风险：材料涨价至板厂提价可能滞后数个季度，期间毛利率承压（分析推断，非公司确认）。",
      "产业传闻未确认：部分二线板厂有定价权说法来自渠道，未经公司官方证实。",
      "需求回落风险：若 AI 服务器需求放缓，高定价权环节同样面临回吐压力。",
      "公司口径差异：龙头公司公开表态往往偏谨慎，与乐观渠道传闻存在口径差；生益/景旺官网未给出涨价幅度。",
    ],
    sourceIds: ["S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC"],
  },
];
