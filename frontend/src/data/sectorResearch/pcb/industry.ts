import type { ContentBlock } from "../types";

/** 产业格局 Tag 内容块。 */
export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "PCB 产业按 树脂 / 玻纤布 / 铜箔 / 覆铜板 / PCB 板厂 / 设备 横向展开。材料端长期由日本、美国、台湾等厂商在高端牌号上领先；板厂端台湾在高端与载板长期领先、大陆在产值与部分高速板领域加速追赶；设备端海外主导、国产替代空间大。以下表格以定性结构为主，具体市场份额数字尚无公开资料确认。（分析推断）",
  },
  {
    type: "table",
    caption: "PCB 产业链全球主导、国内梯队与壁垒类型（定性）",
    headers: ["环节", "全球主导", "国内梯队", "壁垒类型", "代表企业/锚点"],
    rows: [
      [
        "树脂",
        "日/美高频高速树脂体系长期领先（手册未读）",
        "中低端为主，高端仍偏依赖进口（推断）",
        "材料壁垒",
        "尚无公开资料确认具体份额",
      ],
      [
        "玻纤布",
        "日/台高端超薄 / Low-Dk 玻纤布领先（推断）",
        "中低端基本自主，高端仍存差距（推断）",
        "材料壁垒",
        "尚无公开资料确认",
      ],
      [
        "铜箔",
        "日系等在 HVLP / 压延铜箔领先（推断）",
        "电解铜箔基本自主，RTF/HVLP 追赶中（推断）",
        "材料+设备壁垒",
        "与 CCL 体系相关（见生益）",
      ],
      [
        "覆铜板",
        "日/美/台高频高速 CCL 主导（推断）",
        "生益科技已进入全球头部梯队叙事；官网确认高速Synamic8GX（一般 Dk=3.62/Df=0.0016；Dk@10GHz=3.66/Df@10GHz=0.0033）、射频mmWave77(Df0.0010)、IC封装SI13U/SI10US产品线",
        "材料+客户认证",
        "生益科技（S-SHENGYI-HIGHSPEED / S-SHENGYI-RF / S-SHENGYI-IC）",
      ],
      [
        "PCB 板厂（AI/高速）",
        "台湾/日欧在载板与部分高端板领先（推断）",
        "景旺电子官网确认最高80层、AI服务器PCB制造商定位、70+层高多层、9阶HDI；沪电/深南/胜宏等公告正文未读",
        "资本+工艺+客户认证",
        "景旺电子（S-KINWONG-HLC / S-KINWONG-COMPUTING）",
      ],
      [
        "PCB 板厂（总体）",
        "台湾长期居全球产值前列；日韩在载板/HDI 强（推断）",
        "大陆产值占比高，但高端高多层仍追赶中（推断）",
        "资本+产能+客户认证",
        "S-KINWONG-HLC、S-KINWONG-COMPUTING",
      ],
      [
        "设备",
        "日/欧/美在钻孔/曝光/镭射等居主导（推断）",
        "国产在中低端批量替代，高端仍依赖海外（推断）",
        "设备+工艺壁垒",
        "尚无公开资料确认",
      ],
    ],
    sourceIds: ["S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC", "S-KINWONG-HLC", "S-KINWONG-COMPUTING"],
  },
  {
    type: "paragraph",
    text: "公司口径（已读官网产品页）：景旺电子高多层最高80层、材料分级M2~M9、40:1厚径比、AI服务器PCB制造商定位、70+层高多层、9阶HDI、高速板材料库；生益科技高速产品Synamic8GX（一般 Dk=3.62/Df=0.0016；Dk@10GHz=3.66/Df@10GHz=0.0033）、射频mmWave77(Dk3.0/Df0.0010)、IC封装SI13U(CTE13/Tg245℃)/SI10US(CTE10/Tg280℃)等。",
    sourceIds: ["S-KINWONG-HLC", "S-KINWONG-COMPUTING", "S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC"],
  },
  {
    type: "callout",
    tone: "emphasis",
    text: "判断框架（分析推断）：板厂端部分大陆与台湾厂商已进入全球 AI/服务器供应链叙事，但具体客户认证与份额需公告与客户名单核验；上游高频高速树脂、高端玻纤布与精密设备仍以国产替代为主逻辑。沪电/深南/胜宏等公司公告正文尚未读取，不作为正式 sourceId。",
    sourceIds: ["S-KINWONG-HLC", "S-KINWONG-COMPUTING", "S-SHENGYI-HIGHSPEED", "S-SHENGYI-RF", "S-SHENGYI-IC"],
  },
];
