import type { ContentBlock } from "../types";

/** 定价权地图 Tag 内容块。 */
export const pricingPowerBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "定价权地图按三档划分——有定价权 / 半有定价权 / 无定价权——用于判断 PCB 产业链各环节在涨价周期中能否保留利润、紧缺结束后是否回吐、以及上下游成本能否转嫁。判断标准：(1) 涨价时能否保留利润；(2) 紧缺结束后是否回吐；(3) 上下游是否可以转嫁。",
    sourceIds: ["S-PRISMARK", "S-TRENDFORCE", "S-BROKERAGE-AI-PCB"],
  },
  {
    type: "table",
    caption: "PCB 产业链定价权档位",
    headers: ["环节", "定价权档位", "判断依据", "代表企业"],
    rows: [
      [
        "高端 CCL / 特种材料",
        "有定价权",
        "认证壁垒高、客户黏性强，涨价可保留利润；紧缺结束后因认证周期长不易回吐；上游树脂/玻纤成本可向下转嫁",
        "生益科技(S-SHENGYI)、松下美锐(S-PANASONIC-MEGTRON)、Isola(S-ISOLA)、Rogers(S-ROGERS)、台耀(S-ITEQ)",
      ],
      [
        "一线板厂（高端 HDI / 载板）",
        "有定价权",
        "绑定大客户长单，涨价部分保留；技术壁垒使回吐有限；部分成本可向下转嫁至终端",
        "深南电路(S-SHENNAN-002916)、欣兴电子(S-UNIMICRON)",
      ],
      [
        "二线板厂（通用多层板）",
        "半有定价权",
        "涨价时部分保留但竞争侵蚀；紧缺结束后易回吐至原价；向上转嫁受限于材料厂集中度",
        "景旺电子(S-KINWONG)、胜宏科技(S-SHENGHONG-300476)",
      ],
      [
        "低端单双面 PCB",
        "无定价权",
        "同质化严重，涨价即丢单；紧缺结束后完全回吐；上下游均无法转嫁",
        "中小板厂（非上市主体）",
      ],
    ],
    sourceIds: [
      "S-SHENGYI",
      "S-PANASONIC-MEGTRON",
      "S-ISOLA",
      "S-ROGERS",
      "S-ITEQ",
      "S-SHENNAN-002916",
      "S-UNIMICRON",
      "S-KINWONG",
      "S-SHENGHONG-300476",
      "S-PRISMARK",
      "S-TRENDFORCE",
      "S-BROKERAGE-AI-PCB",
    ],
  },
  {
    type: "callout",
    tone: "info",
    text: "判断标准说明：(1) 保留利润 = 涨价幅度 > 成本涨幅；(2) 回吐 = 紧缺结束后价格回落至涨价前水平；(3) 转嫁 = 向上游压价或向下游提价的能力。三档划分基于机构预测与产业访谈，非公司官方口径。",
    sourceIds: ["S-BROKERAGE-AI-PCB", "S-PRISMARK"],
  },
  {
    type: "bullets",
    items: [
      "高端材料牌号扩产与认证进度（生益科技、台耀、松下美锐等新增产能释放节奏）",
      "材料涨价函落地情况（CCL / 玻纤布 / 树脂厂商公开涨价函与实际成交价差）",
      "板厂毛利率季度变化（深南电路、沪电股份、胜宏科技、景旺电子毛利率趋势）",
      "下一代中板（Midplane）量产节奏（AI 服务器 / 800G 交换机用 midplane 量产时间点）",
      "a-stock-data 最新公告和研报（公司公告、券商研报对定价策略的表述更新）",
    ],
    sourceIds: [
      "S-SHENGYI",
      "S-ITEQ",
      "S-PANASONIC-MEGTRON",
      "S-SHENNAN-002916",
      "S-HUATONG-002463",
      "S-SHENGHONG-300476",
      "S-KINWONG",
      "S-BROKERAGE-AI-PCB",
    ],
  },
  {
    type: "risk",
    items: [
      "价格传导滞后风险：材料涨价至板厂提价通常滞后 1-2 个季度，期间毛利率承压（产业传闻，非公司确认）",
      "产业传闻未确认：部分二线板厂'有定价权'说法来自渠道调研，未经公司官方证实",
      "机构预测偏差：券商研报对定价权的判断基于需求持续性好转假设，若需求回落则高定价权环节同样面临回吐压力",
      "公司口径差异：生益科技等龙头公司公开表态偏谨慎，与产业乐观传闻存在口径差",
    ],
    sourceIds: ["S-BROKERAGE-AI-PCB", "S-PRISMARK", "S-TRENDFORCE", "S-SHENGYI"],
  },
];
